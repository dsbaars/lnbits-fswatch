import asyncio
from time import monotonic

from loguru import logger

from lnbits.settings import settings

from .models import (
    EVENT_CHANGED,
    EVENT_HEALTHY,
    EVENT_HEARTBEAT,
    EVENT_UNHEALTHY,
    FundingSourceState,
    StoredWatchSettings,
)
from .services import dispatch_event, get_watch_settings, read_funding_source_state

VOID_FALLBACK_ERROR = "LNbits switched to VoidWallet, payments are disabled"


def _still_on_void_fallback(
    state: FundingSourceState, last_source: str, arrived_on_void: bool
) -> bool:
    """
    Whether LNbits is on VoidWallet because it *arrived* there, as opposed to
    being deliberately configured for it.

    Arriving on VoidWallet is a fallback whatever the settings say by now: the
    watchdog rewrites `lnbits_backend_wallet_class` to VoidWallet as well, so
    only the transition itself reveals what happened. It stays a fallback until
    the funding source changes again -- a later check has no transition left to
    look at and would otherwise read as perfectly healthy.

    A watcher that starts up already on VoidWallet has no transition to go on
    and cannot tell a fallback from a deliberate choice. The caller seeds the
    latch for that case, so being on VoidWallet is reported as unhealthy from
    the very first check without alerting on it.
    """
    if state.funding_source != "VoidWallet":
        return False
    return arrived_on_void or last_source != "VoidWallet"


def _health_after_probe(
    state: FundingSourceState,
    config: StoredWatchSettings,
    last_healthy: bool,
    failures: int,
) -> tuple[bool, int]:
    """
    A single failed probe is not enough to call the funding source unhealthy,
    but once it IS unhealthy only a successful probe clears it again -- raising
    the threshold mid-outage must not look like a recovery.
    """
    if state.healthy:
        return True, 0
    failures += 1
    return last_healthy and failures < config.failure_threshold, failures


def _heartbeat_due(config: StoredWatchSettings, last_dispatch: float | None) -> bool:
    """
    Whether a keepalive is owed. Any event counts as proof of life, so a
    transition postpones the next heartbeat instead of being followed by one.
    """
    if not config.heartbeat_seconds:
        return False
    if last_dispatch is None:
        # nothing sent since this watcher came up: say so straight away, which
        # is what makes a restart or a re-enabled extension visible at all
        return True
    # monotonic, so a clock adjustment cannot postpone a beat indefinitely
    return monotonic() - last_dispatch >= config.heartbeat_seconds


def _decide_event(
    state: FundingSourceState,
    config: StoredWatchSettings,
    last_source: str,
    last_healthy: bool,
    failures: int,
    last_dispatch: float | None,
) -> tuple[str | None, bool, int]:
    """
    The event this check should fire, if any, plus the health state to carry
    into the next one. Expects `state` to already reflect a VoidWallet
    fallback, which only the caller can recognise.
    """
    healthy, failures = _health_after_probe(state, config, last_healthy, failures)

    if state.funding_source != last_source:
        # a new funding source starts from a clean health baseline, so its
        # state is reported as-is and never alerted on twice
        failures = 0 if state.healthy else config.failure_threshold
        return EVENT_CHANGED, state.healthy, failures

    if healthy != last_healthy:
        return (EVENT_HEALTHY if healthy else EVENT_UNHEALTHY), healthy, failures

    if _heartbeat_due(config, last_dispatch):
        return EVENT_HEARTBEAT, healthy, failures

    return None, healthy, failures


async def watch_funding_source() -> None:
    """
    Poll the runtime funding source and fire a webhook when it changes.

    The baseline is the *configured* funding source, so a server that booted
    straight into the VoidWallet fallback reports on the first check.
    """
    last_source: str | None = None
    last_healthy = True
    failures = 0
    last_dispatch: float | None = None
    arrived_on_void = False

    while settings.lnbits_running:
        interval = 60
        try:
            config = await get_watch_settings()
            interval = config.interval_seconds

            if not config.enabled:
                # re-baseline when the watcher is switched back on
                last_source, last_healthy, failures = None, True, 0
                last_dispatch = None
                arrived_on_void = False
            else:
                state = await read_funding_source_state(config.probe_status)

                if last_source is None:
                    last_source = state.configured_funding_source
                    # Baselining onto VoidWallet is ambiguous: a deliberate
                    # VoidWallet install and a watchdog switch this watcher
                    # arrived too late to witness look identical. Alerting is
                    # therefore wrong -- but so is claiming health, because
                    # payments are disabled either way. Start unhealthy AND
                    # start quiet, by baselining last_healthy to match.
                    arrived_on_void = state.funding_source == "VoidWallet"
                    last_healthy = not arrived_on_void

                arrived_on_void = _still_on_void_fallback(
                    state, last_source, arrived_on_void
                )
                if arrived_on_void:
                    state.healthy = False
                    state.error = state.error or VOID_FALLBACK_ERROR

                event_type, healthy, failures = _decide_event(
                    state, config, last_source, last_healthy, failures, last_dispatch
                )

                # report the verdict, not the raw read. Below failure_threshold
                # the watcher deliberately still considers the source healthy,
                # and a heartbeat is the first event that can go out while the
                # two disagree -- a transition only ever fires on a poll where
                # they already agree. `error` is left as observed, so a
                # tolerated probe failure stays visible to the receiver.
                state.healthy = healthy

                # commit the new state BEFORE dispatching: a dispatch that
                # raises must not re-fire the same event on every poll
                # a heartbeat reports the state, it does not report a
                # transition, so it carries no previous funding source
                previous_source: str | None = (
                    None if event_type == EVENT_HEARTBEAT else last_source
                )
                last_source = state.funding_source
                last_healthy = healthy

                if event_type:
                    last_dispatch = monotonic()
                    await dispatch_event(event_type, state, previous_source, config)

        except Exception as exc:
            logger.error(f"fswatch: error while checking the funding source: {exc}")

        await asyncio.sleep(interval)

import asyncio

from loguru import logger

from lnbits.settings import settings

from .models import EVENT_CHANGED, EVENT_HEALTHY, EVENT_UNHEALTHY
from .services import dispatch_event, get_watch_settings, read_funding_source_state


async def watch_funding_source() -> None:
    """
    Poll the runtime funding source and fire a webhook when it changes.

    The baseline is the *configured* funding source, so a server that booted
    straight into the VoidWallet fallback reports on the first check.
    """
    last_source: str | None = None
    last_healthy = True
    failures = 0

    while settings.lnbits_running:
        interval = 60
        try:
            config = await get_watch_settings()
            interval = config.interval_seconds

            if not config.enabled:
                # re-baseline when the watcher is switched back on
                last_source, last_healthy, failures = None, True, 0
            else:
                state = await read_funding_source_state(config.probe_status)

                if last_source is None:
                    last_source = state.configured_funding_source
                    last_healthy = True

                if state.healthy:
                    failures = 0
                    healthy = True
                else:
                    failures += 1
                    # a single failed probe is not enough to call it unhealthy,
                    # but once it IS unhealthy only a successful probe clears
                    # it again -- raising the threshold mid-outage must not
                    # look like a recovery
                    healthy = last_healthy and failures < config.failure_threshold

                event_type = None
                if state.funding_source != last_source:
                    event_type = EVENT_CHANGED
                    if state.funding_source == "VoidWallet":
                        # arriving on VoidWallet is a fallback whatever the
                        # settings say by now: the watchdog rewrites
                        # lnbits_backend_wallet_class as well, so comparing
                        # against the configured source is not enough here
                        state.healthy = False
                        state.error = state.error or (
                            "LNbits switched to VoidWallet, payments are disabled"
                        )
                    # a new funding source starts from a clean health baseline,
                    # so its state is reported as-is and never alerted on twice
                    healthy = state.healthy
                    failures = 0 if state.healthy else config.failure_threshold
                elif healthy != last_healthy:
                    event_type = EVENT_HEALTHY if healthy else EVENT_UNHEALTHY

                # commit the new state BEFORE dispatching: a dispatch that
                # raises must not re-fire the same event on every poll
                previous_source = last_source
                last_source = state.funding_source
                last_healthy = healthy

                if event_type:
                    await dispatch_event(event_type, state, previous_source, config)

        except Exception as exc:
            logger.error(f"fswatch: error while checking the funding source: {exc}")

        await asyncio.sleep(interval)

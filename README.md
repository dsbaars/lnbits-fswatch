# Funding Source Watch (`fswatch`)

Fires a webhook when the LNbits funding source changes, most importantly when
it silently falls back to `VoidWallet`.

## Why

LNbits has three ways to end up on a different funding source than the one you
configured, and only one of them tells you about it:

| Path | Core behaviour |
| --- | --- |
| Backend unreachable at startup, after `FUNDING_SOURCE_MAX_RETRIES` | `logger.warning` only, and `lnbits_backend_wallet_class` is *not* updated, so the admin UI still shows the old backend |
| Watchdog balance delta exceeded | `watchdog_check` notification (Telegram / Nostr / email) |
| Manual change in the admin UI | `settings_update` notification, without saying which backend |

There is also no automatic runtime fallback: if the node dies *after* startup,
LNbits keeps the funding source and payments simply fail. This extension covers
that gap too, by probing the backend on every check.

## What it does

A background task polls every `interval_seconds`:

1. reads the **runtime** funding source (`get_funding_source()`) and the
   **configured** one (`settings.lnbits_backend_wallet_class`, resolved through
   the wallets module so the legacy `CLightningWallet` alias matches the
   runtime `CoreLightningWallet`);
2. optionally calls `status()` on the backend, with a 15s timeout, to see if it
   is actually reachable;
3. compares against the previous check and POSTs a webhook when something
   changed.

Arriving on `VoidWallet` is always reported as `healthy: false`, whether LNbits
fell back at startup or the watchdog switched over at runtime. That distinction
matters, because the watchdog rewrites `lnbits_backend_wallet_class` to
VoidWallet as well, so afterwards the runtime and configured backend agree and
only the transition itself reveals what happened. It then *stays* unhealthy
until the funding source changes again: once the transition is behind it, a
fresh check has nothing left to look at and would otherwise read as perfectly
healthy while payments are still disabled.

Deliberately running on VoidWallet stays quiet, since there is no transition.
A watcher that finds itself on VoidWallet without having seen the transition —
because it just started, or was switched off and on again — cannot tell a
deliberate install from a watchdog switch it arrived too late to witness. It
therefore does not alert, but it does report `healthy: false`: payments are
disabled either way, and reporting health it has not verified would be the one
answer that is wrong in both cases.

**Backends that are never probed:** `VoidWallet` (nothing to probe),
`CoreLightningWallet` and `ClicheWallet`. The latter two call blocking code
inside `status()` (`self.ln.listfunds()` and `create_connection()`), which would
stall the shared LNbits event loop, and `asyncio.wait_for` cannot interrupt
a synchronous call. On those backends the extension still detects funding source
changes, it just cannot report reachability.

The baseline for the first check is the *configured* funding source, so a
server that booted straight into the `VoidWallet` fallback reports immediately
instead of accepting it as normal.

## Events

| `event` | When |
| --- | --- |
| `funding_source_changed` | the runtime funding source is not what it was on the previous check |
| `funding_source_unhealthy` | `status()` failed `failure_threshold` times in a row |
| `funding_source_healthy` | the backend answered again after being unhealthy |
| `heartbeat` | nothing changed and the keepalive interval elapsed |
| `test` | you pressed "Test webhook" |

## Heartbeat

The events above are transitions, so silence means "nothing changed" *and*
"the extension is disabled", "LNbits is down", "an upgrade did not restore the
extension", "the webhook URL rotated and every delivery 4xxs". A receiver
cannot tell those apart, which is the failure this extension exists to catch,
one layer up.

Set **Heartbeat interval** to a non-zero number of seconds and a `heartbeat`
event goes out whenever that long has passed without any other event. The
receiver can then treat silence as unverified rather than healthy, and every
payload carries `heartbeat_seconds` so it can derive the deadline instead of
having it configured in two places.

It is a separate interval from the check interval, so a 30 second poll does not
have to mean 2880 webhooks a day. A heartbeat can only be sent on a poll
boundary, so a heartbeat interval below the check interval just means "every
poll". `0` disables it and keeps the transition-only behaviour.

Any event resets the timer, since a transition is proof of life too. The
watcher also beats immediately when it starts or is re-enabled, which is what
makes a restart visible. Only the most recent heartbeat is kept in the event
log, so a keepalive cannot push the transitions out of it, and heartbeats are
never sent to the admin notification channels.

## Webhook

`POST` with a JSON body:

```json
{
  "event": "funding_source_changed",
  "timestamp": 1760000000,
  "last_check": "2025-10-09T08:53:20+00:00",
  "site_title": "LNbits",
  "lnbits_version": "1.5.6",
  "funding_source": "VoidWallet",
  "previous_funding_source": "LndRestWallet",
  "configured_funding_source": "LndRestWallet",
  "healthy": true,
  "error": null,
  "balance_msat": null,
  "interval_seconds": 60,
  "heartbeat_seconds": 900
}
```

`timestamp` is when the payload was built, `last_check` when the funding source
was actually read: a probe is allowed 15 seconds, so they are not the same
moment. `previous_funding_source` is `null` for events that are not transitions
(`heartbeat`, `test`). `heartbeat_seconds` is `0` when the keepalive is off.

`healthy` is the watcher's verdict, not the raw reading, so it agrees with the
events it sends. A probe that fails while `failure_threshold` has not been
reached is deliberately still `healthy: true` — alerting there is exactly what
the threshold exists to prevent. `error` carries the last observed probe
failure regardless, so a tolerated blip is still visible: **alert on `healthy`,
not on `error`**. Before the keepalive existed this could never be observed,
because a transition only ever fires on a check where the two already agree.

Headers: `X-LNbits-Event`, plus `X-LNbits-Signature: sha256=<hmac>` when a
secret is set, an HMAC-SHA256 over the raw request body.

Verify it on the receiving end:

```python
import hashlib
import hmac

expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
hmac.compare_digest(expected, request.headers["X-LNbits-Signature"])
```

Each event is written to the log *before* delivery is attempted, so a failed
database write can never turn into a webhook that is re-sent on every poll.
Delivery is retried up to 3 times (1s, 2s backoff), but not for a permanent 4xx:
a receiver that rejects the payload will reject the retry too. Redirects are
**not** followed and are recorded as a failure: point the setting at the final
URL. The result is stored per event and shown in the UI.

`LNBITS_CALLBACK_URL_RULES` is honoured. If you have rules configured, the
webhook URL has to match one of them. Be aware that this core allowlist matches
a regex against `scheme://netloc` and never validates the address actually
connected to, so it is a policy control, not an SSRF defence.

Enabling "Also send LNbits admin notifications" additionally pushes each event
through the Telegram / Nostr / email channels from the admin notification
settings.

## Install

Drop the folder in `lnbits/extensions/fswatch` and restart LNbits: any directory
there is picked up as a pre-packed extension and its migrations run on startup.
Then enable it on the Extensions page.

## API

Every API endpoint requires an admin account. The page route `/fswatch/` itself
only requires a logged-in account, following the LNbits extension
convention. A non-admin who opens it gets an empty page, because every call behind it is
rejected with a 403. Add `fswatch` to `LNBITS_ADMIN_EXTENSIONS` to hide it from
non-admins entirely.

| Method | Path |
| --- | --- |
| `GET` | `/fswatch/api/v1/state` (funding source right now) |
| `GET` / `PUT` | `/fswatch/api/v1/settings` |
| `GET` / `DELETE` | `/fswatch/api/v1/events` |
| `POST` | `/fswatch/api/v1/test` |

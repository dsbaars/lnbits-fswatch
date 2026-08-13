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
only the transition itself reveals what happened. Deliberately running on
VoidWallet stays quiet, since there is no transition.

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
| `test` | you pressed "Test webhook" |

## Webhook

`POST` with a JSON body:

```json
{
  "event": "funding_source_changed",
  "timestamp": 1760000000,
  "site_title": "LNbits",
  "lnbits_version": "1.5.6",
  "funding_source": "VoidWallet",
  "previous_funding_source": "LndRestWallet",
  "configured_funding_source": "LndRestWallet",
  "healthy": true,
  "error": null,
  "balance_msat": null
}
```

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

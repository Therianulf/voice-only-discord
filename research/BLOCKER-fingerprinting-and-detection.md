# BLOCKER: Discord Anti-Bot and Client Fingerprinting

## TL;DR

- Discord's strongest "is this the real web client?" signal is the **`X-Super-Properties`** header (REST) and the matching **`properties`** object in the gateway IDENTIFY payload. Mismatched or stale values draw scrutiny.
- The **`client_build_number`** in those properties **must be kept current** by scraping Discord's served JS bundles, otherwise the account looks like an outdated/automation client. Reference clients refresh this regularly.
- **TLS/JA3 fingerprinting** is real but not currently the primary line of defense Discord uses against user-account clients (CDN-level checks at `cloudflare/discord.com` exist; using a Chrome-impersonating HTTP stack like `curl-impersonate`/`utls`/`rquest` is a safety belt, not a hard requirement for low-volume read-only access).
- **Behavioral signals dominate**: heartbeat cadence, presence of `op 14` lazy-guild subscriptions, READY_SUPPLEMENTAL handling, never-exceed REST rate limits, and `/science` telemetry are how Discord separates "weird quiet user" from "bot".
- **abaddon** identifies as Chrome 67 on Windows 10 with a hardcoded default `client_build_number`, sends a full super-properties header, and does *not* send `/science` telemetry. The README explicitly warns this raises spam-filter risk for sensitive actions.
- A **WebView2 / embedded-browser** approach sidesteps every fingerprint problem above but creates new ones (cookie/storage isolation, no clean voice-only UI, you still need IPC to extract the channel list).

---

## 1. The `X-Super-Properties` header (and its Identify-payload twin)

`X-Super-Properties` is a **base64-encoded JSON object** sent on every REST request to `discord.com/api/*` from the web client. The same JSON shape is sent inside the gateway IDENTIFY payload as the `d.properties` object. Discord uses these two to correlate "Is this client telling the same story over WebSocket and HTTPS?" ([X-Super-Properties wiki – KhafraDev/discord-verify](https://github.com/KhafraDev/discord-verify/wiki/X-Super-Properties), [discord-userdoccers](https://docs.discord.food/gateway/using-gateway)).

The 15 known fields (taken verbatim from `abaddon/src/discord/objects.cpp` and `discord.cpp` lines 2787–2854):

```json
{
  "os": "Windows",
  "browser": "Chrome",
  "device": "",
  "system_locale": "en-US",
  "has_client_mods": false,
  "browser_user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/67.0.3396.87 Safari/537.36",
  "browser_version": "67.0.3396.87",
  "os_version": "10",
  "referrer": "",
  "referring_domain": "",
  "referrer_current": "",
  "referring_domain_current": "",
  "release_channel": "stable",
  "client_build_number": 363557,
  "client_event_source": null
}
```

The **`client_build_number`** is the one field Discord actively updates and re-checks. Discord ships a new build of the web client roughly weekly. An old build number is the single biggest "this isn't really Chrome" tell. To stay convincing, projects scrape `https://discord.com/app`, pull the last referenced JS chunk from `/assets/*.js`, and regex out the `Build Number: 363557, Version Hash: <hash>` string baked into the bundle ([adityaxdiwakar/discord-build-scraper updater.py](https://github.com/adityaxdiwakar/discord-build-scraper/blob/master/updater.py)):

```python
regex = re.compile('Build Number: [0-9]+, Version Hash: [A-Za-z0-9]+')
```

Mature unofficial clients re-scrape on startup (sometimes daily). abaddon **does not auto-scrape** — `m_build_number` defaults to `363557` and the user can override via settings, but a stale default is a known weakness.

The header is sent as `X-Super-Properties: <base64>` and also as `X-Discord-Locale: <system_locale>` (see abaddon `discord.cpp:2853`). Discord does not require this header in the strict HTTP sense — requests succeed without it — but its absence is itself a tell, "most likely used to detect bots" ([discord-verify wiki](https://github.com/KhafraDev/discord-verify/wiki/X-Super-Properties)).

Newer reverse engineering also notes the encoded blob can contain `client_launch_id` and `launch_signature` fields generated at startup — not in abaddon, a possible "real client" beacon ([HN](https://news.ycombinator.com/item?id=39763438)).

## 2. TLS / JA3 / JA4 fingerprinting

Does Discord actually check TLS fingerprints? The honest answer in 2026 is: **CloudFlare in front of `discord.com` collects JA3/JA4, and Discord's anti-abuse system absolutely *can* read it**, but there is no public evidence Discord aggressively blocks read-only user-account traffic on TLS fingerprint alone. What gets blocked is:

- The classic mismatch: HTTP layer claims `User-Agent: Mozilla/.../Chrome/...` but the TLS ClientHello looks like Go's `crypto/tls`, Python `requests`+OpenSSL, or `libcurl` default order ([Fastly: state of TLS fingerprinting](https://www.fastly.com/blog/the-state-of-tls-fingerprinting-whats-working-what-isnt-and-whats-next), [fingerprint.com](https://fingerprint.com/blog/what-is-tls-fingerprinting-transport-layer-security/)).
- Datacenter ASNs combined with that mismatch — instant captcha or 403.

The official desktop client is an Electron/Chromium wrapper; its TLS fingerprint is **identical to Chrome stable** because it links BoringSSL the same way. An arbitrary HTTP client (Python `httpx`, Go `net/http`, C++ `cpr`/`libcurl`) will have a different cipher list, extension order, GREASE values, and ALPN. JA4 specifically captures ALPN, SNI, and sorted cipher/extension hashes, which makes it harder to fudge ([Scrapfly JA3/JA4 explainer](https://scrapfly.io/web-scraping-tools/ja3-fingerprint)).

To spoof Chrome's TLS:

- **C/C++**: [curl-impersonate](https://github.com/lwthiker/curl-impersonate) — replaces libcurl's TLS stack with BoringSSL and injects Chrome's exact ClientHello at compile time.
- **Python**: [curl_cffi](https://github.com/lexiforest/curl_cffi) — Python bindings over curl-impersonate.
- **Go**: [utls](https://github.com/refraction-networking/utls) — fork of `crypto/tls` exposing a `UClient` with `HelloChrome_Auto` profile that tracks current stable Chrome.
- **Rust**: [rquest](https://github.com/0x676e67/rquest) / [reqwest-impersonate](https://github.com/4JX/reqwest-impersonate) — reqwest forks plumbed through BoringSSL.

**Verdict for this project**: TLS spoofing is **probably overkill** for a single user reading guilds/channels and joining a voice channel. The volume is tiny, the IP is residential, and the account is the user's real account. abaddon ships without curl-impersonate and (despite the README warnings) works for thousands of users. *Reserve TLS impersonation as a fallback if you see HTTP 403s or captcha walls from an otherwise-correct client.*

## 3. Gateway IDENTIFY payload

`op: 2` IDENTIFY is where Discord most cleanly tells "bot account using `intents`" apart from "user account using `capabilities` + `client_state`". The web-client-style identify ([discord.food docs](https://docs.discord.food/gateway/gateway-events), abaddon `SendIdentify()`):

```json
{
  "op": 2,
  "d": {
    "token": "<user token>",
    "capabilities": 4605,
    "properties": { /* the 15-field super-properties JSON above */ },
    "presence": { "status": "online", "since": 0, "activities": [], "afk": false },
    "compress": false,
    "client_state": {
      "guild_hashes": {},
      "highest_last_message_id": "0",
      "read_state_version": 0,
      "user_guild_settings_version": -1,
      "user_settings_version": -1
    }
  }
}
```

Critical distinctions vs a typical "bot" identify:

- User clients send **`capabilities`** (a bit field — abaddon hardcodes `4605`, the web client uses `16381` in current docs), bot clients send **`intents`**. Sending both, or sending `intents` from a user token, is a red flag ([discord-userdoccers capabilities](https://deepwiki.com/discord-userdoccers/discord-userdoccers/9.2-gateway-intents-and-capabilities)).
- User clients send **`client_state`** so the gateway can send delta READY ([discord-api-docs issue #2704](https://github.com/discord/discord-api-docs/issues/2704)). Missing `client_state` from a user token = suspicious.
- `properties` must match the REST-side `X-Super-Properties` field-for-field — Discord may correlate.

## 4. Other HTTP request headers + ordering

abaddon's `DiscordClient::SetHeaders()` (`discord.cpp:2825`) sets:

```cpp
m_http.SetPersistentHeader("Sec-Fetch-Dest", "empty");
m_http.SetPersistentHeader("Sec-Fetch-Mode", "cors");
m_http.SetPersistentHeader("Sec-Fetch-Site", "same-origin");
m_http.SetPersistentHeader("X-Debug-Options", "bugReporterEnabled");
m_http.SetPersistentHeader("Accept-Language", "en-US,en;q=0.9");
```

Plus, after IDENTIFY (`discord.cpp:2852-2853`):

```cpp
m_http.SetPersistentHeader("X-Super-Properties", Glib::Base64::encode(j.dump()));
m_http.SetPersistentHeader("X-Discord-Locale", identity.Properties.SystemLocale);
```

And per-request: `Origin: https://discord.com`, `Referer: https://discord.com/channels/...`, `Authorization: <token>`, `User-Agent: <browser UA>`. The web client also sends **`X-Discord-Timezone`** (e.g. `America/Los_Angeles`) — abaddon does **not** ([discord.food authentication](https://docs.discord.food/authentication)).

Other web-client headers worth replicating:
- `X-Fingerprint`: opaque device ID obtained from `POST /api/v9/auth/fingerprint`. Sent only by unauthenticated clients during login/account creation, then dropped ([luna unofficial docs – tracking](https://luna.gitlab.io/discord-unofficial-docs/docs/science/)).
- `X-Context-Properties`: base64 JSON describing the UI location an action was taken from (e.g. "Join Voice Channel from Channel List"). Often required for join-guild, friend-request, etc.
- Header **order** matters to some bot-detection stacks; browser-impersonating HTTP libraries handle this.

## 5. Behavioral signals

What the official web client does that bots usually don't:

1. **Heartbeat cadence**: respect the `heartbeat_interval` from `op 10 HELLO` (typically ~41250ms) and apply the `jitter * heartbeat_interval` for the *first* heartbeat. Clockwork-precise intervals are bot-like.
2. **`op 14` lazy guild subscribe**: After READY, the web client subscribes to member-list ranges per visible channel — usually `{"channels": {"<channel_id>": [[0, 99]]}}` on guild open, then `[[0,99],[100,199]]` as the user scrolls ([Lazy Guilds docs](https://arandomnewaccount.gitlab.io/discord-unofficial-docs/lazy_guilds.html)). A user account that *never* sends `op 14` looks abnormal.
3. **READY vs READY_SUPPLEMENTAL**: the official client expects and processes both. READY contains required state; READY_SUPPLEMENTAL has merged presences + member tweaks ([discord.food gateway events](https://docs.discord.food/gateway/gateway-events)).
4. **Resume vs reconnect**: on disconnect, web client first tries `op 6 RESUME` with the last seq number; only on `4007/4009` does it re-IDENTIFY. Hammering IDENTIFY is a strong bot signal.
5. **REST rate limits**: the web client throttles itself well below the bucket limits. Burst-firing `/channels/{id}/messages` or `/guilds/{id}/members` rapidly is the #1 way to get rate-limited and then captcha-walled.
6. **`/science` telemetry**: web client `POST`s batched analytics events (channel-switch, modal-open, message-ack) to `https://discord.com/api/v9/science` every few seconds. abaddon does not, and its README acknowledges this gap ([abaddon README](https://github.com/uowuo/abaddon/blob/master/README.md), [luna tracking docs](https://luna.gitlab.io/discord-unofficial-docs/docs/science/)). For a voice-channel-only client, replicating a *minimal stub* of `/science` (e.g., periodic `app_opened`, `channel_opened` events keyed to the guild/channel being viewed) is the highest-ROI fingerprint improvement after `X-Super-Properties`.

## 6. hCaptcha / captcha triggers

hCaptcha is invoked at the **login flow** and at **specific high-risk actions** (account changes, friend invites, mass-join). Triggers ([discord.py-self captcha discussion](https://github.com/dolfies/discord.py-self/discussions/838)):

- **IP reputation**: datacenter ASNs (AWS, GCP, OVH) → near-100% captcha probability; residential IP → rare captcha.
- **Fresh token** (just-logged-in or just-created account): captcha-prone for first few hours.
- **Unrecognized device**: new `X-Super-Properties` + new IP combo triggers email verification + captcha.
- **Geo/UA mismatch**: User-Agent says Windows but TLS/JA3 looks like Linux Go binary.

For this project: residential IP (user's home), long-lived token from already-logged-in Discord session, stable super-properties → captcha should essentially never appear. The riskier action is the **initial login**; if the user can copy their token from the official client (or use OAuth), avoid programmatic login entirely.

## 7. What abaddon specifically does

Direct quotes from the repo:

- **README** ([uowuo/abaddon](https://github.com/uowuo/abaddon)): *"using a browser user agent, sending the same IDENTIFY message that the official web client does, using API v9 endpoints in all cases"* and the gap: *"the web client sends lots of telemetry via the /science endpoint (uBlock origin stops this) as well as in the headers of all requests."* It also warns: *"third-party clients tend to upset the spam filter more often"*, listing risky actions as joining/leaving servers, frequent reconnections, starting new DMs, profile editing.
- **`src/discord/objects.hpp`** defines `IdentifyMessage`, `IdentifyProperties` (15 fields above), and `ClientStateProperties` (`guild_hashes`, `highest_last_message_id`, `read_state_version`, `user_guild_settings_version`, `user_settings_version`).
- **`src/discord/objects.cpp`** `to_json(IdentifyProperties&)` writes the exact super-properties shape Discord expects.
- **`src/discord/discord.cpp:2787-2814`** `SendIdentify()` hardcodes `OS=Windows, Browser=Chrome, BrowserVersion=67.0.3396.87, OSVersion=10`, `capabilities=4605`. Chrome 67 is from May 2018; this is **dramatically out of date** — current stable is ~Chrome 131+. abaddon relies on Discord not enforcing UA-vs-build-number consistency strictly. A new project should pin to a current Chrome build.
- **`src/discord/discord.cpp:2825-2833`** `SetHeaders()` is the full header set (Sec-Fetch-*, X-Debug-Options, Accept-Language).
- **`src/discord/discord.cpp:2835-2854`** `SetSuperPropertiesFromIdentity()` builds the base64 header from the same JSON. Note: it builds AFTER identify, meaning early REST calls (if any) go out *without* the header.
- **HTTP client** (`src/discord/httpclient.cpp`): uses libcurl via the project's `http::` wrapper. **No TLS impersonation** — out-of-the-box libcurl JA3. Sets `Origin: https://discord.com`, `Authorization`, `Content-Type`, and user-set `User-Agent` (default `"Abaddon"` if unconfigured — that string in a UA is itself a tell).
- **WebSocket** (`src/discord/websocket.cpp`): uses `IXWebSocket`, sets `User-Agent` and `Origin: https://discord.com` as extra headers; the source contains the comment `// idk if this actually works`.

## 8. WebSocket-direct vs WebView2 / embedded-browser approach

Embedding Microsoft Edge **WebView2** (or CEF/Electron) and loading `https://discord.com/app`:

**Pros — fingerprint problems vanish:** Real Chromium TLS = matching JA3/JA4. Every header (`Sec-Fetch-*`, `X-Super-Properties`, `X-Discord-Locale`, `X-Discord-Timezone`, `X-Context-Properties`) is generated by Discord's own JS, always current. `client_build_number` is whatever Discord serves. Captchas, login, voice WebRTC, encryption negotiation all just work. Account is using the *actual* web client; impossible to flag as third-party.

**Cons — new problems:** Hiding everything except servers + voice requires CSS injection (fragile) or DOM scripting via CDP — selectors change. Low-CPU goal undermined: full web app runs 200–400 MB RAM, similar to the Electron client. Click-to-join-voice needs scripted DOM interaction. Token/session lives in WebView2's user-data folder; you cede auth control. Multi-account is awkward (separate user-data dirs). WebView2 is Windows-only (fine for this user).

**Hybrid option**: use WebView2 only for **login + periodic fingerprint capture**, then run a native WebSocket client that copies `X-Super-Properties`, cookies, and token from WebView2's storage. Caveat: Discord can detect "two clients on one token" simultaneously connected to the gateway, so the WebView2 instance must be logged out or closed during native operation.

---

## Recommendations for this project

1. **Native WebSocket approach** (like abaddon), not WebView2 — matches the "tiny, low-CPU" goal.
2. **Scrape `client_build_number` weekly** from `https://discord.com/app`; persist it. Pin a current Chrome UA (131+ on Windows 10/11).
3. **Replicate abaddon's super-properties + SetHeaders + IDENTIFY shape** verbatim, but with current Chrome version and `capabilities = 16381`.
4. **Send `op 14` lazy-guild subscriptions** (`[[0, 99]]`) on guild open even without rendering members.
5. **Stub `/science`** with `app_opened` + `channel_opened` events — closes abaddon's #1 known gap.
6. **Skip TLS impersonation initially**; add `curl-impersonate` only if 403s/captchas appear.
7. **Do not implement programmatic login** — paste/copy the existing token. Avoid `/auth/login`.
8. **Throttle REST calls** to ≤4/sec, **RESUME before re-IDENTIFY**, and never burst-join guilds.

---

## Citations

- [abaddon README – uowuo/abaddon](https://github.com/uowuo/abaddon/blob/master/README.md)
- [abaddon `src/discord/discord.cpp` – SendIdentify, SetHeaders, SetSuperPropertiesFromIdentity](https://github.com/uowuo/abaddon/blob/master/src/discord/discord.cpp)
- [abaddon `src/discord/objects.hpp` – IdentifyProperties, ClientStateProperties](https://github.com/uowuo/abaddon/blob/master/src/discord/objects.hpp)
- [abaddon `src/discord/objects.cpp` – JSON serialization](https://github.com/uowuo/abaddon/blob/master/src/discord/objects.cpp)
- [abaddon `src/discord/httpclient.cpp`](https://github.com/uowuo/abaddon/blob/master/src/discord/httpclient.cpp)
- [abaddon `src/discord/websocket.cpp`](https://github.com/uowuo/abaddon/blob/master/src/discord/websocket.cpp)
- [X-Super-Properties wiki – KhafraDev/discord-verify](https://github.com/KhafraDev/discord-verify/wiki/X-Super-Properties)
- [discord-userdoccers – Using Gateway](https://docs.discord.food/gateway/using-gateway)
- [discord-userdoccers – Gateway Events (Identify, Ready, Ready Supplemental)](https://docs.discord.food/gateway/gateway-events)
- [discord-userdoccers – Authentication](https://docs.discord.food/authentication)
- [discord-userdoccers – Voice Connections](https://docs.discord.food/topics/voice-connections)
- [discord-userdoccers DeepWiki – Gateway Intents and Capabilities](https://deepwiki.com/discord-userdoccers/discord-userdoccers/9.2-gateway-intents-and-capabilities)
- [discord-api-docs Issue #2704 – Undocumented capabilities and client_state](https://github.com/discord/discord-api-docs/issues/2704)
- [Lazy Guilds (op 14) – arandomnewaccount unofficial docs](https://arandomnewaccount.gitlab.io/discord-unofficial-docs/lazy_guilds.html)
- [Tracking and /science – luna unofficial docs](https://luna.gitlab.io/discord-unofficial-docs/docs/science/)
- [adityaxdiwakar/discord-build-scraper – updater.py](https://github.com/adityaxdiwakar/discord-build-scraper/blob/master/updater.py)
- [Pixens/Discord-Build-Number](https://github.com/Pixens/Discord-Build-Number)
- [discord-userdoccers/discord-protos](https://github.com/discord-userdoccers/discord-protos)
- [Fastly – State of TLS fingerprinting (JA3/JA4)](https://www.fastly.com/blog/the-state-of-tls-fingerprinting-whats-working-what-isnt-and-whats-next)
- [Scrapfly – JA3/JA4 explainer](https://scrapfly.io/web-scraping-tools/ja3-fingerprint)
- [fingerprint.com – What is TLS fingerprinting](https://fingerprint.com/blog/what-is-tls-fingerprinting-transport-layer-security/)
- [curl-impersonate](https://github.com/lwthiker/curl-impersonate)
- [curl_cffi (Python bindings)](https://github.com/lexiforest/curl_cffi)
- [utls – refraction-networking](https://github.com/refraction-networking/utls)
- [rquest / reqwest-impersonate (Rust)](https://github.com/4JX/reqwest-impersonate)
- [discord.py-self – hCaptcha discussion #838](https://github.com/dolfies/discord.py-self/discussions/838)
- [HN thread – "still no x-super-properties use Unsafe"](https://news.ycombinator.com/item?id=39763438)
- [WebCord – Discord WebView client](https://github.com/iamtraction/WebCord)
- [Electron blog – WebView2 and Electron](https://www.electronjs.org/blog/webview2)

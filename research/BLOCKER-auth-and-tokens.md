# BLOCKER: Authentication, Token Handling, Captcha, and Account-Recovery Risk

## TL;DR

- Discord user tokens are long-lived bearer credentials with no documented expiry; only a password reset invalidates them globally. Reusing a token extracted from the official web client sidesteps `/auth/login`, hCaptcha, and email/IP verification entirely, and is what abaddon does in practice.
- An in-app username/password flow is technically possible (`POST /api/v9/auth/login`) but will almost certainly trigger hCaptcha on the first attempt from a "new device" (any unfamiliar IP/User-Agent/X-Super-Properties combination) and require email verification via `POST /auth/authorize-ip`. Solving captcha programmatically risks an automation flag.
- Self-botting (any automation of a user account outside the OAuth2/bot API) is a Discord ToS violation; the safe posture is **read/UI parity with the web client, no automation, no spam**, and quiet traffic shaping (proper headers, no unused endpoints).
- On Windows, store the token with **DPAPI `CryptProtectData`** scoped to the current user (CRYPTPROTECT_UI_FORBIDDEN) or via Credential Manager (`CredWriteW`). Do not copy Discord's own behavior — Discord stores the token in unencrypted leveldb under `%APPDATA%\discord\Local Storage\leveldb`, which is famously plundered by token-grabber malware.
- 2FA must be handled at first login if you ever do password login: `/auth/login` returns `mfa: true` plus a `ticket`, and the client must `POST /auth/mfa/totp` (or `/sms`, `/backup`, `/webauthn`). Token refresh is not a thing — user tokens do not rotate.
- Worst-case account recovery: Discord disables the account on suspected automation; the only path back is `dis.gd/contact` appeal with multi-day wait, and after 14–30 days messages are anonymized and the email/phone are blacklisted. Treat the account as potentially destroyable.

## 1. Login flow (what the web client does)

Unauthenticated, the client first hits `POST /api/v9/auth/fingerprint` to obtain an opaque fingerprint (snowflake + hash) which is then sent in the `X-Fingerprint` header on every subsequent unauth request and inside the `fingerprint` JSON field on `/auth/login`. Discord uses it to keep A/B experiment assignment stable across the login funnel.

`POST /api/v9/auth/login` accepts: `login` (email or E.164 phone), `password` (8–72 chars), `undelete` (bool, restore deleted accounts), `login_source` (gift, guild_template, invite, etc.), `gift_code_sku_id`, and `captcha_key`/`captcha_rqtoken` on retry.

The web client also sets `X-Super-Properties` (base64 JSON with `os`, `browser`, `device`, `browser_user_agent`, `browser_version`, `os_version`, `referrer`, `referring_domain`, `referrer_current`, `referring_domain_current`, `release_channel: "stable"`, `client_build_number`, `client_event_source: null`) on essentially every request. Its absence is one of the cheapest bot signals Discord has.

**Captcha challenge:** a `400 Bad Request` body with `captcha_key` (e.g. `["captcha-required"]`), `captcha_service` (`hcaptcha`, `recaptcha`, or `recaptcha_enterprise`), a dynamic `captcha_sitekey`, plus optional `captcha_session_id`, `captcha_rqdata`, and `captcha_rqtoken`. The retry sends the solved token as `X-Captcha-Key`, plus `X-Captcha-Session-Id` and `X-Captcha-Rqtoken` if present. hCaptcha Enterprise binds the solve to the session via `rqdata`, so naive solver services usually fail.

**MFA branch:** the login response is `{ mfa: true, ticket, login_instance_id, totp, sms, backup, webauthn }` (booleans for which factors exist). The client POSTs `/api/v9/auth/mfa/{totp|sms|backup|webauthn}` with `{ ticket, code, login_instance_id }` to get the real user token.

**New-device branch:** without MFA, an unfamiliar IP/UA triggers a Login Verification Email; the link calls `/api/v9/auth/authorize-ip` with the verification token, then login must be retried.

**Suspended accounts** receive `suspended_user_token` instead of `token`; usable only for appeal/standing endpoints.

## 2. Tokens — kinds and lifetime

Three token shapes exist in practice:

1. **User token** — returned by `/auth/login` or MFA verification. Bearer token sent in `Authorization` header (no `Bearer` prefix for user tokens; the raw string). **No documented expiry.** A new login does not invalidate prior tokens — old tokens keep working in parallel (see yal.cc/discord-2021 and Discord support forum posts).
2. **MFA `ticket`** — short-lived partial token returned alongside `mfa: true`. Only usable against `/auth/mfa/*`.
3. **OAuth2 access/refresh tokens** — irrelevant here; those are for third-party apps using the developer-portal OAuth2 flow, not user-account auth. (Their `expires_in` is hardcoded to 604800s.)

User tokens are invalidated only by **password reset**. There is no first-party "log out everywhere" endpoint; `POST /auth/logout` only kills the calling session. This means a leaked token effectively grants persistent account access until the user changes their password, which is why token theft is the dominant Discord attack vector.

## 3. Token extraction vs in-app login

**Token extraction (paste-token):** user opens DevTools in the web client and pastes `window.localStorage.token` (or fetches it via a webpack-shim since direct localStorage access was obfuscated) into our app. Pros: zero captcha exposure, no MFA flow, no new-device email, no fingerprint matching — the token was minted by an already-trusted browser session. Cons: friction, clipboard leak risk, and the session is bound to the browser's IP/UA so wildly different networks may still trip challenges on sensitive endpoints.

**In-app password login:** implement `/auth/login` + captcha + MFA + IP authorization end-to-end. Pros: nicer UX. Cons: captcha is the killer — hCaptcha Enterprise's `rqdata` binding makes automated solving unreliable, and "automating the login and MFA flow on a 2FA enabled account" is explicitly called out by Discord engineers as a termination risk (Discord WebAuthn blog).

**abaddon's choice:** paste-token only. `ActionSetToken()` opens a `TokenDialog`; `ActionLoginQR()` (only when `WITH_QRLOGIN` is defined) connects to `wss://remote-auth-gateway.discord.gg/?v=2`. Abaddon does **not** call `POST /auth/login`. We should do the same — optionally add QR remote-auth, since it is the official mobile-assisted flow and is much less captcha-prone.

## 4. Storing the token on Windows

Worst to best:

1. **Plaintext in `%APPDATA%`** — what Discord itself does (leveldb in `%APPDATA%\discord\Local Storage\leveldb`, `.ldb`/`.log` files). Trivially exfiltrated by user-context malware. Don't.
2. **Plaintext `.ini`** — abaddon's Windows fallback (`%APPDATA%\Abaddon\abaddon.ini`) because its `WITH_KEYCHAIN` is libsecret-only. Same exposure.
3. **Windows Credential Manager** via `CredWriteW`/`CredReadW` with `CRED_TYPE_GENERIC`. DPAPI-encrypted under the hood, surfaced in the Credential Manager UI for user revoke.
4. **DPAPI directly** — `CryptProtectData`/`CryptUnprotectData` from `dpapi.h`. Session key derived from the user's logon credentials; blob decryptable only by the same user on the same machine. What browsers and password managers use.

**Recommendation:** DPAPI with `CRYPTPROTECT_UI_FORBIDDEN`, `CRYPTPROTECT_LOCAL_MACHINE` off (per-user, not per-machine), plus 8-byte app entropy so a stolen blob can't be decrypted by another app running as the same user. Store at `%LOCALAPPDATA%\<app>\token.dpapi`. Provide a "Forget token" menu item that deletes the blob.

## 5. Device-changed challenges

Discord's "same device" heuristic is undocumented but observably keyed on source IP, `User-Agent`, `X-Super-Properties` (especially `client_build_number`, `os`, `browser_version`), and `X-Fingerprint`. A novel tuple triggers either a Login Verification Email (no-MFA case) or hCaptcha (high-suspicion case). `/auth/authorize-ip` whitelists the tuple for a window.

For our paste-token case, the token already carries a trusted-device association from the browser session that minted it. We should match what the web client sends: a real Chrome UA, a stable `X-Super-Properties`, a persistent `Referer: https://discord.com/channels/@me`-style header (abaddon does this), and **never** randomize the fingerprint per launch — that itself is a bot signal.

## 6. 2FA

If we follow the paste-token approach, **2FA never enters the client** — the token was minted post-MFA. If we ever add in-app password login we must implement the `mfa: true` branch (`ticket`, factor selection, `POST /auth/mfa/totp` etc.). Token refresh does not exist for user tokens, so there's no "refresh-time 2FA". The only place 2FA re-appears mid-session is on sensitive endpoints (deleting servers, changing email), which return a separate MFA challenge with `X-Discord-MFA-Authorization` — out of scope for a voice client.

## 7. Account recovery

Worst case: Discord disables the account on automation suspicion. Recovery is `https://dis.gd/contact` form, multi-day to multi-week wait, no guarantees. **Irrecoverable failure modes:**

- After 14–30 days post-disable, Discord anonymizes messages and **blacklists the email and phone number** — they cannot be reused on Discord.
- Support ticket attached to a compromised account can be closed by the attacker before the user replies (per yal.cc).
- Self-bot detection is a stated termination policy ("Automated User Accounts (Self-Bots)" support article). Even private-server "testing" is grounds for ban.

Mitigation: never automate, never send unprompted messages, throttle outgoing actions to plausibly-human rates, do not hit endpoints the web client doesn't hit (no `/users/@me/relationships/scan`-style misuse), keep the build identifying as the web client (matching IDENTIFY payload, super_properties, UA). Recommend the user keep a second verified backup email and an MFA app set up before first launch.

## 8. abaddon study

- **No `/auth/login` call.** No email/password login UI; `src/abaddon.cpp` reads `GetSettings().DiscordToken`; `ActionSetToken()` opens a `TokenDialog`.
- **QR remote-auth (optional)** via `RemoteAuthDialog` behind `#ifdef WITH_QRLOGIN`, hitting `wss://remote-auth-gateway.discord.gg/?v=2`.
- **Token storage:** `WITH_KEYCHAIN` uses libsecret on Linux; else plaintext in `abaddon.ini`. No Windows keychain path in tree — Windows falls through to plaintext.
- **Headers are thin:** `Authorization`, `User-Agent` (custom or "Abaddon"), `Origin: https://discord.com`, a persistent `Referer`. **No `X-Super-Properties`, no `X-Fingerprint`** — abaddon is identifiable as non-web traffic the moment Discord cares to look. README acknowledges it also skips `/science` telemetry.
- **IDENTIFY payload:** README claims parity with the web client's gateway IDENTIFY; built manually in code.

Implication: we should be *more* careful than abaddon about headers (set `X-Super-Properties` to match a real Chrome build) but copy its overall posture — paste-token only, web-client UA, no automation.

## Citations

- Discord Userdoccers — Authentication: https://docs.discord.food/authentication
- Discord Userdoccers — CAPTCHA Handling: https://docs.discord.food/topics/captcha-handling
- Discord Userdoccers — Remote Authentication (Desktop): https://docs.discord.food/remote-authentication/desktop
- X-Super-Properties field list: https://github.com/KhafraDev/discord-verify/wiki/X-Super-Properties
- abaddon repository (README, settings.cpp, abaddon.cpp, discord/*): https://github.com/uowuo/abaddon
- abaddon QR auth gateway connectivity issue (URL evidence): https://github.com/uowuo/abaddon/issues/289
- Discord token never expires / only password reset invalidates: https://support.discord.com/hc/en-us/community/posts/360060394731-What-is-token-has-expired-means and https://support.discord.com/hc/en-us/community/posts/360049545034-Change-account-token
- Yal "Unbelievable horrors of Discord account security" (2021): https://yal.cc/discord-2021/
- Login Verification Email behavior: https://support.discord.com/hc/en-us/articles/6181726888215-How-to-Verify-Your-Discord-Account
- Self-bot policy / termination risk: https://support.discord.com/hc/en-us/articles/115002192352-Automated-User-Accounts-Self-Bots
- Discord blog "How Discord Modernized MFA with WebAuthn" (MFA ticket architecture, warning against automating `/api/login` and `/api/auth/mfa/totp`): https://discord.com/blog/how-discord-modernized-mfa-with-webauthn
- Discord account appeals: https://support.discord.com/hc/en-us/community/posts/16191655766679-Discord-Account-Appeals-What-you-need-to-know
- Microsoft DPAPI `CryptProtectData`: https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata
- Microsoft DPAPI `CryptUnprotectData`: https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptunprotectdata
- DPAPI overview / Credentials path: https://tierzerosecurity.co.nz/2024/01/22/data-protection-windows-api.html
- node-keytar (Windows Credential Vault backend reference): https://github.com/atom/node-keytar
- Discord token storage in leveldb / extraction surface: https://www.upsightsecurity.com/post/slurping-discord-tokens

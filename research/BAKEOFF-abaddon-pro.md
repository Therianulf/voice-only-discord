# BAKEOFF: Fork abaddon (Path A) — Pro

## TL;DR

- Discord voice is **not a documented protocol** — abaddon already implements every undocumented piece (RTP, IP discovery, AEAD, DAVE/MLS E2EE, voice opcodes 0–13/21–31, READY/READY_SUPPLEMENTAL split, super-properties).
- A weekend of *deletion* takes 80+ files down to ~25; a week of UI swap (GTK → Dear ImGui) reaches "click channel, hear audio."
- From-scratch C++ is a 2–4 month project; from-scratch Python is blocked on **DAVE** (no Python libdave binding) after the 2026-03-01 enforcement.
- abaddon has run on real users since 2020 with no mass-ban event — a 5-year fingerprint validation no greenfield can match in week one.
- The honest concession (GTK3/MSYS2 is unloved) is the easiest fix: replace the UI shell, keep `src/discord/`.

---

## 1. What we get for free

abaddon: GPL-3.0, ~96% C++, 1,373 commits, v0.2.4 (Apr 2026), 5-year history. `src/discord/` is the prize.

**Voice — `voiceclient.cpp` (~910 lines).** 5-state machine, `Discovery()` (74-byte UDP IP discovery), `SelectProtocol()`, `SendEncrypted()` (12-byte RTP `0x80 0x78`, XChaCha20-Poly1305-IETF nonce), `OnUDPData()` decryption + Opus extraction (handles `0xF8 0xFF 0xFE` silence), `FeedMeOpus()`. Discord does *not* document RTP layout, AEAD nonce derivation, or 50 Hz cadence — abaddon found it all by pcap-staring.

**DAVE / MLS — `dave.cpp` (~320 lines).** Discord drops non-DAVE voice with **close code 4017 as of 2026-03-01**. `DaveSession` wraps libdave: `Init/Reinit`, encryptor/decryptor, `OnProposals/OnWelcome/OnAnnounceCommitTransition`, roster, `GetPairwiseFingerprint`. DESIGN-minimal-native called DAVE "the single biggest knock against the minimal-native pitch." abaddon already bit it.

**Gateway — `discord.cpp` (~3,427 lines).** `SendIdentify()`, `SetHeaders()`, `SetSuperPropertiesFromIdentity()` (~2787–2854), heartbeat zombie detection, RESUME-before-IDENTIFY, READY/READY_SUPPLEMENTAL split. `IdentifyProperties` in `objects.hpp` is the 15-field shape Discord expects.

**HTTP — `httpclient.cpp`.** libcurl wrapper (`SetPersistentHeader`/`SetAuth`/`SetUserAgent`). Drop-in `curl-impersonate` — one `.lib` swap = Chrome JA3/JA4.

**WebSocket — `websocket.cpp`.** IXWebSocket, `Origin`/UA injected.

**Audio — `audio/manager.cpp`.** miniaudio (WASAPI) → libopus → libsodium → UDP, with rnnoise VAD. The exact pipeline our research recommends.

**Otherwise-reinvent list:** RTP PT=120, AEAD `_rtpsize` nonce, IP-discovery, UDP keepalive, jitter buffer, DAVE MLS, 15-field super-properties, voice OP-5 bitmask, READY_SUPPLEMENTAL buffer, resume-vs-reconnect, voice WS v8 `seq_ack`. Each multi-day. abaddon solved them.

## 2. Stripping plan — what we DELETE

*Subtractive* engineering: we don't write protocol code, we remove UI and features that have no analog in our spec.

### What stays / what goes

| Decision | abaddon files | Why |
|---|---|---|
| **KEEP** voice protocol | `voiceclient.*`, `voicestate.*`, `dave.*` | The whole point |
| **KEEP** audio | `src/audio/manager.cpp`, `devices.cpp`, `ma_impl.cpp` | miniaudio + libopus |
| **KEEP-TRIM** gateway | `discord.*`, `websocket.*`, `objects.*` | Strip `SendLazyLoad` / OP-14 / message dispatch |
| **KEEP** HTTP | `httpclient.*` | Swap libcurl → curl-impersonate |
| **KEEP** model | `guild.*`, `channel.*`, `snowflake.*`, `permissions.*` (lite) | Need server/channel tree |
| **KEEP** auth | TokenDialog + token settings | Paste-token, per BLOCKER-auth §3 |
| **DELETE** messages/members/friends | `message.*`, `member.*`, `relationship.*`, `friendslist.*` | Out of spec; OP-14 forbidden (BLOCKER-gateway §1.6) |
| **DELETE** rich content | `sticker.*`, `emoji.*`, `lazyimage.*` | No rendering |
| **DELETE** admin/social | `webhook.*`, `auditlog.*`, `ban.*`, `role.*`, `invite.*`, `interactions.*`, `store.*`, `activity.*`, `stage.*` | Out of scope |
| **DELETE** chat UI | `chatwindow/input/list/message`, `completer`, `memberlist`, `cellrenderermemberlist` | Bulk of `src/components/` |
| **DELETE** misc UI | `filecache.cpp` (avatar cache), most of `src/dialogs/` (keep TokenDialog) | No images, no settings UI v1 |
| **DELETE-OR-REPLACE** GTK shell | gtkmm3, libhandy, MSYS2 closure | See §3 |

**LoC.** abaddon ~50–60k LoC total. Kept: discord.cpp 3.4k + voiceclient.cpp 910 + dave.cpp 320 + objects/permissions/guild/channel/httpclient/websocket ~4–5k + audio ~2k ≈ **10–12k LoC**. Deleted: chat/embed/member/dialog graveyard ≈ 30–40k LoC. Post-strip footprint is well below any greenfield C++ estimate.

## 3. The GTK question

abaddon uses GTK3/gtkmm + MSYS2 on Windows; LANG-cpp documents the burnout. But GTK touches almost none of `src/discord/` — the seam is one gateway-thread→dispatcher signal. Replace the shell with **Dear ImGui + D3D11 + Win32** (LANG-cpp §2 — ~100 KB, zero runtime deps); signal/slot becomes function pointers, mechanical.

Crucially, GTK3 idle CPU is fine *in practice*. xda-developers measured abaddon at ~45 MB RAM; `WaitMessage()` parks the GTK thread, GTK doesn't *spin*. **Recommendation:** strip features in v1 (keep GTK3), UI swap in v2. Feature deletion buys CPU; UI swap buys polish.

## 4. Hours to working prototype

| Milestone | scratch C++ | scratch Python | **fork abaddon** |
|---|---|---|---|
| Gateway IDENTIFY + READY | 1–2 wk | 1 day | **0 days** |
| Voice WS + UDP handshake | 2–3 wk | 2–3 days | **0 days** |
| RTP / AEAD / Opus | 1–2 wk | 1 day (PyNaCl) | **0 days** |
| **DAVE / MLS** | **2–4 wk** | **1–3 wk** (no libdave Py binding) | **0 days** |
| Super-properties + headers | 2–3 days | 1 day | constant edits |
| Strip chat/members/embeds | n/a | n/a | **1–2 days** |
| UI swap (GTK → ImGui) | 1 wk | n/a (PySide6) | 1 wk (v2, optional) |
| **Click-voice → hear audio** | **2–4 months** | **2–4 weeks** | **~weekend + 1 week** |

Python looks competitive — until DAVE. `discord.py-self` ships no DAVE; libdave is C++ with no Python binding. After 2026-03-01: close code 4017 on every voice join. abaddon has DAVE today.

## 5. Risk-adjusted CPU

Greenfield's pitch is "tighter loop." True in principle, false in practice: fresh code carries unknown CPU bugs — busy-poll where `WaitMessage()` belongs, 1 ms reconnect spins, per-packet jitter buffer allocs, missed `RESUMED` acks triggering re-IDENTIFY storms.

abaddon's idle is *measured*, not targeted. 5 years of users haven't reported runaway CPU. BLOCKER-gateway estimates idle <0.1%, voice 3–5% — abaddon hits both today. With 64 GB RAM, the ~45 MB resident is invisible. The metric that matters — CPU — is the one abaddon already won.

## 6. Anti-flagging story

BLOCKER-tos is unequivocal: Discord bans *traffic shapes*, not *binaries*. abaddon has been the most visible 3rd-party client for 5 years; the only documented disable cases (discussion #84, issue #349) are users who *also* spammed DMs or files. The fingerprint surface — UA, IDENTIFY, `X-Super-Properties`, headers, REST discipline — is already solved in `discord.cpp` ~2787–2854. Known gaps (stale Chrome 67 UA, hardcoded build number, no `/science` stub) are constant edits, not redesigns.

A from-scratch client *will* get this wrong first time: forget `Sec-Fetch-Site`, send `intents` with a user token, hammer reconnect, leak identity in an HTTP/2 SETTINGS frame. abaddon was debugged by 2.2k stars of users. We inherit that debugging free.

## 7. Why abaddon beats from-scratch C++

LANG-cpp concedes it in its own TL;DR: "someone already wrote ninety percent of this app in C++." Read carefully, the from-scratch C++ pitch reduces to "use the libraries abaddon uses (libopus, libsodium, IXWebSocket, miniaudio, libcurl, nlohmann/json) and reimplement the glue." That glue *is* `voiceclient.cpp` + `discord.cpp` + `dave.cpp` + audio manager — ~12k LoC we get free. From-scratch C++ becomes abaddon-minus-GTK after a month. Skip the month.

## 8. Why abaddon beats Python

`discord.py-self` v2.1.0 is impressive; `curl_cffi` solves TLS. But: **(a)** No DAVE/MLS shipped, no libdave Python binding — close code 4017 today. **(b)** Voice receive on selfbots is "grayer" (LANG-python's word); abaddon's `OnUDPData()` decrypts inbound today. **(c)** ~60 MB RAM + 25–35 MB Nuitka binary vs stripped-abaddon ~30 MB + ~15 MB exe. RAM is free here, but cold-start and AV false-positives aren't.

## 9. Honest concessions

- **Maintainer burnout documented.** Once forked, we own the tree; no upstream blocker.
- **GPL-3.0 sticky.** Fine for personal use; public release means publishing source. Not a real blocker.
- **GTK3/MSYS2 is unloved.** Addressed §3 — *developer* friction, not *user* friction. The built `.msi` double-clicks and runs.
- **Inherited architectural quirks.** `std::function`-capture dangling in `voiceclient.cpp`, the `// idk if this actually works` comment in `websocket.cpp` — real. But we hit them with a working baseline as oracle, not in greenfield code where bugs hide among other new bugs.
- **C++ ergonomics < Python.** Granted. Offset: this is mostly *deletion* — the easy part of any codebase.

Every concession is smaller than the alternative cost: months of greenfield protocol, or weeks blocked on DAVE in Python.

---

## Citations

- [abaddon repo](https://github.com/uowuo/abaddon) — GPL-3.0, 96% C++, 1,373 commits, v0.2.4 (Apr 2026), 2.2k stars.
- [`voiceclient.cpp`](https://github.com/uowuo/abaddon/blob/master/src/discord/voiceclient.cpp) — ~910 lines, 5-state voice machine, `Discovery`/`SelectProtocol`/`SendEncrypted`/`OnUDPData`/`EnsureDaveSession`.
- [`dave.cpp`](https://github.com/uowuo/abaddon/blob/master/src/discord/dave.cpp) — ~320 lines, `DaveSession` wrapping libdave.
- [`discord.cpp`](https://github.com/uowuo/abaddon/blob/master/src/discord/discord.cpp) — ~3,427 lines, `SendIdentify`/`SetHeaders`/`SetSuperPropertiesFromIdentity` ~2787–2854.
- [`src/discord/`](https://github.com/uowuo/abaddon/tree/master/src/discord) and [`src/components/`](https://github.com/uowuo/abaddon/tree/master/src/components) listings — confirmed strip targets.
- [discord/libdave](https://github.com/discord/libdave); [Meet DAVE blog](https://discord.com/blog/meet-dave-e2ee-for-audio-video); [docs.discord.food voice-connections](https://docs.discord.food/topics/voice-connections) — close code 4017.
- [xda-developers](https://www.xda-developers.com/lightweight-alternatives-electron-apps-dont-eat-up-ram/) — abaddon ~45 MB RAM.
- [HN zorkian quote](https://news.ycombinator.com/item?id=28435490); [abaddon discussion #84](https://github.com/uowuo/abaddon/discussions/84).
- Prior research: `BLOCKER-{tos,fingerprinting,gateway,auth}-*.md`, `LANG-{cpp,python}.md`, `DESIGN-minimal-native.md`.
</content>
</invoke>
# BAKEOFF — The Case Against Forking abaddon

*Position: forking abaddon is the worst of the three options. Build a fresh client in C++ or Python instead.*

## TL;DR

abaddon is a **text-chat client first** with voice bolted on; the message/member subsystem is fused into the gateway dispatcher, the `Abaddon::Get()` singleton, the channel-list tree, and ~45 sigc++ signals — with **no CMake flag to compile it out**. The voice code we actually want is ~5 files; the rest is ~80 files of GTK-bound chat UI we'd surgically unwire. On top of that, a fork inherits abaddon's **GTK3/MSYS2** chain (no MSVC, no Visual Studio debugger), **stale fingerprint defaults** (Chrome 67, build 363557, no `client_launch_id`, no `/science`), **GPLv3 copyleft**, and a **bus factor of one** (`ouwou` owns 1,311 of ~1,380 commits, ~95%). A clean C++ build or a `discord.py-self` Python build both ship sooner with less debt.

---

## 1. abaddon is a text-chat client — "subtractive engineering" is mostly a fiction

Counts from `src/discord/discord.hpp`:

| Subsystem | Methods | Signals |
|---|---|---|
| Messages | ~13 | 6 |
| Channels | ~13 | 4 |
| Members | ~10 | 2 + `guild_member_list_update` |
| Guilds | ~12 | 7 |
| **Voice** | **~12** | **~11** |
| Permissions | ~10 | — |
| Reactions / threads / invites / relationships / DMs / stage / emoji | ~20 | 14 |

We want ≤15% of `DiscordClient`'s public surface and 11 of ~45 signals. Every signal is wired into UI, the unread store, notifications, and the GTK main loop — cutting one wire drags dependencies through `src/components/`, `src/dialogs/`, `src/windows/`.

`HandleGatewayReady` / `ProcessNewGuild` (`discord.cpp` ~2462–2580) **auto-merge `READY_SUPPLEMENTAL.MergedMembers` into `m_store`** and update guild-member maps on every `GUILD_MEMBER_UPDATE` / `PRESENCE_UPDATE`. The same dispatcher populates `m_unread`, `m_guild_to_users`, and `m_voice_states` in parallel. To "turn off messages" you walk every `case t == "MESSAGE_*"`, every `m_store.Set*`, every signal emit, and every consumer.

`ChannelListTree` — the widget we'd reuse — exposes `OnMessageCreate(...)` and `RedrawUnreadIndicatorsForChannel(...)` as members, alongside thread/forum/text/voice render-types in one switch. Voice rows ride the same code path as text-chat unread logic.

**There is no `WITH_CHAT` flag.** `CMakeLists.txt` gates only `ENABLE_VOICE`, `ENABLE_RNNOISE`, `ENABLE_QRCODE_LOGIN`, `USE_KEYCHAIN`, `USE_LIBHANDY`, `ENABLE_NOTIFICATION_SOUNDS`. Sources are pulled in by recursive glob. The chat path is mandatory. The fork pitch is a **surgical refactor across ~80 files**, not "delete and build."

---

## 2. GTK3 on MSYS2 on Windows is a maintenance disaster

- **MinGW-w64 in MSYS2**, twelve `pacman` packages including `gtkmm3`, `libhandy`, `opus`, `libsodium`. **No MSVC build option** — no Visual Studio debugger, no clang-cl analysis, awkward PDBs, `signtool` friction. LANG-cpp.md: "abaddon ships MinGW/MSYS2 builds because of GTK — exactly the burnout source."
- **Open Windows issues:** [#320](https://github.com/uowuo/abaddon/issues/320) hideconsole broken (open since Jul 2024); [#357](https://github.com/uowuo/abaddon/issues/357) 32-bit build infeasible because MSYS2 GTK3 isn't trivially i686-buildable.
- **DPI**: GTK3 on Windows is integer-scale-only — mixed 4K + 1080p setups misrender. Dear ImGui + D3D11 handles fractional scaling per-monitor.
- **Look**: default GTK theme is visibly non-native; `libhandy` adds Adwaita.
- **Closure**: ~60 MB of GTK/Glib/Pango/Cairo DLLs at runtime; MSYS2 updates break builds without warning.

---

## 3. We inherit abaddon's fingerprint debt

From `BLOCKER-fingerprinting-and-detection.md`, verbatim:

- "abaddon **does not auto-scrape** — `m_build_number` defaults to `363557`."
- "Hardcodes `OS=Windows, Browser=Chrome, BrowserVersion=67.0.3396.87`, `capabilities=4605`. **Chrome 67 is from May 2018; this is dramatically out of date** — current stable is ~Chrome 131+."
- "default `"Abaddon"` if unconfigured — **that string in a UA is itself a tell**"
- "**No TLS impersonation** — out-of-the-box libcurl JA3."
- "abaddon **does not** send `/science` telemetry."
- websocket.cpp contains the comment `// idk if this actually works`.

Currently-open [issue #417 (April 2026)](https://github.com/uowuo/abaddon/issues/417) — "X-Super-Properties missing important properties: `launch_signature`, `client_launch_id` (UUIDv4), `client_heartbeat_session_id` (UUIDv4)" — notes Discord "uses them to flag automated requests and may flag accounts using this client." **No maintainer response.** This is the spam-classifier-relevant deficit, still unfixed in May 2026.

A from-scratch client puts current Chrome UA, an auto-scraped build-number, `client_launch_id`, a `/science` stub, and `X-Discord-Timezone` in the first 200 LOC. A fork starts in the hole.

---

## 4. One-name bus factor + voice already broke once

GitHub contributors API: `ouwou` 1,311 commits; `TheMorc` 14; `mesalilac` 6. **~95% one person.** Commit cadence is sporadic — multi-month gaps; latest commit 2026-03-31. GTK4 port has been requested since [#60 (2022)](https://github.com/uowuo/abaddon/issues/60), never delivered. LANG-cpp.md cites the maintainer's "significant headaches" and burnout from GTK3+MSYS2.

**Concrete cost:** On 2026-03-01 Discord enforced DAVE/MLS (close code 4017). [Issue #407](https://github.com/uowuo/abaddon/issues/407): *"voice channel connection isnt working since monday just noticed that discord changed something on march 1st."* The gap between Discord breaking voice and abaddon fixing it lives on one person's calendar — and **the moment we strip 60% of the code we're a fork, not a user**, forfeiting upstream fixes. Forks of one-maintainer projects rot fast.

---

## 5. GPL-3.0 viral copyleft

abaddon is **GPLv3**. A fork licenses the whole work under GPLv3, carries dated modification notices, provides complete source on demand to any binary recipient, and **cannot relicense more permissively**. Consequences: sharing a signed build obligates source; no future linking against proprietary noise-suppression or Steam Audio; real bookkeeping even for hobby use. A from-scratch project picks its own license (MIT/Apache-2.0) while respecting BSD libopus and ISC libsodium.

---

## 6. The voice code isn't as portable as it looks

`src/discord/voiceclient.{hpp,cpp}` is **tangled with gtkmm**: `Glib::Dispatcher` (`m_dispatcher`, `m_binary_dispatcher`) for cross-thread events; sigc++ signals everywhere (`m_ws.signal_*().connect(sigc::mem_fun(*this, ...))`); **`Abaddon::Get()` referenced 10+ times** from inside voice for audio manager, opus feeding, volume, RTP timestamps; three internal threads (heartbeat, keepalive, `UDPSocket::ReadThread`) whose lifetimes depend on the dispatcher; `DaveSession` wired through signal callbacks, not a clean library boundary.

LANG-cpp says we'd "lift or study" — **study** is the operative word. Reading abaddon as a reference is high-value; forking and keeping voiceclient bound to a new event loop is weeks of fighting the architecture.

---

## 7. libdave doesn't favor the fork

[`discord/libdave`](https://github.com/discord/libdave) is a standalone C++/C library with a clean C ABI. Any path links it the same way. abaddon offers **no DAVE advantage** — the minimal-native design doc already plans to "statically link `discord/libdave`" in a fresh `voice-helper.exe`.

---

## 8. The hidden cost: forking detaches from upstream

The strongest pro-fork argument is "abaddon is proven code." **That benefit evaporates the moment we strip 60% of it.** Every upstream patch becomes a cherry-pick onto a divergent tree where most files are gone or renamed. Within months, merging a `ouwou` commit costs the same as **reading it as documentation and implementing the change cleanly**. "Proven, tested" is real for the first compile and a liability after.

A from-scratch project treats abaddon as **read-only reference docs** (great for that — its userdoccers-compatible IDENTIFY/voice handshake is correct). Zero-maintenance benefit forever. The fork is a positive-maintenance liability forever.

---

## 9. From-scratch C++ beats fork

Clean **CMake + vcpkg + MSVC + Dear ImGui (D3D11) + IXWebSocket + libopus + libsodium + curl-impersonate + libdave** delivers everything in ~5–8 KLOC against userdoccers and abaddon-as-reference. We get MSVC debugging, fractional DPI, native Win32 look, ~6 MB static .exe, fresh fingerprint defaults (current Chrome UA, auto-scraped build_number, `client_launch_id`, `/science` stub, curl-impersonate JA3/JA4), a license of our choice, and **no inherited 80-file blast radius**.

## 9b. From-scratch Python beats fork

[`discord.py-self` 2.1.0 (Jan 2026)](https://pypi.org/project/discord.py-self/) ships the gateway, voice send, super-properties, AEAD modes, and capabilities **out of the box**, actively maintained on Python 3.10–3.14. Pair with `curl_cffi` (perfect JA3/JA4 Chrome, WebSocket included) and PySide6 + `QSystemTrayIcon`. ~1,500 LOC, weekend build. Voice CPU is libopus/libsodium native — same as C++. Fingerprint defaults are *current Chrome*, not Chrome 67 from 2018. Pay 30 MB binary / 60 MB idle RAM (irrelevant on a 64 GB laptop), save a month.

---

## 10. The honest concession

**What abaddon legitimately gives us:** a debugged, end-to-end-tested Discord voice handshake (gateway OP 4 → VOICE_STATE/VOICE_SERVER → voice WS Identify/Ready → UDP IP discovery → Select Protocol → Session Description → RTP at 50 Hz), including DAVE MLS, that has survived thousands of users against production servers. Userdoccers is good; working code is better.

**Why it's still not enough.** We capture that value by **reading** voiceclient + dave + audio/manager (~1,000 LOC), then writing our own state machine in 1–2 weeks. Same correctness, no Glib::Dispatcher, no `Abaddon::Get()`, no GTK threading model, no GPLv3 contagion, no inherited fingerprint debt, no bus-factor-of-one risk. The "proven" benefit lives in *understanding*, not *inheriting*.

---

## What abaddon assumes that we don't want

| abaddon assumes | We want | Cost to fork |
|---|---|---|
| Text chat is the primary UI | Servers + voice channels only | Strip ~85% of `DiscordClient`, 4 of 6 `src/components/` dirs |
| GTK3 / gtkmm / Glib::Dispatcher main loop | Native Win32 + D3D11 (or Qt/PySide) | Rewrite event dispatch everywhere voice touches |
| MSYS2/MinGW build chain | MSVC + vcpkg | Re-port build; lose Visual Studio debugger |
| Member lists + presence + unread in channel tree | None of those | Remove `OnMessageCreate`, unread store, presence map from `ChannelListTree` |
| Chrome 67 / build 363557 / `"Abaddon"` UA / no `/science` / no `client_launch_id` | Current Chrome + auto-scrape + telemetry stub | Replace fingerprint code in `discord.cpp`, re-test |
| GPLv3 | License of our choice | Cannot relicense; must publish all source |
| Single maintainer sets the upstream cadence | We control the cadence | Forfeited the moment we strip; merges from upstream rot |
| libcurl default JA3 | curl-impersonate Chrome JA3/JA4 | Trivial in new project; painful inside abaddon's `httpclient.cpp` |

---

## Citations

- abaddon repo (GPL-3.0, C++ 96.0%, v0.2.4 2026-04-06): https://github.com/uowuo/abaddon
- abaddon README: https://github.com/uowuo/abaddon/blob/master/README.md
- abaddon LICENSE (GPLv3): https://github.com/uowuo/abaddon/blob/master/LICENSE
- CMakeLists.txt (no chat-gating flag): https://github.com/uowuo/abaddon/blob/master/CMakeLists.txt
- `src/discord/discord.hpp` (method + signal counts): https://github.com/uowuo/abaddon/blob/master/src/discord/discord.hpp
- `src/discord/discord.cpp` ~lines 2462–2580 (READY / ProcessNewGuild / MergedMembers), 2787–2854 (SendIdentify with Chrome 67 / build 363557 / capabilities 4605): https://github.com/uowuo/abaddon/blob/master/src/discord/discord.cpp
- `src/discord/voiceclient.{hpp,cpp}` (Glib::Dispatcher, sigc++, `Abaddon::Get()` ×10+): https://github.com/uowuo/abaddon/blob/master/src/discord/voiceclient.cpp
- `src/components/channellist/channellisttree.hpp` (`OnMessageCreate`, `RedrawUnreadIndicatorsForChannel`): https://github.com/uowuo/abaddon/blob/master/src/components/channellist/channellisttree.hpp
- `src/abaddon.hpp` (singleton owns DiscordClient, AudioManager, MainWindow, Notifications): https://github.com/uowuo/abaddon/blob/master/src/abaddon.hpp
- Contributors API (ouwou 1,311 / TheMorc 14 / mesalilac 6): https://api.github.com/repos/uowuo/abaddon/contributors
- Issue #320 hideconsole broken on Windows (open, Jul 2024): https://github.com/uowuo/abaddon/issues/320
- Issue #357 32-bit Windows build (open, Apr 2025): https://github.com/uowuo/abaddon/issues/357
- Issue #340 "rewrite in rust pls" (closed Mar 2025): https://github.com/uowuo/abaddon/issues/340
- Issue #60 "GTK4 port?" (closed Mar 2022, never delivered): https://github.com/uowuo/abaddon/issues/60
- Issue #407 voice broken at DAVE mandate 2026-03-01: https://github.com/uowuo/abaddon/issues/407
- Issue #417 X-Super-Properties missing `launch_signature` / `client_launch_id` / `client_heartbeat_session_id` (open, Apr 2026, no maintainer reply): https://github.com/uowuo/abaddon/issues/417
- Discussion #84 (account disabled; "comes with the territory of using unofficial clients"): https://github.com/uowuo/abaddon/discussions/84
- DAVE mandate / close code 4017: https://docs.discord.food/topics/voice-connections
- Project-internal: LANG-cpp.md, LANG-python.md, BLOCKER-fingerprinting-and-detection.md, BLOCKER-gateway-and-voice.md, DESIGN-minimal-native.md

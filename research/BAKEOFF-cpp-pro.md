# BAKEOFF: New C++ Client From Scratch (path B)

*Advocate brief. Three paths: (A) fork abaddon, (B) new C++ from scratch, (C) new Python from scratch. Argue B.*

## TL;DR

- **CPU floor is the binding constraint.** C++ + ImGui + blocking I/O is the absolute bottom: no GC, no asyncio, no GTK pump, no redraw when hidden. Idle **<0.05% of one core**.
- **Forking abaddon inherits debt**: GTK3 + MSYS2 build chain, six-year-stale Chrome-67 super-properties, plaintext-token on Windows, OP-14 lazy-load we don't want, `// idk if this actually works` in `websocket.cpp`, GPLv3.
- **Lift abaddon's protocol *knowledge*, not its code** — read `voiceclient.cpp` in a second editor; rewrite clean with current Chrome UA, AES-256-GCM voice cipher, libdave linked from day one, DPAPI token storage.
- **2026 C++ Windows tooling is good**: vcpkg 2026.04.27 (2,595 ports on `x64-windows-static`), MSVC clang-cl + clangd-LSP, ImGui v1.92.6, libopus 1.6.1, libdave's formalized C++ API.
- **DAVE/MLS is mandatory** (close code 4017 since 2026-03-02). libdave is C++ — trivial link from C++, write-your-own ctypes shim from Python.

---

## 1. The killer pitch: lowest possible CPU floor

User is gaming. Every 0.5% of a core stolen is half a frame the game doesn't render. RAM is free; CPU is sacred. Idle floors:

| Path | Idle CPU (one core %) | Why |
|---|---|---|
| **(B) C++ scratch, ImGui hidden** | **~0.01–0.05%** | Thread parked on `MsgWaitForMultipleObjectsEx`; no redraw when hidden; one heartbeat/41 s. |
| (A) Fork abaddon | ~0.5–2% | GTK3 loop, dispatcher thread, miniaudio device retained (xda: ~45 MB / measurable CPU). |
| (C) Python scratch | ~0.1–0.5% | CPython asyncio per-wakeup overhead; PySide6 event pump runs while hidden. |

C++ wins via **zero managed-runtime presence**. The kernel parks the thread on `MsgWaitForMultipleObjectsEx(2, [ws_evt, voice_evt], INFINITE)` — zero scheduler ticks until a packet arrives. A heartbeat tick is ~40 bytes JSON + ~30 bytes WS write, sub-microsecond on Zen 4. One tick per 41 s ⇒ **~0.000002% of one core averaged**.

## 2. Modern C++ Windows tooling in 2026

For ~5–8 KLOC the rough edges stay bounded. `vcpkg install opus libsodium curl ixwebsocket nlohmann-json spdlog imgui[dx11-binding,win32-binding] --triplet x64-windows-static` is one command (vcpkg 2026.04.27 ships 2,595 ports on that triplet). Clean MSVC build sub-30 s; incremental sub-second. `clang-cl` emits `compile_commands.json` that clangd reads directly — zero LSP-gating drama. VS debugger is best-on-platform; time-travel debugging stable. nlohmann/json, spdlog, miniaudio, Dear ImGui are header-only. Template errors are still a chore; lifetime bugs in callback code are real (§11) — surface area is small enough to stay tractable.

## 3. Lift abaddon's KNOWLEDGE, not its code

Forking inherits: GTK3 + MSYS2 build chain ("significant headaches" per maintainer; Qt6 rewrite floated), `m_build_number = 363557` (Chrome 67, May 2018 — Discord's #1 fingerprint signal per `BLOCKER-fingerprinting-and-detection.md`), no Windows keychain (`WITH_KEYCHAIN` is libsecret-only; Windows falls through to plaintext `abaddon.ini`), OP-14 `SendLazyLoad` (we don't want member-list subscriptions), no `/science`/`X-Discord-Timezone`/`X-Context-Properties`, `// idk if this actually works` in `websocket.cpp`, and GPLv3.

Greenfield uses abaddon as a **reverse-engineering corpus**:
- `voiceclient.cpp` → learn the OP 2 IDENTIFY → OP 8 HELLO → OP 0 IDENTIFY → OP 2 READY → UDP IP discovery → OP 1 SELECT_PROTOCOL → OP 4 SESSION_DESCRIPTION sequence. Re-implement in ~400 lines, no `Glib::Dispatcher`.
- `objects.cpp` → 15-field super-properties shape. Rewrite with current Chrome 134 UA + weekly build-number scrape.
- `audio/manager.cpp` → miniaudio + libopus + rnnoise. Re-implement with 20 ms frames (abaddon uses 10 ms) and AES-256-GCM default (abaddon defaults XChaCha20).
- `dave.cpp` → re-wire against libdave's formalized public C++ API.

Calendar time similar to fork-and-modernize, vastly better quality, zero inherited debt.

## 4. Library stack

| Concern | Library | Version | Why |
|---|---|---|---|
| Build | CMake + vcpkg + MSVC 19.50 | vcpkg 2026.04.27 | 2,595 ports on x64-windows-static; clang-cl → clangd |
| GUI core + backend | Dear ImGui docking + Win32 + D3D11 | **v1.92.6** | Immediate-mode; zero CPU when not redrawn |
| HTTP + TLS mimicry | curl-impersonate (lexiforest) | active 2026 | Chrome JA3/JA4/SETTINGS bit-perfect; same `curl_easy_*` API |
| Gateway WS | IXWebSocket | 6.0.0+ autobahn-compliant | Proven against Discord by abaddon; per-message-deflate |
| Voice UDP | raw winsock2 | — | Too thin for a library |
| JSON / Logging | nlohmann/json 3.11.x · spdlog 1.14.x | latest | Header-only |
| Audio I/O | miniaudio (WASAPI shared) | 0.11.x | Single-header; abaddon-proven |
| Codec | **libopus** | **1.6.1 (2026-01-14)** | SSE/SSE2/SSE4.1 + runtime CPU detect |
| Crypto (voice) | libsodium + Win32 BCrypt AES-GCM | 1.0.20+ / OS | XChaCha20 fallback; AES-NI default cipher |
| Crypto (TLS) | BoringSSL via curl-impersonate | bundled | Chrome byte-for-byte |
| **E2EE** | **libdave (C++ public API)** | **`74979cb` (Feb 2026)** | Mandatory; trivial link |
| Token storage | Win32 DPAPI + 8-byte entropy | OS | Per-user encrypted; no plaintext |

## 5. Why ImGui specifically

**Immediate-mode rendering means the UI literally costs zero CPU when not redrawing.** Retained-mode (GTK/Qt/WinUI) pumps signal queues, timers, accessibility hooks even when minimized. WebView2/Electron run a full compositor. ImGui hidden gates with one line — `if (!visible) { WaitMessage(); continue; }` — and the kernel parks the thread until a real message arrives. When visible (rare), render at vsync — under 0.5% of one core for two list views. When hidden, the swap chain is never touched. **Idle GPU is also zero.**

## 6. Tray-first design

Adopt `DESIGN-minimal-native.md` wholesale: `Shell_NotifyIcon` for the icon, `TrackPopupMenu` for the channel list, `CreateWindowEx` only on "Open window…". Voice-state changes ~once/minute, so menu rebuild from the in-memory model takes microseconds. Steady state: the main window doesn't exist — not just hidden, never `CreateWindowEx`'d. D3D11 device + swap-chain footprint elided until first invocation.

## 7. Voice as a separate process

Spawn `voice-helper.exe` only on join; kill on leave. Greenfield designs against a clean IPC seam from line one — named pipe, ~6 JSON messages — so the main process never imports libopus, libsodium, libdave. Abaddon's `voiceclient.cpp` is wired via `Glib::Dispatcher` and shared GTK signal slots; process-extraction from a fork means cutting a dozen circular deps. Crash isolation: a DAVE/MLS edge case kills the helper, not the tray. Cost: ~50 ms `CreateProcess` on first join — invisible next to the ~200 ms MLS handshake.

## 8. DAVE/MLS — C++ is the only sane integration

Mandatory since 2026-03-02 (close code 4017 to clients with `max_dave_protocol_version: 0`). [discord/libdave](https://github.com/discord/libdave) is C++/C with a formalized public C/C++/Wasm API (`74979cb`).

- **C++ from scratch**: `#include <dave/Session.h>`, link `dave.lib`. Done.
- **Python**: nobody has shipped a binding (`discord.py-self` issue #9948 open). Roll-your-own via cffi/ctypes is real engineering.
- **Forked abaddon**: their `dave.cpp` predates the formalized API — refactor either way.

## 9. Anti-flagging: full byte-level control

With curl-impersonate + IXWebSocket + hand-written JSON, **we own every byte from BoringSSL handshake to WS frame**:

- **TLS ClientHello / HTTP/2 SETTINGS / ALPN / GREASE**: curl-impersonate produces JA3/JA4 **identical to Chrome stable**. Python's `curl_cffi` is the same engine but with GIL hops; stock libcurl (abaddon) is visibly non-Chrome.
- **WS frame ordering + per-message-deflate**: IXWebSocket exposes frame-level options. `discord.py-self` wraps aiohttp — frame ordering not ours.
- **Super-properties freshness**: weekly scrape `discord.com/app` for `Build Number: [0-9]+, Version Hash: [A-Za-z0-9]+`. Abaddon defaults to six-year-stale 363557.
- **`/science` stub** (`app_opened` + `channel_opened`) closes abaddon's #1 telemetry gap.

## 10. Why B beats A; why B beats C

**B vs A**: Forking inherits Chrome-67 super-properties, GTK3 build chain, no Windows keychain, no voice isolation, GPLv3, and `// idk if this actually works`. Abaddon's value is its protocol knowledge — you get all of that *for free* by reading the source in a second editor while writing original C++ in the first. Calendar time is similar; result has half the binary size and none of the inherited debt.

**B vs C**: Python is faster to a *first prototype* (`LANG-python.md`'s case is real), but the bake-off criterion is **steady-state CPU on a gaming laptop**. Asyncio per-wakeup overhead is a measurable fraction-of-a-percent forever; PySide6's event pump runs even when hidden; ImGui literally stops drawing. Python lacks a DAVE binding. Python defers WS frame ordering to aiohttp; C++ owns it. Python would be right for a chat client. For voice-only with mandatory DAVE and CPU-first constraints, C++ is right.

## 11. Honest concessions

- **Dev velocity is slower than Python** (weekend vs 3–6 weeks). Accepted — the criterion is the *running* CPU, not build calendar.
- **Build-system complexity is real.** vcpkg + CMake + presets is more moving parts than `pip install`. Mitigate with `vcpkg.json` manifest mode + CMake Presets.
- **Memory safety on the encryption path is a footgun.** Voice UDP buffer + AEAD nonce + libdave frame transforms are exactly where overruns bite. Mitigations: `/fsanitize=address` in debug, `unique_ptr` discipline, `std::span` over raw pointers, test vectors before wiring.
- **C++20 coroutines are not C# `async`.** Callback-driven IXWebSocket + libcurl multi-handle. Acceptable.
- **No accessibility in ImGui.** Single-user voice client; doesn't matter.

---

## Citations

- abaddon (`voiceclient.cpp`, `audio/manager.cpp`, `discord.cpp`, `dave.cpp`): <https://github.com/uowuo/abaddon>
- Dear ImGui v1.92.6 (2026-02-25): <https://github.com/ocornut/imgui>
- libopus 1.6.1 (2026-01-14): <https://opus-codec.org/news/> · libopus 1.6 (2025-12-15): <https://opus-codec.org/release/stable/2025/12/15/libopus-1_6.html>
- libdave C++ API + formalize commit `74979cb`: <https://github.com/discord/libdave> · <https://github.com/discord/libdave/commit/74979cb33febf4ddef0c2b66e57520b339550c17>
- DAVE close-code 4017 (Userdoccers): <https://docs.discord.food/topics/voice-connections> · DAVE blog: <https://discord.com/blog/meet-dave-e2ee-for-audio-video>
- curl-impersonate (lexiforest): <https://github.com/lexiforest/curl-impersonate>
- IXWebSocket: <https://github.com/machinezone/IXWebSocket>
- vcpkg 2026.04.27 (VS 2026 v145, 2,595 x64-windows-static ports): <https://github.com/microsoft/vcpkg/releases> · triplet docs: <https://learn.microsoft.com/en-us/vcpkg/users/triplets>
- nlohmann/json, miniaudio, libsodium, spdlog: <https://github.com/nlohmann/json> · <https://github.com/mackron/miniaudio> · <https://libsodium.org/> · <https://github.com/gabime/spdlog>
- Win32 DPAPI: <https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata> · `Shell_NotifyIcon`: <https://learn.microsoft.com/en-us/windows/win32/api/shellapi/ns-shellapi-notifyicondataa>
- abaddon ~45 MB RAM: <https://www.xda-developers.com/lightweight-alternatives-electron-apps-dont-eat-up-ram/>
- Mumble low-CPU voice precedent: <https://github.com/mumble-voip/mumble/issues/1092>
- Discord build-number scraper: <https://github.com/adityaxdiwakar/discord-build-scraper>
- X-Super-Properties spec: <https://github.com/KhafraDev/discord-verify/wiki/X-Super-Properties>

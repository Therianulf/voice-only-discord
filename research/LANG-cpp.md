# LANG-cpp: The C++ Case for a Voice-Only Discord Client

## TL;DR

C++ is the right choice because someone already wrote ninety percent of this app in C++: [abaddon](https://github.com/uowuo/abaddon) is a working, voice-capable, third-party Discord client whose `voiceclient.cpp`, `websocket.cpp`, `httpclient.cpp`, and `audio/` modules can be lifted or studied wholesale. C++ also owns the bottom of the CPU budget — no GC, no managed runtime, no async scheduler — and `libopus` (the reference implementation, SSE/SSE2/SSE4.1-optimized) plus direct WASAPI is the most efficient voice pipeline on Windows. The TLS-mimicry story is mature via `curl-impersonate`, a patched libcurl that's a drop-in for what abaddon already uses. We pay with rougher developer ergonomics than C# and less memory safety than Rust, but for "near-zero idle CPU, voice channels only" on Windows, the tradeoffs land firmly on our side.

---

## 1. What we lift from abaddon

abaddon is GPLv3 C++/gtkmm, 96.0% C++ by source share. The repo is a near-complete recipe:

- **`src/discord/voiceclient.cpp/.hpp`** — full Discord voice protocol: WebSocket connect to voice gateway, `Hello`/`Identify`/`Ready` handshake, UDP IP discovery, RTP header construction (`rtp[0]=0x80; rtp[1]=0x78;` Opus payload type), nonce management, XChaCha20-Poly1305 via `crypto_aead_xchacha20poly1305_ietf` from libsodium. Discord's DAVE E2EE (`src/discord/dave.cpp`) is wired in for protocol version > 0. The hard part, sitting there compiled and working.
- **`src/discord/websocket.cpp/.hpp`** — IXWebSocket wrapper with reconnect disabled, custom headers including `Origin: https://discord.com`, GTK-dispatcher callbacks. Strip the dispatcher, keep the rest.
- **`src/discord/httpclient.cpp/.hpp`** — libcurl wrapper with `SetPersistentHeader`, `SetAuth`, `SetUserAgent`, `SetCookie`, typed `request`/`response_type`, `Referer: https://discord.com/channels/@me` plumbing.
- **`src/discord/discord.cpp/.hpp`** — gateway state machine with `SetBuildNumber()` and `SetReferringChannel()` — exactly the hook for current Discord web build numbers.
- **`src/audio/manager.cpp`, `devices.cpp`, `ma_impl.cpp`** — miniaudio (WASAPI on Windows by default).

**Discard:** chat/embed pipeline, SQLite cache (`filecache.cpp`), `src/components/`, `src/dialogs/`, GTK dispatcher pattern. **Upgrade:** super-properties. abaddon defaults to `"Abaddon"` UA and doesn't set `X-Super-Properties` or `X-Discord-Locale`. We add those and a real Chrome UA — trivial on top of `SetPersistentHeader`.

## 2. GUI on Windows — drop GTK, pick Dear ImGui

abaddon's biggest pain is the one to learn from. The maintainer has described "significant headaches" and burnout from GTK3 + MSYS2, and a Qt6 rewrite has been discussed for that reason. The MSYS2 closure (`gtkmm3`, `libhandy`, `glib`, `pango`, `cairo`) bloats install size and breaks on Windows updates. We don't have a chat panel, embed renderer, or 200 dialog windows — we have a tree of servers and a list of voice channels.

- **GTK4** — inherits abaddon's Windows pain. Skip.
- **Qt 6** — ~30 MB of DLLs, long vcpkg builds. Overkill for two list views.
- **Dear ImGui on D3D11** — immediate-mode, ~100 KB of code, zero runtime deps. Used by Valve, Blizzard, NVIDIA tools. **Recommend.**
- **Native Win32 + Direct2D** — lighter, but writing tree views by hand is a week we don't need to spend.
- **WebView2** — defeats the point: 100 MB of Edge runtime to render two lists.

On `WM_SIZE` + `SIZE_MINIMIZED` we set a flag, skip `Present()`, and wake only on gateway events. That's how we hit "near 0% idle CPU."

## 3. Voice — libopus + libsodium + WASAPI

[libopus](https://opus-codec.org/) is the reference implementation and most CPU-efficient by a wide margin: x86 SSE/SSE2/SSE4.1 intrinsics with runtime CPU detection. The 1.1 release alone cut decoding CPU ~40% on ARM and encoding ~30%. Every other "Opus" library — .NET `Concentus`, Rust `audiopus`, Python `pyogg` — is either a binding to libopus or a less-tuned reimplementation. abaddon's pipeline (miniaudio → libopus encode → libsodium XChaCha20-Poly1305 → UDP) is the right stack. Recommend miniaudio for v1 (proven by abaddon, WASAPI shared-mode by default) and direct WASAPI via `IAudioClient3` only if profiling demands it.

## 4. HTTP / TLS fingerprint mimicry — curl-impersonate wins

This is where C++ has a best-in-class option that managed-runtime languages can't easily match:

- **[curl-impersonate](https://github.com/lwthiker/curl-impersonate)** and the more actively-maintained **[lexiforest fork](https://github.com/lexiforest/curl-impersonate)** — patched libcurl linked against BoringSSL/NSS that replicates Chrome/Firefox/Safari/Edge TLS handshakes exactly: cipher suite order, extension order, GREASE values, ALPN preferences, HTTP/2 SETTINGS ordering. **Same `libcurl_easy_*` API** abaddon already uses — drop in a different `.lib`, get JA3/JA4-indistinguishable-from-Chrome traffic. JA4 support is in active development.
- **Rust `rquest`** does similar work but is newer, supports fewer Chrome versions, and has less adversarial battle-testing.
- **.NET `HttpClient`** rides on SChannel by default, which produces a fingerprint that is *not* Chrome's. Swapping it out requires P/Invoking into a native TLS library — at which point .NET's "managed simplicity" advantage is gone.

abaddon's HTTPClient class already abstracts `MakeGET/POST/PUT/PATCH/DELETE` over libcurl. Swapping in curl-impersonate is a build change, not a code change.

## 5. WebSocket — keep IXWebSocket

abaddon uses [IXWebSocket](https://github.com/machinezone/IXWebSocket), a single-dep C++11 lib with TLS and per-message-deflate. Already wired into abaddon's gateway with custom-header support. Alternatives: `boost::beast::websocket` (excellent but pulls Boost.Asio's executor model into our event loop), `websocketpp` (older, less maintained), `libwebsockets` (C-idiomatic callbacks, awkward in C++). **Keep IXWebSocket.**

## 6. Idle CPU profile

When minimized, work is just the gateway heartbeat (~41 s interval, one WS send + small JSON parse). Voice gateway is disconnected when not in a channel; GUI render is gated. No GC pauses; no async-runtime scheduler — one I/O thread (libcurl + IXWebSocket) and one audio callback thread, driven by OS event objects (`WSAEventSelect`, WASAPI event handle), both blocking on kernel objects when idle. ImGui render gates on `WaitMessage()`. Realistic steady-state: a heartbeat tick every 41 s parsing ~500 bytes of JSON — microseconds of CPU per minute. .NET's GC and Rust's tokio reactor each put a small but measurable floor under this; our requirement is "near 0%."

## 7. Packaging on Windows

- **Toolchain:** MSVC (clang-cl as a stretch). abaddon ships MinGW/MSYS2 builds because of GTK — exactly the burnout source. Drop GTK, use MSVC, get better PDBs and clean `signtool` integration.
- **Build:** CMake + vcpkg. `vcpkg install opus libsodium libcurl ixwebsocket nlohmann-json spdlog miniaudio imgui[dx11-binding,win32-binding] --triplet x64-windows-static`. Static-link, one .exe.
- **Expected size:** 4–8 MB static. Versus .NET self-contained ~70 MB, Electron-class ~150 MB.
- **Signing:** standard Authenticode via an EV cert.

## 8. Dev experience — honest take

C++ on Windows in 2026 is better than its reputation, but rougher than C#. **Good:** vcpkg handles every dep we need; MSVC clean builds for this size are sub-30s, sub-second incremental; Visual Studio's debugger is the best on the planet; CMake Presets give clean IDE integration. **Bad:** template errors are still a chore; vcpkg + manual `find_package` version pinning is fiddly; lifetime bugs in callback/signal-heavy code are real (abaddon's `voiceclient.cpp` uses `std::function` captures that can dangle); C++20 coroutines work but aren't C# `async/await`. For 5–8 KLOC that lifts most hard logic from abaddon, the rough edges are bounded — we are not writing Chrome.

## 9. Why C++ beats Rust here

Rust gives memory safety and clean async. But abaddon doesn't exist in Rust. Discord voice is not a documented public protocol — abaddon is the corpus we'd cross-reference against constantly, and doing that lookup in the same language we ship in roughly halves the timeline. Rust's TLS-impersonation options (`rquest`, `reqwest-impersonate`) are younger and cover fewer Chrome versions than curl-impersonate. Rust's Windows GUI story isn't measurably better than Dear ImGui. We'd be greener-field for no runtime win on a surface area small enough that lifetime bugs stay tractable.

## 10. Why C++ beats C# here

C# is the natural Windows pick with excellent tooling. Three reasons we reject it: **(1)** `HttpClient` uses SChannel by default and produces a non-Chrome TLS fingerprint; getting Chrome-shaped handshakes from .NET requires P/Invoking native TLS, throwing away the C# advantage. **(2)** Idle CPU and memory floors are higher — even AOT-compiled .NET keeps a GC alive, and self-contained deployments are ~70 MB vs our ~6 MB. **(3)** No .NET Discord-voice client exists to crib from; we'd reimplement the voice gateway from scratch in a language where the abaddon source is one machine translation away.

## 11. Where we concede

- **Memory safety.** Rust wins outright. Mitigate with AddressSanitizer debug builds, `-Werror`, `unique_ptr`/`shared_ptr` discipline. Audio raw-buffer path is highest-risk.
- **Dev velocity vs C#.** A C# prototype probably reaches "lists servers, joins voice" two weeks faster. Accepted.
- **Async ergonomics vs Rust.** No `async/await` at C#/Rust level. Callback-driven IXWebSocket and libcurl multi-handle like abaddon does — fine, not elegant.
- **Accessibility.** Dear ImGui is weak on screen readers, IME, RTL. For a personal voice client this doesn't matter.

---

## Proposed library stack

| Concern | Library | Why |
|---|---|---|
| Build | CMake + vcpkg + MSVC (x64-windows-static) | Single static .exe, MSVC debugging |
| GUI | Dear ImGui + Win32 + D3D11 backend | ~100 KB; idle-frame gateable |
| HTTP + TLS mimicry | [curl-impersonate (lexiforest)](https://github.com/lexiforest/curl-impersonate) | Chrome JA3/JA4-correct, same libcurl API |
| WebSocket | [IXWebSocket](https://github.com/machinezone/IXWebSocket) | Proven against Discord gateway by abaddon |
| JSON | [nlohmann/json](https://github.com/nlohmann/json) | What abaddon uses; header-only |
| Audio I/O | [miniaudio](https://github.com/mackron/miniaudio) (WASAPI) | Single-header; matches abaddon |
| Codec | [libopus](https://opus-codec.org/) | Reference impl; SSE/SSE2/SSE4.1 optimized |
| Crypto | [libsodium](https://libsodium.org/) | XChaCha20-Poly1305 voice; matches Discord spec |
| Logging | [spdlog](https://github.com/gabime/spdlog) | What abaddon uses |
| Reference | [abaddon](https://github.com/uowuo/abaddon) `src/discord/{voiceclient,websocket,httpclient}.cpp`, `src/audio/manager.cpp` | Working implementation to port |

---

## Citations

- abaddon, third-party C++ Discord client: https://github.com/uowuo/abaddon
- abaddon installation / MSYS2 build docs: https://deepwiki.com/uowuo/abaddon/1.1-installation-and-setup
- libopus reference implementation & SSE optimizations: https://opus-codec.org/release/stable/2013/12/04/libopus-1_1.html
- Opus codec background: https://en.wikipedia.org/wiki/Opus_(audio_format)
- curl-impersonate (original): https://github.com/lwthiker/curl-impersonate
- curl-impersonate (active fork, JA4 support): https://github.com/lexiforest/curl-impersonate
- TLS fingerprint mimicry overview: https://scrapfly.io/blog/posts/curl-impersonate-scrape-chrome-firefox-tls-http2-fingerprint
- IXWebSocket: https://github.com/machinezone/IXWebSocket
- nlohmann/json: https://github.com/nlohmann/json
- miniaudio: https://github.com/mackron/miniaudio
- libsodium: https://libsodium.org/
- spdlog: https://github.com/gabime/spdlog
- Dear ImGui: https://github.com/ocornut/imgui
- vcpkg: https://github.com/microsoft/vcpkg
- Dear ImGui getting started (Win32 + DirectX): https://github.com/ocornut/imgui/wiki/Getting-Started

# LANG-csharp: Why C# / .NET 8+ is the right choice

## TL;DR

C# on .NET 8/9 is the strongest fit for a Windows-only, voice-only Discord client. **WebView2** ships with Windows and lets us host the *real* Discord web client in a custom shell — the most credible path to "looks like Discord web traffic" without reimplementing the gateway. **NativeAOT** produces a 10–30 MB self-contained binary with sub-100 ms startup and <60 MB working set — idle CPU indistinguishable from C++/Rust. NAudio/WASAPI, Concentus, LibSodium.Net, and `ProtectedData` (DPAPI) cover the rest with no FFI glue. The honest weakness is **TLS fingerprint mimicry**, but WebView2 sidesteps it via Edge. C# is the only stack that gives us Discord-Web-grade traffic for free.

---

## 1. NativeAOT and idle CPU

.NET 8 promoted NativeAOT to a first-class feature. Microsoft and third-party benchmarks agree:

- **Startup**: ~67 ms vs. ~290 ms for JIT (~77% faster).
- **Working set**: ~56 MB vs. ~436 MB for JIT (~87% lower), helped by the DATAS GC that AOT enables by default.
- **Binary size**: ~1.5 MB for a trimmed console app; expect 10–30 MB for our project with WebView2, NAudio, libsodium.

For a minimized tray app, AOT erases the cost story that hounded .NET on the desktop for two decades: no JIT warm-up, no R2R rehydration. The runtime is statically linked; the event loop sleeps in `WaitForSingleObject` with idle CPU indistinguishable from a Rust or C++ equivalent. Vs. **JIT .NET**: AOT wins on startup, working set, and cold-CPU power. Vs. **Rust/C++**: AOT is slightly larger on disk (Rust release-LTO 3–8 MB; C++ MSVC 2–5 MB), but at *idle* the working-set delta is single-digit MB and CPU is the same. On the metric that matters here, they tie.

## 2. WebView2: the killer card

This is where C# stops competing and starts dominating. **WebView2** is the Edge (Chromium) engine as an embeddable control, preinstalled on Windows 10/11. Binding: `Microsoft.Web.WebView2` on NuGet (v1.0.3967+, monthly cadence).

**Approach A — render our own minimal HTML/CSS UI.** WebView2 hosts a tiny local page; .NET owns the WebSocket and audio, wired in via `CoreWebView2.AddHostObjectToScript`. Pros: trivial layout, free font rendering, zero XAML. Cons: a Chromium process tree is ~80–150 MB resident across renderer + GPU + utility. Mitigation: `MemoryUsageTargetLevel = Low` and `TrySuspendAsync()` when hidden bring the renderer near sleep.

**Approach B — host the real Discord web client.** Point WebView2 at `https://discord.com/channels/@me` and decorate the page (CSS injection, `AddScriptToExecuteOnDocumentCreatedAsync`) to hide everything except servers and voice. Because the WebView2 *is* Edge, the TLS fingerprint, HTTP/2 frame order, JA3/JA4, gateway WebSocket framing, even SDP details are byte-identical to a real Discord-in-Edge session. This collapses the "looks like Discord web traffic" requirement to nothing — *because it literally is* a Discord web client.

A hybrid is also viable: WebView2 owns gateway and HTTP (we read state via the JS bridge), .NET handles voice UDP + Opus natively for latency. Traffic-sensitive parts run in Edge; latency-sensitive parts run in managed code. C++ (abaddon) and Rust both have to hand-roll TLS mimicry; C# gets it free.

## 3. GUI alternative if not WebView2

- **WPF**: mature, DirectX-backed. NativeAOT *not* officially supported (COM interop / `Marshal.ReleaseComObject`).
- **WinUI 3**: Composition Layer (DX12), best-looking; strict MSIX packaging.
- **Avalonia 11.2+**: Skia-rendered, supports NativeAOT (`<PublishAot>true</PublishAot>`, `<IsAotCompatible>true</IsAotCompatible>`). Smallest binaries of any XAML stack.
- **MAUI**: overkill — mobile-first cross-platform.

**Recommendation: Avalonia 11.2+** if we skip WebView2 — the only XAML stack publishing cleanly as NativeAOT on Windows, stylable into a thin Discord-like sidebar in <500 lines of AXAML. WPF is the safer boring pick (~30 MB more binary, 20-year track record).

## 4. HTTP client and TLS fingerprint — the honest weakness

`System.Net.Http.HttpClient` is excellent (HTTP/2 default, HTTP/3 opt-in, async, pooled), but on Windows it uses **SChannel**. SChannel's ClientHello does not match Chrome's — different cipher order, no GREASE, different extension layout. Out of the box, our JA3/JA4 screams "not a browser."

C# mimicry options exist but are thin: **CycleTLS-dotnet** (`mnickw/CycleTLS-dotnet`, wraps the Go CycleTLS process), **TlsClient** (`danikishin/TlsClient`, pure-C# custom JA3, less battle-tested), or direct **BoringSSL P/Invoke**. C++ has `lwthiker/curl-impersonate` (gold standard, BoringSSL-backed libcurl); Rust has `rquest` (single crate, actively maintained).

**This is the one place C# loses on technical merit.** Approach A means pulling in CycleTLS or a BoringSSL shim. Approach B makes the question evaporate — Edge does the TLS. *Sufficient reason on its own to prefer Approach B.*

## 5. WebSockets

`System.Net.WebSockets.ClientWebSocket` is mature, fully async, supports per-message-deflate, runs over HTTP/2 when configured. Non-issue. WS upgrade goes through `HttpClient`, so it inherits the TLS-mimicry question above.

## 6. Voice (Opus, WASAPI, libsodium)

- **Opus**: **Concentus 2.2.2** (`lostromb/concentus`, NuGet, May 2024) — pure-managed Opus, zero native deps, AOT-friendly. ~40–50% of libopus throughput, irrelevant for a single 48 kHz mono stream (well under 1% of one core). Companion `Concentus.Native` exists if we ever want native speed.
- **WASAPI**: **NAudio**. `WasapiCapture` + `WasapiOut` give shared-mode capture/playback with 10–20 ms buffers — below Discord's jitter budget. Exclusive mode for sub-10 ms.
- **Voice encryption**: Discord voice now defaults to `aead_xchacha20_poly1305_rtpsize` (since `xsalsa20_poly1305` was deprecated late 2024). **LibSodium.Net** exposes XChaCha20-Poly1305 and AES-256-GCM — both in Discord's current mode list.

Three actively-maintained NuGet packages, zero exotic dependencies.

## 7. Discord library landscape — hand-roll the gateway

Both **Discord.Net** and **DSharpPlus** explicitly refuse user-account automation and have deprecated voice. DSharpPlus docs: *"Automating a user account is against Discord's Terms of Service and is not supported."* Voice is marked **Deprecated**. So for *any* candidate language we hand-roll gateway + voice UDP. C# makes this ergonomic: async/await, `System.Text.Json` source generators (AOT-friendly), `System.IO.Pipelines` for zero-copy reads, `ClientWebSocket` handling the heartbeat loop.

## 8. DPAPI — token storage solved by stdlib

`System.Security.Cryptography.ProtectedData.Protect(...)` calls Windows DPAPI directly. One line, no key management, AOT-compatible. Token is encrypted to the current user account. C++ needs raw `CryptProtectData` + manual `LocalFree`; Rust needs the `windows` crate and `unsafe` blocks. C# just works.

## 9. Developer experience

Visual Studio 2022 and VS Code both have first-class C# tooling: edit-and-continue, hot reload, world-class CLR debugger, BenchmarkDotNet for the idle path, dotMemory/dotTrace for working set. Incremental builds 1–3 s; AOT publish 10–20 s. Per-dev-hour velocity on Windows is best in category.

## 10. Why C# beats Rust here

Rust is the most attractive *systems* language and `rquest` + `tokio-tungstenite` would give a beautifully TLS-mimicked client. But Rust loses on GUI: no equivalent of WebView2 with the same maintenance backing. Tauri uses WebView2 internally but adds a JS toolchain and complicates DPAPI. egui/iced are fine for a plain window, but the moment we want the "host real Discord web" trick, Rust must use Tauri or the `webview2-com` crate — all of C#'s overhead, none of its ergonomics. C# is the language Microsoft ships WebView2 in; impedance is zero.

## 11. Why C# beats C++ here

C++ (abaddon's stack) gives curl-impersonate-grade TLS mimicry, genuinely better than C# out of the box. The rest is a death march: GTK on Windows looks alien, Win32/Direct2D is a 1990s API surface, DPAPI is `wincrypt.h` with manual cleanup, no Concentus equivalent that doesn't link libopus. CMake + vcpkg + the verbose WebView2 C++ binding balloons build times. For a single-dev Windows client, C++ pays a tax for one advantage WebView2 nullifies anyway.

## Where I concede

1. **TLS fingerprint ecosystem.** C# is third behind C++ and Rust. *Mitigated entirely by Approach B.*
2. **"Unofficial Discord client" community.** Almost everything in this niche (abaddon, ripcord) is C++. No body of C# reverse-engineering for the gateway/voice — we do more first-principles work.
3. **Cross-platform.** C# can (Avalonia/MAUI), but the project explicitly doesn't need it; moot.
4. **Process-tree weight with WebView2.** Chromium subprocesses add ~80–150 MB resident — the trade for traffic indistinguishability. Suspend-on-hide brings idle CPU near zero; RAM is heavier than pure-WPF.

---

## Proposed library / package stack

| Layer | Package | Why |
|---|---|---|
| Runtime | .NET 9 + NativeAOT | Smallest binary, fastest startup, lowest idle working set |
| GUI shell | `Microsoft.Web.WebView2` (1.0.3967+) | Hosts Discord web; identical TLS/HTTP fingerprint |
| Fallback GUI | Avalonia 11.2+ (AOT-supported) | If we reject WebView2 |
| HTTP | `System.Net.Http.HttpClient` (built-in) | Async, HTTP/2 default, HTTP/3 opt-in |
| TLS mimicry (only if not WebView2) | `mnickw/CycleTLS-dotnet` or BoringSSL P/Invoke | Honest weakness; only relevant for own-UI path |
| WebSocket | `System.Net.WebSockets.ClientWebSocket` (built-in) | Gateway connection |
| JSON | `System.Text.Json` + source generators | AOT-friendly, fast |
| Opus codec | `Concentus` 2.2.2 (pure managed) | No native deps; AOT-friendly |
| Audio I/O | `NAudio` + `NAudio.Wasapi` | WASAPI capture/playback |
| Voice encryption | `LibSodium.Net` | XChaCha20-Poly1305, AES-256-GCM |
| Token storage | `System.Security.Cryptography.ProtectedData` (built-in) | DPAPI, one-liner |
| Tray + autostart | `H.NotifyIcon.Wpf` or `Shell_NotifyIconW` P/Invoke; registry `Run` key | Trivial |
| Packaging | `dotnet publish -r win-x64 -p:PublishAot=true` → single ~25 MB exe | No installer needed |

---

## Citations

- [Performance Improvements in .NET 8 — Microsoft .NET Blog](https://devblogs.microsoft.com/dotnet/performance-improvements-in-net-8/)
- [Native AOT deployment overview — Microsoft Learn](https://learn.microsoft.com/en-us/dotnet/core/deploying/native-aot/)
- [Enable Native AOT in .NET 8 — NanoByte Technologies](https://nanobytetechnologies.com/Blog/Enable-Native-AOT-in-NET-8-Step-by-Step-Guide-Benchmarking-Performance-Gains)
- [Performance best practices for WebView2 apps — Microsoft Learn](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/performance)
- [Get started with WebView2 in WPF — Microsoft Learn](https://learn.microsoft.com/en-us/microsoft-edge/webview2/get-started/wpf)
- [Microsoft.Web.WebView2 — NuGet](https://www.nuget.org/packages/microsoft.web.webview2)
- [Concentus 2.2.2 — NuGet](https://www.nuget.org/packages/Concentus)
- [Concentus — GitHub](https://github.com/lostromb/concentus)
- [NAudio WASAPI Capture — DeepWiki](https://deepwiki.com/naudio/NAudio/4.1-wasapi-capture)
- [LibSodium.Net guide](https://libsodium.net/guide.html)
- [Discord Voice Connections docs](https://discord.com/developers/docs/topics/voice-connections)
- [DSharpPlus FAQ — selfbot policy and voice deprecation](https://dsharpplus.github.io/DSharpPlus/faq.html)
- [Discord.Net xsalsa20_poly1305 deprecation issue #3155](https://github.com/discord-net/Discord.Net/issues/3155)
- [ProtectedData Class — Microsoft Learn](https://learn.microsoft.com/en-us/dotnet/api/system.security.cryptography.protecteddata)
- [Avalonia Native AOT docs](https://docs.avaloniaui.net/docs/deployment/native-aot)
- [WinUI vs WPF vs UWP — Avalonia Blog](https://avaloniaui.net/blog/winui-vs-wpf-vs-uwp)
- [CycleTLS-dotnet — GitHub](https://github.com/mnickw/CycleTLS-dotnet)
- [TlsClient (C#) — GitHub](https://github.com/danikishin/TlsClient)
- [curl-impersonate (C++) — GitHub](https://github.com/lwthiker/curl-impersonate)
- [abaddon — reference C++ Discord client](https://github.com/uowuo/abaddon)

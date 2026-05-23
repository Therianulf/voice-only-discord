# Language Choice: Rust

## TL;DR

Rust hits the sweet spot for this project. The voice stack (`songbird` driver + `audiopus` + `cpal`) is the most mature outside Discord itself. `rquest`/`wreq` give Chrome-grade JA3/JA4/HTTP2 TLS impersonation that's effectively impossible in stock C# and painful in C++. `egui` + `tray-icon` produces a ~5 MB single-exe that doesn't repaint on idle. Tokio's current-thread runtime parks on IOCP and burns no CPU when nothing's happening. The borrow checker eliminates the threading bugs Abaddon (the C++ reference) keeps shipping fixes for. We pay for it in compile times and lack of a turnkey user-account library, neither of which actually matters here.

## 1. Discord library ecosystem: we're writing the gateway

No Rust library wraps the user-account gateway. The two big ones are bot-only:

- **serenity** ([serenity-rs/serenity](https://github.com/serenity-rs/serenity)) is high-level, command-framework-shaped, bot-token-assuming. Useless here.
- **twilight** ([twilight-rs/twilight](https://github.com/twilight-rs/twilight), 836 stars, MSRV 1.89) is modular. We grab **`twilight-model`** for the JSON event schema (hundreds of structs for free) and ignore the rest.

Realistic plan:
- **Reuse from twilight**: `twilight-model` types and opcode constants.
- **Write ourselves**: WebSocket loop on `tokio-tungstenite` ([snapview/tokio-tungstenite](https://github.com/snapview/tokio-tungstenite)). Heartbeat, IDENTIFY, RESUME, sequence/session bookkeeping — ~500-800 lines because we only care about servers/channels/voice state.
- **Refer to Abaddon**: [uowuo/abaddon](https://github.com/uowuo/abaddon) (~1.3k stars) is the cleanest open-source user-account gateway reference. We translate, we don't link.

The Rust win isn't a magic wrapper — it's that `tokio` + `tokio-tungstenite` + `serde` + selective `twilight-model` gives us a smaller, more correct gateway than any Python/JS self-bot framework, and `Send`/`Sync` makes the heartbeat-vs-reader race a compile error.

## 2. Voice: Rust's strongest leg

This is where Rust pulls ahead of everything.

- **`songbird` v0.6.0 "Hoopoe" (April 2026)** ([serenity-rs/songbird](https://github.com/serenity-rs/songbird), 503 stars) is the most actively maintained open-source Discord voice stack, period. Voice gateway v8, UDP discovery, xsalsa20/aead-aes256-gcm encryption, Opus passthrough, RTP/RTCP, optional voice receive. Docs explicitly support `twilight` or no framework via the `gateway` feature.
- **Honest caveat**: songbird's high-level `Songbird` manager is bot-shaped. We use the lower-level **`songbird::driver::Driver`**, which is gateway-agnostic — you feed it `ConnectionInfo` (endpoint, session_id, token) that *our* gateway produced. Documented entry point.
- **`audiopus`** ([Lakelezz/audiopus](https://github.com/Lakelezz/audiopus)) wraps libopus 1.3 with a static Windows build.
- **`cpal` 0.15+** ([RustAudio/cpal](https://github.com/RustAudio/cpal)) provides WASAPI capture/playback in pure Rust. There's a known [latency-accumulation issue](https://github.com/RustAudio/cpal/issues/817) under odd buffer configs — for a chat client with 20ms Opus frames in shared mode, fine. If it bites, `wasapi-rs` is a thinner direct binding.

C++ has libopus + raw WASAPI but you assemble everything by hand. C# has NAudio + `Concentus`, but real-time Opus through P/Invoke plus GC pauses on the audio thread is a crackle factory. Rust glues two crates together.

## 3. GUI: egui, not close

We need a server list and clickable voice channel rows. Idle 0%. Small binary. Native chrome is not a requirement.

- **`egui` 0.34** ([emilk/egui](https://github.com/emilk/egui), 29.2k stars) is immediate-mode but **does not repaint on idle** — its README is explicit: "if your app is idle, no CPU is wasted… only repaints when there is interaction or animation." Smallest binary among major options, trivial to learn.
- **`iced`** is retained-mode/Elm-y, bigger, slower compile, more ceremony for a sidebar.
- **`slint`** is great but its DSL is wasted here, and the dual-license adds noise for a personal tool.
- **`dioxus`** and **`Tauri`** both pull in WebView2 — wrong idle profile and wrong binary size for this app.

`egui` + `eframe` + **`tray-icon` 0.24** ([tauri-apps/tray-icon](https://github.com/tauri-apps/tray-icon), 377 stars, May 2026) gives us hide-to-tray on minimize. egui explicitly does not target native look, but this is a single-user tool that sits next to a fullscreen game — fine.

## 4. TLS fingerprint mimicry: Rust's killer feature

Discord fingerprints unofficial clients. The Abaddon-style "curl with Chrome-ish headers" works until it doesn't.

- **`rquest`** ([penumbra-x/rquest](https://github.com/penumbra-x/rquest)) and the related **`wreq`** ([0x676e67/wreq](https://github.com/0x676e67/wreq)) provide JA3/JA4 + HTTP/2 SETTINGS frame impersonation backed by BoringSSL, with 100+ maintained browser profiles in `wreq-util`. You pick `Emulation::Chrome131` and the ClientHello, ALPS, HTTP/2 SETTINGS, frame ordering, PRIORITY frames match real Chrome.
- **`reqwest-impersonate`** ([4JX/reqwest-impersonate](https://github.com/4JX/reqwest-impersonate)) is the older fork; rquest/wreq are where development moved.

**Genuinely hard in C++**: `curl-impersonate` exists but means shelling out or vendoring patched curl + patched BoringSSL. **Much worse in C#**: `HttpClient` uses SChannel/.NET TLS, you cannot configure the ClientHello extension order, and projects that try (CycleTLS, etc.) shell out to Go binaries. Rust gives us `Client::builder().emulation(Emulation::Chrome131).build()`. For a project whose stated goal is "looks like Discord web," this single capability tilts the choice.

WebSocket handshakes are also fingerprinted; rquest/wreq do WS upgrade through the same TLS stack — a plain `tokio-tungstenite` connect would expose a rustls ClientHello and blow our cover.

## 5. Idle CPU

Tokio's "high CPU" reputation comes from busy multi-threaded servers. Our setup:

- `Builder::new_current_thread()` — single-threaded, no work-stealing, no inter-thread wakeups. The runtime parks on IOCP when idle.
- Tokio timers have 1ms resolution; we have *one* timer (the 41s heartbeat). No-op overhead.
- The GUI is idle until you mouse over the window. WASAPI callbacks fire only when joined to voice.

Realistic expectation: tray-minimized, no voice, ~0.0–0.1% CPU on a modern laptop. In voice: ~1-2% for Opus encode/decode + WASAPI. A hand-rolled `mio`/IOCP loop saves us essentially nothing at this scale; see the [Tokio scheduler post](https://tokio.rs/blog/2019-10-scheduler) and the [thread-wakeup discussion](https://github.com/tokio-rs/tokio/discussions/4753).

## 6. Packaging on Windows

- **Single-exe**: `cargo build --release` + `strip` + optional `upx` → 4-8 MB `voice-only-discord.exe`. No runtime, no .NET, no Edge.
- **`cargo-wix`** ([volks73/cargo-wix](https://github.com/volks73/cargo-wix)) for optional MSI; integrates `signtool` for code-signing.
- **DPAPI**: `windows-dpapi` ([sheridans/windows-dpapi](https://github.com/sheridans/windows-dpapi)) wraps `CryptProtectData` for storing the user token user-scoped.
- **Autostart**: write `HKCU\…\Run` directly via `windows-rs` ([microsoft/windows-rs](https://github.com/microsoft/windows-rs)).
- **Tray**: `tray-icon` 0.24.

## 7. Dev experience tradeoffs

- **Compile times**: clean release ~2-4 min; incremental dev rebuilds 4-15s. Slower than Go, fine for a personal project.
- **Debugging on Windows**: VS Code + CodeLLDB or the MSVC C++ debugger over PDBs is solid in 2026.
- **Async + borrowck friction**: real. Sharing the session struct across reader/heartbeat/UI tasks pushes you to `Arc<Mutex<State>>` or channels. First week feels worse than C#; after that it works and the compiler stops you from racing.

## 8. Why Rust beats C++ here

C++ would mean Abaddon-2: vcpkg dependency hell for libopus + libsodium + a GUI toolkit + curl-impersonate, CMake, and manual thread-safety across gateway/voice/UI. Abaddon ships periodic fixes for races that exist precisely because the read task, heartbeat task, and UI thread share state. Rust's `Send`/`Sync` makes those bugs compile errors. For a single-dev project where time is the binding constraint, eliminating that bug category beats any C++ ecosystem maturity advantage.

## 9. Why Rust beats C# here

C# would mean .NET 8 + Avalonia + DSharpPlus (bot-only, same problem as serenity). Three concrete losses: **(a)** you cannot do JA3/JA4/HTTP-2 impersonation in .NET — SChannel and `SocketsHttpHandler` don't expose ClientHello tuning; workarounds shell out to a Go binary, which is worse than just writing Rust. **(b)** GC introduces 5-30ms collection pauses that show up as audio crackle in a 20ms Opus loop unless you fight ServerGC and pin buffers. **(c)** self-contained .NET + Avalonia ships at 30-60 MB vs a ~5 MB Rust exe. "C# is faster to write" is real but eaten by maintaining a sidecar TLS proxy.

## 10. Where Rust loses (honestly)

- **GUI iteration speed**: C# + WinForms/Avalonia hot-reload faster than `cargo run`. For a UI this trivial it doesn't matter; for a richer GUI it would.
- **No turnkey user-account Discord library**. Python's `discord.py-self` is fastest to prototype with — but can't fingerprint TLS, can't avoid GC jitter on audio. Wrong choice for the actual requirements.
- **`cpal` WASAPI has rough edges** ([#817](https://github.com/RustAudio/cpal/issues/817)). Worst case: drop to `wasapi-rs`, a day of work.
- **songbird is bot-shaped**. We use only the driver. If the driver API changes we adapt — it's stable.

Net: Rust is the only stack where Chrome TLS impersonation, real-time GC-free voice, and a 5 MB single-exe coexist. That's exactly the project.

---

## Proposed crate stack

- `tokio` (current-thread runtime) — async runtime, single-threaded for idle efficiency.
- `tokio-tungstenite` — WebSocket client for the Discord and voice gateways.
- `rquest` (or `wreq`) — HTTP client with Chrome JA3/JA4/HTTP2 impersonation; also handles WS upgrade.
- `serde` + `serde_json` — gateway payload (de)serialization.
- `twilight-model` — reused JSON type definitions for gateway events.
- `songbird` (driver only, `gateway` feature disabled) — voice UDP + RTP + crypto + Opus glue.
- `audiopus` — libopus 1.3 bindings.
- `cpal` — WASAPI capture/playback; fallback `wasapi` crate if needed.
- `egui` + `eframe` — immediate-mode GUI that doesn't repaint on idle.
- `tray-icon` — Windows tray icon + context menu.
- `windows-dpapi` — encrypt the user token at rest.
- `windows` (windows-rs) — autostart registry write, native dialogs.
- `tracing` + `tracing-subscriber` — structured logs.
- `cargo-wix` (build tool) — optional signed MSI builder.

## Citations

- twilight repo: https://github.com/twilight-rs/twilight
- twilight docs: https://api.twilight.rs/twilight/
- serenity repo: https://github.com/serenity-rs/serenity
- songbird repo: https://github.com/serenity-rs/songbird
- songbird/twilight example: https://github.com/serenity-rs/songbird/blob/current/examples/twilight/src/main.rs
- tokio-tungstenite: https://github.com/snapview/tokio-tungstenite
- Abaddon (reference C++ client): https://github.com/uowuo/abaddon
- rquest: https://github.com/penumbra-x/rquest
- wreq: https://github.com/0x676e67/wreq
- reqwest-impersonate: https://github.com/4JX/reqwest-impersonate
- audiopus: https://github.com/Lakelezz/audiopus
- cpal: https://github.com/RustAudio/cpal
- cpal WASAPI latency issue: https://github.com/RustAudio/cpal/issues/817
- wasapi-rs: https://crates.io/crates/wasapi
- egui: https://github.com/emilk/egui
- tray-icon: https://github.com/tauri-apps/tray-icon
- cargo-wix: https://github.com/volks73/cargo-wix
- windows-dpapi: https://github.com/sheridans/windows-dpapi
- windows-rs: https://github.com/microsoft/windows-rs
- Tokio scheduler internals: https://tokio.rs/blog/2019-10-scheduler
- Tokio idle/wakeup discussion: https://github.com/tokio-rs/tokio/discussions/4753
- Discord Platform Manipulation Policy: https://discord.com/safety/platform-manipulation-policy-explainer
- 2025 Rust GUI survey (boringcactus): https://www.boringcactus.com/2025/04/13/2025-survey-of-rust-gui-libraries.html

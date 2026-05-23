# DESIGN: Absolute Minimum Native Footprint

*Maverick proposal. The opposite extreme of the WebView2-shell pitch.*

## TL;DR

- **Build a tray-icon-first Win32 app in Rust** (no Tokio, no GTK, no WebView, no framework) that exposes servers and voice channels through a right-click menu and only opens a real window if the user asks for one.
- A single OS thread driving blocking `WSARecv`/`MsgWaitForMultipleObjectsEx` handles the gateway, voice UDP, and the message loop with **<0.1% idle CPU** and a binary under **2 MB**.
- The voice subsystem (Opus + libsodium + libdave) is a **separate child process** that's only spawned when the user actually joins a channel and killed on leave, so the steady-state footprint is just a WS heartbeat every ~41 s.
- Gateway state is aggressively pruned: subscribe to nothing privileged, skip member/presence/DM ingestion entirely, and cache the channel tree to a 50 KB SQLite file so startup is instant.
- The hard constraint is **DAVE/MLS** (enforced 2026-03-01) — the design accepts a one-time integration of `discord/libdave` (C++) via FFI, which is the only piece large enough to matter.
- Targets to beat the field: **<8 MB RAM idle / <0.1% CPU idle / <40 MB in-voice / <2% CPU in-voice / <2 MB binary**.

## Target Spec

| Metric | Idle (no voice) | In-voice | Notes |
|---|---|---|---|
| Resident RAM | **<8 MB** | <40 MB | libopus + libdave dominate in-voice |
| CPU (modern Intel U-class) | **<0.1%** | <2% | Mumble achieves <1% in-voice with complexity 5 [3] |
| Binary size (release, stripped) | **<2 MB main + ~3 MB voice helper** | — | abaddon ships ~15 MB total [9] |
| Cold start to tray | <150 ms | — | Disk-cached channel tree, no Electron warmup |
| Cold start to "in voice" | <1.5 s | — | UDP discovery + DAVE handshake bound |
| Gateway packets/min idle | ~1.5 | ~3 | One heartbeat per heartbeat_interval (~41 s) [1] |
| Privileged intents requested | **zero** | zero | Read-only client; nothing the spam classifier likes |

Targets are deliberately tighter than abaddon (~45 MB RAM [4]) and ~50x tighter than Electron Discord (300–600 MB). The justification is structural, not tweaking: no V8, no Chromium, no Tokio reactor, no member cache, no message cache, no UI rendering when the window is hidden.

## Stack pick: Rust, current_thread + blocking I/O, raw Win32

**Language: Rust.** C++ also works and trims more bytes, but Rust gives us safety on the crypto paths (DAVE, xchacha20-poly1305) while keeping the C ABI we need for libopus and libdave. Zig is tempting for the 2 KB hello-world headline [10], but Win32 ergonomics and Opus/sodium ecosystem are immature. Raw C earns nothing — we are CPU-wake-up-bound, not byte-bound.

**Runtime: none.** No Tokio. A current-thread runtime is ~200–400 bytes per task [11], but the *binary* cost is real (mio + Tokio + futures) and worse, it pushes the multi-future mental model on what is actually two sockets and a message loop:

1. One WebSocket to `gateway.discord.gg` (TLS).
2. One UDP socket to the voice server (only when in voice).
3. One Win32 message queue.

`MsgWaitForMultipleObjectsEx(handles, INFINITE)` with two `WSAEventSelect` handles plus the message queue, on the main thread, gives **0% CPU when idle** — the kernel parks the thread until something happens [13] — and integrates the tray right-click without any cross-thread channel.

**TLS: schannel** via `windows-rs`. Free, already in the OS, ~700 KB binary savings vs rustls+ring.

**GUI: raw Win32.** `Shell_NotifyIcon` for the tray [12]; `CreatePopupMenu`/`TrackPopupMenu` for the menu [12]; `CreateWindowEx` only when the user asks for a window. No GTK, Qt, WPF, or WinUI 3 (WindowsAppSDK alone is ~50 MB).

## The six radical bets, defended

### 1. Single-threaded blocking I/O

The async-runtime narrative is built on C10K. We are not a server; we have *two* sockets. Tokio pays for a scheduler, reactor, mio, and task allocator to coordinate work that fits in one thread. Native blocking with `WSAEventSelect` + `MsgWaitForMultipleObjectsEx` gives the kernel exactly enough information to park the thread. Result: **idle CPU is "unmeasurable on a modern laptop."**

### 2. Tray-icon-first UI

The user is gaming 90% of the time. The window is dead weight. The tray right-click becomes:

```
Voice-Only Discord
├── Server #1
│   ├── #general (3 users)
│   ├── #raid (active, join)
│   └── ...
├── Gaming Server
│   └── ...
├── ─────────────
├── Currently in: (nothing)
├── Leave voice (disabled)
└── Quit
```

`TrackPopupMenu` with `SetForegroundWindow` is the well-known incantation [8]. Precedent: mIRC has been tray-primary for two decades [8]. The "papercut" is rebuilding the menu each click — but Discord's voice state changes ~once/minute, so we rebuild from the in-memory model in microseconds.

A "full" window exists but is only summoned via the menu's "Open window…" item. Steady state: **`WM_PAINT` is never sent to a hidden window**, which is our single largest CPU saving versus any framework client.

### 3. Defer every byte the user can't see

Discord's READY can be megabytes [2][6] — ~1 MB compressed for a 100-guild user [2]. We:

- Identify as a web client (`properties.os: "Windows"` per Userdoccers convention [5]) to look normal.
- Use **lazy guild subscriptions** [5]: subscribe to channels only for the guild whose submenu is open, with a 30 s idle expiry.
- Skip `GUILD_MEMBERS`, `GUILD_PRESENCES`, `MESSAGE_CONTENT`, `DIRECT_MESSAGES`.
- Drop message events at the WS layer.
- Keep `VOICE_STATE_UPDATE` and `CHANNEL_UPDATE` in the hot path; nothing else.

After the initial `READY`/`READY_SUPPLEMENTAL` parse (~10 ms via `flate2`), we sit at ~1 packet/min.

### 4. Hibernate the WS when minimized AND not in voice

I'll *partly* back off. A fresh `IDENTIFY` triggers full `READY` + `READY_SUPPLEMENTAL` [7] — ~1 MB compressed for a 100-guild user [2] and ~10 ms decompression every cycle. Plus the spam classifier dislikes reconnect loops (flag risk).

**Compromise: resume, don't reconnect.** Hold the TCP socket open even when idle; rely on `resume_gateway_url` if Discord closes us. Idle WS costs ~1 syscall/min (heartbeat + ack), cheaper than the resume handshake amortized over any plausible window. CPU asleep: **zero**, the thread is parked.

### 5. Voice as a separate process

The highest-leverage idea. Opus + libsodium + libdave is the bulk of the binary and the only hot path. Make it `voice-helper.exe`:

- Main stays <2 MB RAM idle.
- `CreateProcess` only when joining a channel; killed on leave.
- A crash in Opus/DAVE doesn't take down the tray.
- Voice is an *optional* component — a user who never joins never installs it.
- IPC: anonymous pipe with JSON `VOICE_SERVER_UPDATE` forwarding, <2 KB/s.

Cost: ~50 ms spawn on first join — invisible next to the DAVE handshake anyway.

### 6. Pre-cached channel tree

Startup reads `cache.sqlite` (~50 KB for 100 guilds: id, name, voice channel ids, positions). Tray menu renders in <5 ms **before the WS connects**. `READY` arrives and we diff. WAL-mode SQLite, batched writes on `GUILD_UPDATE`/`CHANNEL_UPDATE`. The ~700 KB SQLite costs is worth it vs rolling a file format.

## The thing this design has to bite: DAVE/MLS

The most awkward research finding: **as of 2026-03-01, Discord disconnects voice clients that don't support DAVE with close code 4017** [14][15]. DAVE requires full MLS 1.0 group key exchange, AES-128-GCM frame encryption with codec-aware unencrypted ranges, ECDSA P-256 identity keys, and WebRTC-encoded-transform-equivalent per-frame encryption — a real cryptography stack and the single biggest knock against the minimal-native pitch. Honest answer: **statically link `discord/libdave`** (C++/C, manageable FFI [16]). Adds ~2 MB to the voice helper, non-negotiable.

Silver lining: libdave runs *inside* `voice-helper.exe`, never touching the main tray process. The tray process knows nothing about DAVE.

## Account-flag risk

A custom client that looks like the web client but never speaks is exactly the spam classifier's least-favorite signal. Mitigations:

- Use real web `properties` (abaddon's approach [9]).
- Never auto-reconnect faster than ~5 s.
- Never `request_guild_members` (highest-risk endpoint [17]).
- Reuse the user's real `super_properties` bitfield captured once from their web client.
- Never type, never speak. Joining voice and listening is indistinguishable from "user minimized their main client while in voice."

## Opus settings: how cheap can we go?

The voice gateway *requires* 48 kHz / 2 ch / 20 ms frames on the wire [18]. We can't change that. But on the encoder we can:

- **Complexity 3** (vs default 10) [19][20]. Documented as real-time on limited hardware; voice-quality delta is imperceptible.
- **32 kbps VBR** (Discord supports 8–96 kbps, default 64 [21]). 32 is telephone-plus.
- **DTX** [19]: send near-zero packets when not speaking.

Decode runs at 48 kHz stereo (forced by the senders); complexity doesn't apply. Hardware Opus via WASAPI is a non-starter — Windows doesn't expose it to userland reliably. Software libopus.

For capture/playback: **WASAPI shared mode at 10 ms buffers** [22]. Lowest power, adequate for voice. Exclusive mode and sub-millisecond buffers are for ASIO musicians, not Discord listeners.

## What we explicitly do NOT build

No chat rendering, no avatars, no emoji/stickers, no video/screen share, no notifications beyond tooltip changes, no theme system (Win32 honors system theme), no auto-updater, no telemetry. Each absence is a feature: it's not missing, it's *not built* because it costs CPU and isn't needed.

## Why this beats the alternatives

- **vs Electron/WebView2:** ~50–100x smaller resident set, no V8 GC, no browser warmup, no compositor running while gaming.
- **vs abaddon:** ~5–10x smaller, no GTK overhead, tray-first instead of window-first, voice in a separate process.
- **vs official Discord:** different sport.

Risk is developer time: raw Win32 + custom gateway + DAVE FFI is a 2–4 month project for one developer, versus 2–3 weeks for a shell-on-Discord-web. The argument for spending it is the goal: "low CPU for a gaming laptop" is bought by **structural** choices, not by tuning. You can't tune an Electron client to <0.1% idle CPU — you have to choose not to be an Electron client from the first commit.

## Citations

1. Discord, "Gateway — Documentation" — heartbeat opcode and interval. https://docs.discord.com/developers/events/gateway
2. dav1ta, "Discord Gateway Scale" — payload size estimates. https://dav1ta.github.io/studies/discord-gateway-scale/
3. mumble-voip/mumble issue #1092 — CPU usage at low latency, comparison vs TeamSpeak. https://github.com/mumble-voip/mumble/issues/1092
4. xda-developers, "4 lightweight alternatives to Electron apps" — abaddon ~45 MB RAM. https://www.xda-developers.com/lightweight-alternatives-electron-apps-dont-eat-up-ram/
5. Discord Userdoccers, "Gateway" — lazy guild subscriptions, intents. https://docs.discord.food/topics/gateway
6. discord-userdoccers, "Gateway Intents & Capabilities" via DeepWiki. https://deepwiki.com/discord-userdoccers/discord-userdoccers/9.2-gateway-intents-and-capabilities
7. Discord Userdoccers, "Using Gateway" — READY_SUPPLEMENTAL and PRIORITIZED_READY_PAYLOAD capability. https://docs.discord.food/gateway/using-gateway
8. Microsoft Learn / community examples — TrackPopupMenu + SetForegroundWindow pattern. https://learn.microsoft.com/en-us/windows/win32/api/shellapi/ns-shellapi-notifyicondataa
9. uowuo/abaddon README — C++/GTK 3 stack, ixwebsocket, libcurl, libopus, libsodium, libdave. https://github.com/uowuo/abaddon
10. zserge.com, "Zig, the small language" — binary size headline. https://zserge.com/posts/zig-the-small-language/
11. tokio.rs / docs.rs — runtime per-task overhead and current-thread scheduler. https://docs.rs/tokio/latest/tokio/runtime/index.html
12. Microsoft Learn, "NOTIFYICONDATAA (shellapi.h)" — Shell_NotifyIcon. https://learn.microsoft.com/en-us/windows/win32/api/shellapi/ns-shellapi-notifyicondataa
13. Microsoft Learn, "Preventing Hangs in Windows Applications" — GetMessage parks the thread. https://learn.microsoft.com/en-us/windows/win32/win7appqual/preventing-hangs-in-windows-applications
14. Discord Userdoccers, "Voice Connections" — DAVE enforcement and close code 4017. https://docs.discord.food/topics/voice-connections
15. Discord, "Meet DAVE: Discord's New End-to-End Encryption for Audio & Video". https://discord.com/blog/meet-dave-e2ee-for-audio-video
16. discord/libdave repository — language composition. https://github.com/discord/libdave
17. nomsi gist, "Selfbot Rules" — flag-risk behaviors. https://gist.github.com/nomsi/2684f5692cad5b0ceb52e308631859fd
18. Discord, "Voice — Documentation" — Opus 48 kHz / 2 ch / 20 ms requirement. https://docs.discord.com/developers/topics/voice-connections
19. Xiph wiki, "Opus Recommended Settings" — complexity, DTX, VBR. https://wiki.xiph.org/Opus_Recommended_Settings
20. Asterisk, "Configuring the Opus Encoder for Asterisk" — complexity 3–6 for real-time voice. https://www.asterisk.org/configuring-opus-encoder-asterisk/
21. Discord Support, "Audio Bitrate FAQ" — 8–96 kbps range, 64 kbps default. https://support.discord.com/hc/en-us/articles/11635925354775-Audio-Bitrate-FAQ
22. Microsoft Learn, "Low Latency Audio" — WASAPI shared mode and buffer-size CPU tradeoffs. https://learn.microsoft.com/en-us/windows-hardware/drivers/audio/low-latency-audio

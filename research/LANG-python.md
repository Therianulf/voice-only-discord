# LANG: Python

## TL;DR

Python is the **only** language with multiple actively maintained Discord *selfbot* libraries — `discord.py-self` shipped v2.1.0 on **18 January 2026** and `selfcord.py` shipped v1.0.3 in **October 2025**. That single fact reframes the whole decision: in Rust/C++/C# you build a Discord user-mode client from raw gateway packets; in Python you `pip install discord.py-self[voice]` and override the HTTP layer to use `curl_cffi` for a perfect Chrome JA3. The "Python is slow" objection is real but mostly irrelevant — for an idle WebSocket heartbeat plus PyNaCl's native Opus, the bottleneck is the network card, not CPython. You pay ~60 MB of idle RAM, ship a 25–35 MB Nuitka-compiled `.exe`, and get the project done in a weekend instead of a month.

---

## 1. Library ecosystem — the killer card

This is the entire argument in one section. Discord user-mode wrappers in Python:

- **`discord.py-self`** (Dolfies fork of Rapptz/discord.py) — 1.2k stars, 246 forks, 5,295 commits, **v2.1.0 on 2026-01-18**, Python 3.10–3.14. Voice extra exists (`pip install discord.py-self[voice]`). Drop-in API-compatible with discord.py so any tutorial on the planet applies. [PyPI](https://pypi.org/project/discord.py-self/), [GitHub](https://github.com/dolfies/discord.py-self).
- **`selfcord.py`** — v1.0.3 on 2025-10-19, smaller community but a viable fallback. [PyPI](https://pypi.org/project/selfcord.py/).
- **`discum`** — deprecated by its own maintainer, who explicitly redirects users to `discord.py-self`. [PyPI](https://pypi.org/project/discum/).

Rust (`serenity`, `twilight`), C# (`Discord.Net`, `DSharpPlus`), and C++ (`D++`) are **all bot-token-only by design**. None parse the user `READY` payload, none know the undocumented user-only routes (super-properties header, friend-source flags, channel ordering), and none have voice tested on a user account in production. `discord.py-self` already handles the X-Super-Properties base64 blob, user IDENTIFY, voice gateway v4/v8, lazy guild subscriptions, and the `aead_xchacha20_poly1305_rtpsize` Opus mode Discord rolled to in 2024. Rolling that yourself is **weeks of pcap-staring**.

## 2. Voice — honest assessment

`discord.py-self`'s `VoiceClient` works for **send** (mic in, audio out) on user accounts — the well-trodden path. PyNaCl wraps libsodium for SRTP; Opus loads from a bundled `libopus` DLL. The framework loop fires into native code every 20 ms, so CPython only runs a few hundred times per second per voice connection — fine.

**Voice receive** for selfbots is grayer; `discord-ext-voice-recv` is upstream-targeted at real bots, and you may need a small patch. For this project (single user wants to *talk*, not record everyone), send-only is enough and is solid. Opus is **never** in pure Python here — PyNaCl + libopus do the work in C. The "Python is slow at audio" worry doesn't apply.

## 3. GUI choice — PySide6 + QSystemTrayIcon, no contest

Surveyed for *this use case* (Windows, tray-resident, server/channel tree, idle near 0% while a game runs):

- **DearPyGui** — GPU rendering on the *same GPU as the game*. Plus [issue #2487](https://github.com/hoffstadt/DearPyGui/issues/2487) documents excessive idle memory. Wrong tool.
- **Tkinter** — built-in, ugly. Acceptable Plan B if you want zero extra deps.
- **Flet** — Flutter runtime, multi-platform overkill.
- **pywebview + WebView2** — sub-10 MB ([benchmarks](https://johal.in/pywebview-python-tiny-electron-cef-alternative-cross-platform-2025/)), HTML/CSS tree, but you write a JS bridge. Viable.
- **PySide6** — ~40 MB on disk after Nuitka prune, but `QSystemTrayIcon` is **event-driven and idles at ~0% on the Win32 message pump**. Hide to tray, the loop sleeps.

**Pick: PySide6** + `QTreeView` for servers/channels + `QSystemTrayIcon`. LGPL, official wheels, native Win32 widgets so it disappears into Windows 11. Disk cost is the price; idle-CPU is the prize.

## 4. TLS fingerprint mimicry — `curl_cffi` is Python's unfair advantage

[`curl_cffi`](https://github.com/lexiforest/curl_cffi) (5.6k stars, **v0.15.1b1 in April 2026**, 37 preset fingerprints) wraps `curl-impersonate`. The whole "browser TLS" problem collapses to:

```text
from curl_cffi import requests
r = requests.get("https://discord.com/api/v10/users/@me", impersonate="chrome")
```

JA3, JA4, HTTP/2 SETTINGS frame, HTTP/2 priority frame, ALPN order, extension order — all match a real Chrome. **And it has native WebSocket support** (sync + async), which means the gateway connection inherits the same TLS fingerprint. That's the entire `BLOCKER-fingerprinting-and-detection.md` story solved with one dependency.

Equivalents:
- Rust: `rquest` (good, but you wire the WS yourself on top).
- C#: there is **no first-class library**. You shell out to a `curl-impersonate` binary or hand-build BoringSSL bindings. This is a multi-week project in C#.
- C++: link `curl-impersonate` directly — works, but every API call is hand-rolled.

Python wins this category by an embarrassing margin.

## 5. Idle CPU profile — honest numbers

A `discord.py-self` client with no work to do is one asyncio coroutine sleeping on `await ws.recv()` plus a heartbeat every ~41 s. CPython 3.13 stock + asyncio: heartbeat is ~1 ms of CPU every 41 s — well under 0.003% of one core. Mic muted, no voice connection: effectively zero CPU between heartbeats. Mic open, voice up, talking: ~1–3% of one core for Opus encode (native), gateway, jitter buffer — **same order of magnitude as a Rust client doing the same work**, since libopus and libsodium are the bottleneck and both are C. [Python 3.13 free-threading](https://docs.python.org/3/howto/free-threading-python.html) is irrelevant here (doesn't speed up asyncio, adds 1–8% single-thread overhead). Use the stock GIL build. Yes Rust would idle slightly lower — we're arguing 0.01% vs 0.1% of one core while the user's game eats 95% of eight. **It does not matter.**

## 6. Packaging — Nuitka, not PyInstaller

[Nuitka](https://nuitka.net/) transpiles the whole dependency tree to C, then to a real native executable: `nuitka --onefile --enable-plugin=pyside6 --windows-console-mode=disable main.py`. Expected output **25–35 MB single exe**, ~400 ms cold start, no Python install on target. PyInstaller produces smaller artifacts but trips more AV false positives because the interpreter is visibly bundled — Nuitka's native code doesn't reflexively flag as "Python+unknown". Code signing: standard `signtool`. Autostart: one registry write to `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.

## 7. Token storage — DPAPI in one line

```text
import keyring
keyring.set_password("voice-only-discord", "token", token)
```

[`keyring`](https://pypi.org/project/keyring/) on Windows uses Credential Manager which is backed by DPAPI scoped to the user SID. Per the [johal.in 2025 benchmarks](https://johal.in/python-keyring-backends-secretservice-windows-credential-manager-support-2025/), retrieve latency is ~0.7 ms. If you want the raw DPAPI primitive (no Credential Manager indirection), `pywin32`'s `win32crypt.CryptProtectData(blob, None, None, None, None, 0)` is two lines.

No `LANG-rust.md` story is cleaner than `keyring.set_password(...)`.

## 8. Dev experience — Python's home turf

For a single-dev hobby project: REPL inspection of any gateway payload (`await client.fetch_me()` in `python -m asyncio`), ~600 ms cold-restart iteration loop vs Rust's 15–60 s cargo rebuild on a touched dep, `breakpoint()` in any handler, and a 1,500-line readable `voice_client.py` you can patch in-place when Discord changes a super-properties string. In a hand-rolled Rust/C++ client, **you** are the maintainer when Discord shifts the protocol; with `discord.py-self`, an upstream patch arrives in a week.

## 9. Why Python beats the others, specifically

**vs Rust:** `discord.py-self` exists. `serenity-self` and `twilight-self` do not. You can spend two weeks writing a user-mode gateway in Rust to get a tighter binary, or one evening in Python to have a working voice client. The only place Rust wins is binary size (5 MB vs 30 MB), which is meaningless on a 1 TB gaming SSD. Rust's `rquest` doesn't match `curl_cffi`'s WebSocket-inherits-fingerprint trick out of the box.

**vs C++:** D++ does not support user accounts. Period. You'd be writing the gateway and voice from scratch using `libcurl-impersonate`, `libsodium`, `libopus`, and Qt. That is a **months-long project** for the same end product. For a single dev who wants to *talk* in voice chat, this is comically wrong.

**vs C#:** C# has good tooling (Visual Studio, NAudio, WPF, native AOT) but **zero selfbot library tradition** — `Discord.Net` actively rejects user-token PRs. You also have no `curl_cffi` equivalent in the .NET ecosystem; you'd shim curl-impersonate over P/Invoke. The AOT story is nice in theory but bot-token-locked libraries make it moot.

## 10. Where Python concedes — honestly

- **Idle RAM: ~60–100 MB** with PySide6 loaded. Rust/C++/C# AOT can do 20–30 MB. On a 16 GB gaming laptop this disappears in noise; on an 8 GB machine it might matter.
- **Startup time: 300–500 ms** for stock CPython, ~400 ms for Nuitka build. Rust does 30 ms. For a tray app started once at login, irrelevant.
- **Single-file distribution.** Nuitka onefile works but produces a self-extracting binary (~30 MB extracts to ~80 MB temp on first run). Rust/C++ static binaries are cleaner.
- **AV false positives.** Bundled Python sometimes pings Windows Defender heuristics. Nuitka helps; code signing helps more.
- **Pure-Python CPU.** Opus encode in pure Python would melt a core. We **don't do that** — PyNaCl + system libopus do it natively. The seam is fine.
- **Voice receive on selfbots is unofficial**, but we don't need it for "click to join and talk".

If you absolutely need ≤30 MB RAM and ≤50 ms cold start, pick Rust. Otherwise: Python.

---

## Proposed package stack

```text
discord.py-self[voice]==2.1.0     # selfbot gateway + voice send (PyNaCl pulled in)
curl_cffi>=0.15                   # Chrome-impersonating HTTP + WebSocket
PySide6>=6.7                      # GUI + QSystemTrayIcon
pystray>=0.19.5                   # fallback tray (if not using QSystemTrayIcon)
keyring>=25                       # DPAPI-backed token storage on Windows
pywin32>=306                      # autostart registry, optional raw DPAPI
sounddevice>=0.4.7                # WASAPI mic input (low-latency)
nuitka>=2.5                       # build-time only: compile to single .exe
```

Build command:
```text
python -m nuitka --onefile --enable-plugin=pyside6 --windows-console-mode=disable main.py
```

Target: ~30 MB exe, ~80 MB resident, <0.1% CPU idle, <3% CPU on one voice connection. Built in a weekend.

---

## Citations

- `discord.py-self` v2.1.0, 2026-01-18, Python 3.10–3.14, 1.2k stars: https://pypi.org/project/discord.py-self/ , https://github.com/dolfies/discord.py-self
- `selfcord.py` v1.0.3, 2025-10-19: https://pypi.org/project/selfcord.py/
- `discum` deprecation (redirects to discord.py-self): https://github.com/Merubokkusu/Discord-S.C.U.M
- `curl_cffi` v0.15.1b1, Apr 2026, 5.6k stars, async WebSocket: https://github.com/lexiforest/curl_cffi
- `PyNaCl`: https://pypi.org/project/PyNaCl/
- `PySide6`: https://pypi.org/project/PySide6/
- `pystray` v0.19.5: https://pypi.org/project/pystray/
- `keyring` (Windows Credential Manager / DPAPI backend): https://github.com/jaraco/keyring , benchmarks https://johal.in/python-keyring-backends-secretservice-windows-credential-manager-support-2025/
- `pywin32`: https://pypi.org/project/pywin32/
- `Nuitka`: https://nuitka.net/ , vs PyInstaller: https://coderslegacy.com/nuitka-vs-pyinstaller/
- Python 3.13 free-threading (1–8% single-thread overhead, no asyncio benefit): https://docs.python.org/3/howto/free-threading-python.html , https://codspeed.io/blog/state-of-python-3-13-performance-free-threading
- DearPyGui idle memory issue: https://github.com/hoffstadt/DearPyGui/issues/2487
- pywebview benchmarks: https://johal.in/pywebview-python-tiny-electron-cef-alternative-cross-platform-2025/
- Reference Discord client `abaddon` (C++): https://github.com/uowuo/abaddon

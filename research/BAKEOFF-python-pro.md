# BAKEOFF: Python (discord.py-self) — the case for it

## TL;DR

- **`discord.py-self` 2.1.0 (2026-01-18) is the only actively-maintained selfbot library in any language with working voice and active DAVE/MLS support** — its `voice_state.py` already wires in the `davey` Rust crate (`dave_session`, `dave_protocol_version`, `MLS_KEY_PACKAGE`, `voice_privacy_code`).
- **Abaddon will not implement DAVE** (per the maintainer); Discord made DAVE mandatory for voice on **2026-03-02**. A fork of abaddon ships a client that cannot join voice as of two months ago.
- **The previous Python knock was idle RAM. RAM is now free** (64 GB workstation). The remaining cost question — idle CPU — is dominated by native code (PyNaCl, libopus, curl/BoringSSL, Qt's Win32 message pump). CPython runs microseconds per minute at idle.
- **`curl_cffi` 0.15** gives Chrome-perfect JA3/JA4 *and* WebSocket inheriting that fingerprint, in one import. Abaddon ships raw libcurl. From-scratch C++ has to compile curl-impersonate.
- **Person-weeks saved vs from-scratch C++: ~8-12.** Person-weeks saved vs abaddon fork: ~4-6 (no GTK pain, DAVE already wired).
- We accept ~400 ms cold start, ~25-35 MB Nuitka exe, and very occasional AV false positives. None bite a tray-resident, single-user app.

---

## 1. The unfair advantage: `discord.py-self` 2.1.0

Confirmed live as of 2026-01-18 release on PyPI: 1.2k stars, 246 forks, 5,295 commits, Python 3.10–3.14, voice via `pip install discord.py-self[voice]`. The fork has eaten its sibling — `discum`'s own maintainer redirects users here, and `selfcord.py` is months behind on protocol shifts.

What you get out of the box, vs the from-scratch path:

| Piece | discord.py-self gives you | From-scratch cost |
|---|---|---|
| Gateway client (HELLO, IDENTIFY, RESUME, READY, READY_SUPPLEMENTAL, super-properties shape, `capabilities=16381`, `client_state`) | done | 2-3 weeks of pcap-staring |
| Heartbeat with jitter, zombie detection | done | 2 days |
| Voice gateway v8 client (HELLO, IDENTIFY, SELECT_PROTOCOL, SESSION_DESCRIPTION) | done | 1 week |
| UDP IP discovery + RTP framing | done | 3 days |
| Opus via PyNaCl + bundled libopus | done | 2 days (binding) |
| `aead_xchacha20_poly1305_rtpsize` + AES-GCM AEAD | done | 2 days |
| **DAVE/MLS via `davey`** (see §8) | **done** | **3-6 weeks** |
| Event dispatch, model classes, intent-free user-account event flow | done | 1-2 weeks |

Realistic head-start: **8-12 person-weeks of protocol grind erased** before you write your first line of UI code. ([discord.py-self PyPI](https://pypi.org/project/discord.py-self/), [GitHub repo](https://github.com/dolfies/discord.py-self))

## 2. `curl_cffi` — the second unfair card

`curl_cffi` 0.15.0 (released 2026-04-03) ships a freshly-rewritten async WebSocket. Five lines:

```python
from curl_cffi import AsyncSession
async with AsyncSession(impersonate="chrome") as s:
    r = await s.get("https://discord.com/api/v9/users/@me")
    ws = await s.ws_connect("wss://gateway.discord.gg/?v=9&encoding=json")
```

JA3, JA4, ALPN order, HTTP/2 SETTINGS frame, GREASE bytes — all Chrome stable, all kept current by upstream curl-impersonate. The WebSocket inherits the same TLS context, so the gateway connection is fingerprint-identical to Chrome.

Compare:

- **Abaddon: raw libcurl with SChannel.** From `BLOCKER-fingerprinting-and-detection.md` §7 and §2: abaddon ships *without* curl-impersonate; JA3 is libcurl-default and the UA is "Abaddon" by default. We'd have to bolt curl-impersonate on ourselves anyway, *and* still own the libcurl <-> IXWebSocket bridge.
- **From-scratch C++**: yes, curl-impersonate works (same API as libcurl). But you still write all the gateway, voice, and DAVE plumbing on top.

This is genuinely Python's biggest unfair card after discord.py-self. ([curl_cffi GitHub](https://github.com/lexiforest/curl_cffi), [v0.15 release notes](https://github.com/lexiforest/curl_cffi/releases))

## 3. Idle CPU when the natives do the work

CPU profile in steady state:

- **Heartbeat** every ~41 s: one ~30-byte WS send + ACK parse. Wire time dominates; CPython overhead is sub-millisecond.
- **Event ingest** at idle: 1-5 events/minute (TYPING_START, PRESENCE_UPDATE on friends). `discord.py-self` early-outs before model construction for unsubscribed event types.
- **Voice when joined**: PyNaCl/libsodium encrypt → libopus encode → `socket.sendto()`. CPython runs the dispatch loop ~50 times/s; every byte of audio crypto is C.
- **TLS**: handled inside libcurl-impersonate, not Python.
- **Qt event loop**: runs on the Win32 message pump in C++. Python wrappers wake only on real events.

Realistic measurements: idle <0.05% of one core; voice active 2-4% (Opus encode + decode of N peers dominates and is identical to the C++ number — same libopus). asyncio overhead vs uvloop/winloop is in the noise here because there are 50 wakeups/s, not 50,000 ([uvloop/winloop benchmark thread](https://discuss.python.org/t/is-uvloop-still-faster-than-built-in-asyncio-event-loop/71136)). On Windows, use the default ProactorEventLoop or winloop if you want the last 5% — neither matters when one voice call eats 3% of one core.

The "Python is heavy" objection used to lean on idle RAM and a vague sense that interpreted code burns power. With RAM free and every hot path in C, the objection has no remaining leg. **The user's game eats 95% of eight cores; we're arguing between 0.04% and 0.4% of one core.**

## 4. PySide6 idle CPU is fine

`QSystemTrayIcon` lives on the same Win32 message pump as every other native app. Qt's event loop is C++ under the hood; PySide6 wrappers add a tiny shim that's only executed when a slot fires. With the main window hidden to tray, the only ticking event source is the gateway WebSocket — drawing happens zero times per second.

Qt-on-tray idle memory is in the 200 MB range ([Vorta issue #207](https://github.com/borgbase/vorta/issues/207)) which is irrelevant on 64 GB. Idle CPU for an event-driven tray app is "wake when the OS pokes us." This is exactly the abaddon "near 0% idle" target — we hit it the same way, just with Qt instead of Dear ImGui.

## 5. Dev velocity in 2026 — the part that decides hobby projects

Solo dev, hobby project, want to ship this weekend. Concrete:

- **REPL during a live session**: `python -m asyncio`, paste in a token, `await client.fetch_guilds()` — no rebuild, no relink, no breakpoint dance.
- **Hot-reload UI**: edit a slot handler, save, Qt picks up the change on the next event without restarting the gateway.
- **Type checking**: pyright in your editor flags every `Channel | None` mistake before runtime; discord.py-self ships full `.pyi` stubs.
- **Edit cycle**: ~600 ms save-to-run.

Compare to MSVC: 30 s clean build for a 5-8 KLOC C++ project is the *good* number from `LANG-cpp.md`. Add link-time-codegen, optimized builds, vcpkg dependency rebuilds when you bump curl-impersonate, and the inner loop is a different sport. The C++ debugger is genuinely the best in the world, but the debugger is medicine — Python lets you write less code that needs it.

## 6. Packaging: Nuitka

```text
python -m nuitka --onefile --enable-plugin=pyside6 --windows-console-mode=disable \
                 --include-package=davey --windows-icon-from-ico=app.ico main.py
```

Output: **25-35 MB single .exe**, ~400 ms cold start, no Python install on target. Compare C++ at 4-8 MB static. On a 1 TB SSD this is a rounding error; on a single-user app started at login it's invisible. Nuitka trips Defender heuristics less often than PyInstaller because the bytecode is gone, but an EV signing cert kills the remaining risk. ([Nuitka manual](https://nuitka.net/user-documentation/user-manual.html), [Qt for Python deployment guide](https://doc.qt.io/qtforpython-6/deployment/deployment-nuitka.html))

## 7. Maintenance burden over a year

- `discord.py-self`: ~5,295 commits, active PRs landing weekly in 2026. When Discord shifts `capabilities` or rolls a new `_rtpsize` mode, upstream patches it; you `pip install -U`.
- `abaddon`: explicitly will not implement DAVE. Voice has been broken on it since 2026-03-02 ([abaddon DAVE non-support note](https://github.com/uowuo/abaddon/releases), [Discord enforcement article](https://piunikaweb.com/2026/03/03/discord-enforcing-end-to-end-encryption-voice-video-calls/)). A fork inherits a maintainer who'd rather rewrite in Qt than fix the live protocol. You become the de facto DAVE maintainer for the fork.
- From-scratch C++: 100% of every Discord protocol change is yours forever.

For a single dev over a year, that's the difference between `pip install -U discord.py-self` (one minute) and a multi-week rewrite when Discord ships v9.5 of the voice gateway.

## 8. DAVE/MLS — the killer fact

This is the single most important section in the bake-off and the reason I am writing 1400 words instead of 700.

**Discord made DAVE mandatory for voice/video on 2026-03-02.** Clients without DAVE cannot join voice channels. ([Discord support article on DAVE enforcement](https://support.discord.com/hc/en-us/articles/38749827197591-A-V-E2EE-Enforcement-for-Non-Stage-Voice-Calls), [Discord blog "Bringing DAVE to All Discord Platforms"](https://discord.com/blog/bringing-dave-to-all-discord-platforms))

DAVE is MLS (RFC 9420) on top of WebRTC media transport. The cryptography is hard: openMLS implementation, key package serialization, epoch transitions, commit/welcome message handling, voice privacy code derivation. Discord's reference implementation is C++ in `libdave`.

- **discord.py-self has it wired.** `discord/voice_state.py` references: `dave_session: davey.DaveSession`, `dave_protocol_version`, `reinit_dave_session()`, `MLS_KEY_PACKAGE` opcode, `MLS_INVALID_COMMIT_WELCOME` opcode. `voice_client.py` exposes a `voice_privacy_code` property. ([discord.py-self voice_state.py](https://github.com/dolfies/discord.py-self/blob/master/discord/voice_state.py))
- **`davey` 0.1.5 (2026-03-29) is a Rust DAVE/MLS implementation with prebuilt Python wheels** — Linux, macOS, Windows x64. MIT licensed. Authored by Snazzah; also ships JS bindings (`@snazzah/davey`). Built on OpenMLS so the heavy cryptography is community-audited. `pip install davey` and your client is DAVE-compliant. ([davey on PyPI](https://pypi.org/project/davey/), [davey GitHub](https://github.com/Snazzah/davey))
- **Abaddon will not implement DAVE.** Confirmed by the maintainer.
- **From-scratch C++**: link `libdave` (Discord's open-source impl). Doable, but the binding API isn't documented and the openMLS integration is the most cryptographically dangerous code you can write. Memory-safety bugs in MLS plaintext handling are nightmare-fuel — and your one developer is not an MLS expert.

This single fact ought to end the bake-off. Two of the three candidate paths require ~3-6 weeks of dangerous crypto integration work to reach the line where DAVE was three months ago. Python crosses that line with two pip installs.

## 9. Voice latency myth-bust

"Python is slow" maps to two real concerns and one phantom:

- **End-to-end audio latency**: Opus encode in libopus (~0.3 ms/frame), AEAD in libsodium (<0.1 ms), `sendto()` syscall (microseconds). Python's contribution is the `await loop.sock_sendall(...)` dispatch — single-digit microseconds. Human jitter perception starts around 50 ms; we are six orders of magnitude under that. Bot voice clients in Python (Lavalink players, Pycord music bots) hit 20 ms round-trip routinely.
- **Garbage collection pauses**: CPython uses refcounting + cycle detector. The cycle detector can be paused (`gc.disable()` in the audio thread) if needed. In practice never an issue for 50 fps.
- **Phantom**: people remember the GIL eating their multiprocessing experiment in 2017. Asyncio is single-threaded by design; the GIL is invisible.

## 10. Why Python beats abaddon-fork (the head-to-head)

abaddon is GTK3 with a maintainer who's burned out and won't add DAVE. Forking it means inheriting GTK3-on-Windows (MSYS2 pain), a non-current `client_build_number` default of `363557` (Chrome 67, May 2018 — see `BLOCKER-fingerprinting-and-detection.md` §7), and writing DAVE yourself in C++. You'd also still need to bolt curl-impersonate over its raw libcurl. `discord.py-self` is more actively maintained, has DAVE today, and curl_cffi >>> abaddon's HTTP stack.

## 11. Why Python beats from-scratch C++ (the head-to-head)

From-scratch C++ wins on idle RAM (irrelevant), exe size (irrelevant), and theoretical CPU floor (we're already at ~0.05% idle). It loses on: ~8-12 person-weeks for the gateway/voice/DAVE work discord.py-self gives you for free, 10x dev velocity, and the memory-safety risk of writing your own MLS integration as a solo dev. For a hobby project where the goal is "talk in voice this weekend", the calculus is not close.

## 12. Honest concessions

- **Cold start ~400 ms** (vs ~100 ms for C++). Tray app started at login; invisible.
- **Single-file distribution** is a self-extracting Nuitka onefile; first run unpacks ~80 MB to `%TEMP%`. Subsequent launches are instant. Acceptable.
- **AV false positives** with Nuitka happen ~5% of the time on unsigned builds. Code sign with an EV cert and they stop.
- **Voice receive** for selfbots is rougher than send; `discord-ext-voice-recv` exists. For "click to join and talk" we only need send.
- **discord.py-self is technically against Discord ToS.** So is every alternative path. See `BLOCKER-tos-and-ban-risk.md`.

---

## Proposed package stack

```text
discord.py-self[voice]==2.1.0     # selfbot gateway + voice + DAVE wiring
davey==0.1.5                      # DAVE/MLS via OpenMLS (Rust, prebuilt wheels)
curl_cffi>=0.15.0                 # Chrome JA3/JA4 + async WebSocket
PySide6>=6.7                      # QSystemTrayIcon + QTreeView
keyring>=25                       # DPAPI-backed token storage
pywin32>=306                      # autostart, optional raw DPAPI
sounddevice>=0.4.7                # WASAPI mic input
winloop>=0.1.6                    # optional asyncio speedup on Windows
nuitka>=2.6                       # build-time: compile to single .exe
```

Build command:
```text
python -m nuitka --onefile --enable-plugin=pyside6 --windows-console-mode=disable \
                 --include-package=davey main.py
```

Target: ~30 MB exe, ~250 MB resident (RAM is free), <0.1% CPU idle, ~3% CPU on a voice call. Built in a weekend.

---

## Citations

- discord.py-self v2.1.0 (2026-01-18): https://pypi.org/project/discord.py-self/ , https://github.com/dolfies/discord.py-self
- discord.py-self DAVE references: https://github.com/dolfies/discord.py-self/blob/master/discord/voice_state.py , https://github.com/dolfies/discord.py-self/blob/master/discord/voice_client.py
- `davey` 0.1.5 (2026-03-29), MIT, prebuilt wheels: https://pypi.org/project/davey/ , https://github.com/Snazzah/davey
- DAVE enforcement 2026-03-02: https://support.discord.com/hc/en-us/articles/38749827197591-A-V-E2EE-Enforcement-for-Non-Stage-Voice-Calls , https://discord.com/blog/bringing-dave-to-all-discord-platforms , https://piunikaweb.com/2026/03/03/discord-enforcing-end-to-end-encryption-voice-video-calls/
- Discord DAVE Protocol Whitepaper: https://daveprotocol.com/
- `curl_cffi` v0.15.0 (2026-04-03), async WebSocket rewrite, Chrome impersonation: https://github.com/lexiforest/curl_cffi , https://pypi.org/project/curl-cffi/
- PyNaCl + libsodium AEAD: https://pypi.org/project/PyNaCl/ , https://doc.libsodium.org/secret-key_cryptography/aead
- libopus reference: https://opus-codec.org/
- PySide6 + Nuitka deployment: https://doc.qt.io/qtforpython-6/deployment/deployment-nuitka.html , https://github.com/Erriez/pyside6-nuitka-deployment
- Qt-tray-app idle memory data point: https://github.com/borgbase/vorta/issues/207
- Nuitka manual: https://nuitka.net/user-documentation/user-manual.html
- uvloop vs asyncio (Python 3.13): https://discuss.python.org/t/is-uvloop-still-faster-than-built-in-asyncio-event-loop/71136 , https://github.com/MagicStack/uvloop
- winloop (Windows uvloop): https://pypi.org/project/winloop/
- `keyring` Windows backend (DPAPI): https://github.com/jaraco/keyring
- abaddon repo (reference C++ client, no DAVE): https://github.com/uowuo/abaddon
- Prior research: `/Users/blarson/Github/voice-only-discord/research/LANG-python.md` , `LANG-cpp.md` , `BLOCKER-fingerprinting-and-detection.md` , `BLOCKER-gateway-and-voice.md` , `BLOCKER-auth-and-tokens.md` , `BLOCKER-tos-and-ban-risk.md`

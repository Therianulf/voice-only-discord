# BAKEOFF: The Case **Against** a New Python Client (discord.py-self + PySide6)

*Skeptic brief. Three paths on the table: (A) fork abaddon, (B) new C++ from scratch, (C) new Python from scratch on discord.py-self. This document argues path C is **probably the worst of the three** for this specific project — a low-CPU, voice-only Discord client running alongside a game on a Windows laptop.*

## TL;DR

Python is the worst path because: **(1) the DAVE/MLS deadline is now and discord.py-self maintainers closed both DAVE-tracking issues as "Not planned"** (#901 closed 2026-03-22, #917 closed 2026-05-21) — your voice client is on a countdown to gateway op 4017 with no upstream plan; **(2) discord.py-self is the most recognizable selfbot library on the network** and any traffic that quacks like a known selfbot lib raises ban risk in a way abaddon (5+ years of unchanged traffic patterns) and a from-scratch C++ client (fingerprint-anonymous) do not; **(3) asyncio+PySide6 cannot match `MsgWaitForMultipleObjectsEx` for the literal "zero CPU between events" floor we want while the user is gaming**; **(4) the library is 90% dead weight we can't remove without forking it ourselves** — at which point we're maintaining a selfbot fork in a language with no Discord protocol experts to lean on. The RAM constraint being lifted does not fix any of these — they are all CPU, ban-risk, or maintenance failure modes.

---

## Risk table (severity ranked)

| # | Risk | Severity | abaddon-fork | C++ scratch | Python (this path) |
|---|---|---|---|---|---|
| 1 | **DAVE/MLS deadline (op 4017 disconnects already happening 2026-05)** | Critical | Has libdave wired in | Static-link libdave | **Upstream "Not planned"** (#901, #917) — bolt on `davey`/`dave.py` (v0.1.x, March 2026, "no documentation to speak of") |
| 2 | **Selfbot-library traffic fingerprint = enforcement target** | High | Web-client mimic, 5+ yr corpus | Anonymous traffic | **Most-recognizable selfbot lib name on PyPI** |
| 3 | **asyncio idle-CPU floor on Windows** | Medium-High | Native blocking wait, ~0% | Native blocking wait, ~0% | ProactorEventLoop wakes ~15.6 ms tick min; GIL contention with PySide6 |
| 4 | **Library bloat we can't remove** | High | Lift only files we need | Write only what we need | discord.py-self pulls everything; pruning = fork |
| 5 | **PyNaCl + opuslib + discord.py-self voice instability** | High | Direct libsodium/libopus | Direct libsodium/libopus | Open #870 4006-storm, voice in voice_client.py is the most-reported area |
| 6 | **GIL contention during voice + GUI + WS** | Medium | N/A | N/A | Real; encode holds GIL during pure-Python framing |
| 7 | **Maintainer single point of failure** | High | MIT, fork-able | You are the maintainer | One person; `discum` precedent shows self-deprecation is real |
| 8 | **PySide6 cold-start CPU spike** | Low-Medium | C++ Qt or ImGui | ImGui | Reported 1–3 s on Linux; 0.5–1 s on Windows |
| 9 | **Nuitka + PySide6 build complexity / Defender false positives** | Medium | MSVC + signtool | MSVC + signtool | Wacapew/Wacatac flags documented; commercial Nuitka recommended |
| 10 | **No DAVE/MLS protocol experts in Python** | High | abaddon already did it | Self-managed | `davey` is one experimental package; you're alone |

---

## 1. discord.py-self is targeted, identifiable, and a known-bad-traffic source

`BLOCKER-tos-and-ban-risk.md` is explicit: Discord enforces on **traffic patterns and behavior**, not on language choice. The relevant question is therefore "does our traffic look like a known selfbot stack?" — and `discord.py-self` is the most recognizable Python selfbot library on the network. From `BLOCKER-tos-and-ban-risk.md`: "Self-bot libraries (discum, discord.py-self): terminate accounts regularly — but bans correlate with automation behavior."

`discord.py-self`'s own [hCaptcha discussion #838](https://github.com/dolfies/discord.py-self/discussions/838) catalogues the exact pattern: captcha walls for fresh tokens, datacenter ASNs, and the library's own traffic shape. The library wears a known **user-agent string default**, has known IDENTIFY ordering, and known REST-bucket cadence. Compare to **abaddon** (5 years, ~3 000 users, established as "background noise" in Discord's anti-abuse model — explicitly tolerated per zorkian's HN comment) and **from-scratch C++** (fingerprint-anonymous — you become a single user with the right `X-Super-Properties` and zero history).

The `discum` precedent matters: a once-popular Python selfbot library that **self-deprecated** and now redirects users to discord.py-self. Whatever caused that abandonment (maintainer burnout, ban-rate, ToS pressure) is a reasonable prior on the next selfbot lib that becomes the obvious target.

## 2. asyncio on Windows is **not** a zero-wakeup loop

`DESIGN-minimal-native.md` makes the core architectural claim: `MsgWaitForMultipleObjectsEx(handles, INFINITE)` with two `WSAEventSelect` handles plus the Win32 message queue parks the thread until something happens — **0% CPU when idle**. That is the structural advantage of native code on Windows for this workload.

CPython's `asyncio.ProactorEventLoop` cannot match this. Windows clock resolution is **~15.6 ms** ([CPython issue #87079](https://github.com/python/cpython/issues/87079)) — every `loop.call_later(timeout)` resolves to a 15.6 ms IOCP wait that returns and re-enters the loop. Even a well-behaved asyncio program ticks. The [urwid `AsyncioEventLoop` regression #90](https://github.com/urwid/urwid/issues/90) documents "5–10% CPU usage" when polling defaults are wrong; tunable but not zero. The LANG-python.md advocate is right that *aggregate* CPU is small in absolute terms, but the floor is the wrong shape: a periodic poll while gaming is exactly the cache-line displacement that drops a few frames at thermal throttle.

PySide6's QApplication adds a second event loop pumped via `asyncqt`/`qasync` bridges. Two reactors talking through a queue is two wake-ups, not one.

## 3. discord.py-self is overwhelmingly dead weight for "servers + voice"

Per `BLOCKER-gateway-and-voice.md`, what we actually need: gateway WS, READY/GUILD_CREATE parsing, OP 4 voice state, voice WS, UDP RTP + AEAD, libopus, libsodium, presence "invisible". That is approximately **the voice subset of `voice_client.py` plus a small `gateway.py`**.

What `discord.py-self` ships: message caching (`Messageable`), member cache (`MemberCacheFlags`), embed parsing, attachment/file objects, thread/forum support, slash command interaction, presence subsystem, REST rate-limit bucket router, audit-log scrapers, friend system, DM channels, sticker/emoji handling, full `BaseUser`/`ClientUser` profile editing, application/team objects, scheduled events, stage instances. By any honest count, **>80% of the library is code we cannot delete without forking**. Even if it idles quietly, every `MESSAGE_CREATE` event is parsed into a `Message` object before our handler can drop it — that's continuous allocation churn while the user is in a chatty server. `BLOCKER-gateway-and-voice.md` §1.6 says: "keep `d` as a raw JSON slice and only parse when `t` is whitelisted." discord.py-self does the opposite by design.

## 4. PyNaCl + opuslib + the discord.py-self voice stack is the buggiest area

discord.py-self issue [#870 — "Voice channel websocket closed with 4006 in most region"](https://github.com/dolfies/discord.py-self/issues/870) is open and unconfirmed: bot connects, handshake completes, voice WS dies seconds later with `4006 SessionNoLongerValid`. It references a parallel discord.py issue [#10207 "Error 4006 causing bot to repeatedly connect to vc and fail"](https://github.com/Rapptz/discord.py/issues/10207) and several others ([#10228](https://github.com/Rapptz/discord.py/issues/10228), [#10237](https://github.com/Rapptz/discord.py/issues/10237), [#9616](https://github.com/Rapptz/discord.py/issues/9616), [#9634](https://github.com/Rapptz/discord.py/issues/9634)). These are not "rough edges" — they are the load-bearing path for our single use case.

The advocate's claim that "voice send works on user accounts — the well-trodden path" is technically true but glosses the bug surface. PyNaCl itself is healthy ([PyNaCl 1.6.x](https://pypi.org/project/PyNaCl/), libsodium 1.0.20 pulled in 2025-12), and `opuslib` is a thin ctypes wrapper, **but** the discord.py-self voice client is the orchestration layer (handshake, IP discovery, session-description handling, mode negotiation, jitter) where everything goes wrong. abaddon's `voiceclient.cpp` has been working through these states for five years and is the relevant corpus to crib from — in C++.

## 5. DAVE/MLS in Python: upstream **"Not planned"**

This is the most damaging finding. As of the date of this brief:

- discord.py-self **[issue #901 — "Add support for DAVE protocol"](https://github.com/dolfies/discord.py-self/issues/901)**: closed **2026-03-22 as "Not planned"**, the day after Discord's enforcement deadline.
- discord.py-self **[issue #917 — "Voice connection fails with 4017 (E2EE/DAVE required) on Linux"](https://github.com/dolfies/discord.py-self/issues/917)**: closed **2026-05-21 as "Not planned"**.

Per `BLOCKER-gateway-and-voice.md` §5.1, ops 21–31 are DAVE/MLS; per the [Discord DAVE blog](https://discord.com/blog/bringing-dave-to-all-discord-platforms), clients without DAVE support are **disconnected from voice with close code 4017** after the March 2026 cutover. Reverse-engineered docs confirm this is enforced ([docs.discord.food/topics/voice-connections](https://docs.discord.food/topics/voice-connections)).

The only Python options are third-party experimental wrappers around libdave: **[`dave.py`](https://github.com/DisnakeDev/dave.py) v0.1.2 (2026-03-10)**, self-described as having no documentation, primarily intended for Disnake (a bot library, not selfbot), and **`davey` 0.1.0rc2** which is a release-candidate from a different author using OpenMLS. **Neither is integrated with discord.py-self's voice gateway state machine**. You would be the integrator — and since DAVE is "Not planned" upstream, you'd be carrying that patch forever or running a fork. At which point you have all the maintenance burden of an abaddon-fork or a C++ scratch project, in a language where libdave is C++ wrapped twice.

abaddon, by contrast, has `src/discord/dave.cpp` in-tree and statically links libdave. C++ scratch can `vcpkg install libdave` and link it natively in 50 lines.

## 6. PySide6 cold-start CPU is real

[PySide6 startup forum thread](https://forum.qt.io/topic/133093/extremely-slow-startup-time-for-pyside6-vs-pyside2) and [PYSIDE-2749 regression](https://bugreports.qt.io/projects/PYSIDE/issues/PYSIDE-2749) document 1–3 s cold start, with regressions across point releases. The advocate's "~400 ms cold start" is best-case. While the user is launching the gaming laptop at the start of a session, PySide6 has to enumerate icon themes, fonts, plugins, accessibility services on a thermally-cold CPU. ImGui/D3D11 is microseconds.

## 7. Nuitka + PySide6 + PyNaCl + curl_cffi is a build engineering project

[Nuitka issue #2685 — "Why does Windows Defender flag my application as malware?"](https://github.com/Nuitka/Nuitka/issues/2685) and [#2495 "Windows Defender blocks nuitka onefile exe"](https://github.com/Nuitka/Nuitka/issues/2495) document persistent Wacapew/Wacatac false positives, with Nuitka's own recommendation being **purchase the commercial plan**. [Nuitka #2690](https://github.com/Nuitka/Nuitka/issues/2690) shows PySide6 builds regressing across Nuitka point releases. Build times for `--onefile --enable-plugin=pyside6` with PyNaCl C extensions + curl_cffi's curl-impersonate vendored libs are **5–15 minutes per clean build**, vs `cmake --build .` for a static C++ exe in 30–60 s. Every dependency change re-runs the C compilation step.

## 8. The GIL still matters even when most work is native

The advocate is right that libopus and libsodium are C and run outside the GIL. But the *scheduling* code, the RTP header construction, the AEAD nonce counter, the gateway WS framing, the JSON parsing of `READY_SUPPLEMENTAL` (megabytes per `BLOCKER-gateway-and-voice.md` references), and every PySide6 signal/slot crossing **does** hold the GIL. While the laptop is thermally stressed running a game on the same socket, contention between the asyncio thread and the PySide6 UI thread is real. `LANG-python.md` explicitly rules out free-threaded Python 3.13/3.14 because asyncio doesn't benefit and single-thread overhead rises. So you're on stock CPython, with one core doing all the Python work, plus another thread doing the WASAPI callback. Not catastrophic, but not "C++-shape".

## 9. Maintainer single point of failure

Rapptz, the original discord.py maintainer, has been on record opposing selfbot support since [discord.py issue #1449](https://github.com/Rapptz/discord.py/issues/1449) — he won't merge user-account PRs upstream. The discord.py-self project is one person (dolfies) maintaining a fork against an upstream that doesn't want its changes. **`discum` precedent**: the previous selfbot library maintainer wrote "Will have less and less time to work on this project" and redirected users to discord.py-self. There is no second option. Compare:

- **abaddon-fork**: 25 contributors over 5 years, MIT-licensed corpus we control end-to-end.
- **C++ from scratch**: you are the maintainer, but the protocol you're implementing is documented in [docs.discord.food](https://docs.discord.food/), and the libdave/libopus/libsodium dependencies have actual Linux Foundation/security teams behind them.

## 10. Why the two C++ options beat Python here

**abaddon-fork beats Python because** abaddon already ships every hard piece (`voiceclient.cpp`, `dave.cpp` linking libdave, RTP/AEAD framing, IP discovery, voice WS state machine) **for user accounts on Windows** — five years of debugging the exact 4006/4017/4015 storms that are open in discord.py-self's tracker today. The bug surface is closed. We strip the GTK chat panel and ship.

**From-scratch C++ beats Python because** the constraint is "near-zero CPU on a thermally-stressed gaming laptop", which is bought by *structural* choices: blocking `MsgWaitForMultipleObjectsEx`, no managed-runtime tick, immediate-mode ImGui that doesn't render when minimized, statically-linked libopus with SSE intrinsics, libdave as a vcpkg dep, curl-impersonate as the libcurl drop-in. None of that exists in Python without lashing together five wrappers, each with its own scheduling tick and GIL handoff.

## 11. One honest concession

**Where Python genuinely wins: developer velocity to first prototype.** `pip install discord.py-self[voice]` + 200 lines = a thing that connects to a voice channel and plays audio in 1–2 evenings. abaddon-fork is 2–4 weeks (build environment + GTK strip + GUI port). C++ scratch is 1–3 months.

**Why it doesn't outweigh the rest:** the project is for **personal long-term use during gaming**, not a hackathon. A weekend prototype that gets disconnected by op 4017 in production, trips spam filters because its IDENTIFY shape is the most recognizable in Discord's ML dataset, and burns even 0.5% CPU during a CPU-bound game session has paid you back in *speed of failure*, not *speed to a thing that solves the problem*. The DAVE issue alone (closed "Not planned" upstream, May 2026) makes Python a path you have to fork or abandon within months.

---

## Citations

- discord.py-self issue **#870** — voice WS 4006 storm (open, unconfirmed): https://github.com/dolfies/discord.py-self/issues/870
- discord.py-self issue **#901** — Add DAVE protocol support, **closed Not planned 2026-03-22**: https://github.com/dolfies/discord.py-self/issues/901
- discord.py-self issue **#917** — 4017 (DAVE required) on Linux, **closed Not planned 2026-05-21**: https://github.com/dolfies/discord.py-self/issues/917
- discord.py-self **hCaptcha discussion #838** (selfbot detection cluster): https://github.com/dolfies/discord.py-self/discussions/838
- discord.py issue **#10207** — Error 4006 voice reconnect loop: https://github.com/Rapptz/discord.py/issues/10207
- discord.py issue **#10228** / **#10237** — same 4006 cluster: https://github.com/Rapptz/discord.py/issues/10228 , https://github.com/Rapptz/discord.py/issues/10237
- discord.py issue **#1449** — Rapptz's stance against selfbot doc/support: https://github.com/Rapptz/discord.py/issues/1449
- Pycord issue **#3135** — 4017 DAVE enforcement evidence: https://github.com/Pycord-Development/pycord/issues/3135
- `discum` deprecated in favor of discord.py-self: https://github.com/Merubokkusu/Discord-S.C.U.M , https://pypi.org/project/discum/
- CPython issue **#87079** — ProactorEventLoop signal/wakeup behavior: https://github.com/python/cpython/issues/87079
- urwid AsyncioEventLoop high idle CPU (5–10%) regression: https://github.com/urwid/urwid/issues/90
- Hacker News — overhead of asyncio Tasks: https://news.ycombinator.com/item?id=35073136
- PySide6 vs PySide2 startup time forum thread: https://forum.qt.io/topic/133093/extremely-slow-startup-time-for-pyside6-vs-pyside2
- PYSIDE-2749 6.6 → 6.7 performance regression: https://bugreports.qt.io/projects/PYSIDE/issues/PYSIDE-2749
- Nuitka issue **#2685** — Windows Defender flags Nuitka onefile as Wacapew/Wacatac: https://github.com/Nuitka/Nuitka/issues/2685
- Nuitka issue **#2495** — Defender blocks Nuitka onefile: https://github.com/Nuitka/Nuitka/issues/2495
- Nuitka issue **#2690** — PySide6 builds regressing across Nuitka versions: https://github.com/Nuitka/Nuitka/issues/2690
- DAVE protocol whitepaper / enforcement: https://daveprotocol.com/ , https://discord.com/blog/bringing-dave-to-all-discord-platforms
- discord-userdoccers — voice 4017 close code: https://docs.discord.food/topics/voice-connections
- `dave.py` v0.1.2 (March 2026, "no documentation to speak of"): https://github.com/DisnakeDev/dave.py
- `davey` 0.1.0rc2 (OpenMLS Python DAVE impl): https://pypi.org/project/davey/0.1.0rc2/
- discord/libdave (the C++ reference): https://github.com/discord/libdave
- PyNaCl 1.6.x + libsodium 1.0.20: https://pypi.org/project/PyNaCl/ , https://pynacl.readthedocs.io/
- Microsoft Learn — `MsgWaitForMultipleObjectsEx`: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-msgwaitformultipleobjectsex
- Internal: `LANG-python.md`, `LANG-cpp.md`, `BLOCKER-gateway-and-voice.md`, `BLOCKER-fingerprinting-and-detection.md`, `BLOCKER-tos-and-ban-risk.md`, `DESIGN-minimal-native.md`

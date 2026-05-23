# BAKEOFF: The Case Against From-Scratch C++

*Skeptic brief. Path B (new C++ from scratch) vs Path A (fork abaddon) and Path C (new Python). B is the worst of the three for a solo dev who actually wants to ship.*

## TL;DR

- From-scratch C++ pays the **full protocol-reverse-engineering cost** (the part abaddon already absorbed) **and** the **full systems-programming cost** (the part Python skips).
- Itemized scope: **18–21 person-weeks** — 3–5 calendar months for a hobbyist at 10–15 hrs/wk.
- Throws away 4+ years of `client_build_number` / super-properties / capability-bitfield / READY_SUPPL scar tissue you'd re-acquire one disconnect at a time.
- Marginal CPU win over Python is **~0.05% of one core at idle** on a 64 GB / 8-core laptop. To save *that*: multi-month build, forever maintenance.
- Memory-unsafe C++ in token + crypto + RTP paths is an account-compromise risk Python and abaddon-fork largely sidestep.

---

## 1. Scope, itemized

One solo dev, no prior Discord-protocol work, against `BLOCKER-gateway-and-voice.md` + `BLOCKER-fingerprinting-and-detection.md`:

| Component | Wks |
|---|---|
| HTTPS REST + curl-impersonate | 1 |
| Gateway WS (zlib-stream + HELLO/IDENTIFY/READY/READY_SUPPL/heartbeat/RESUME) | 2 |
| Super-properties + build-number scraper | 0.5 |
| Guild/channel state (diff `GUILD_CREATE/*`, `CHANNEL_*`, `VOICE_STATE_UPDATE`) | 1 |
| Voice gateway WS (OP 0–13, IDENTIFY/SELECT_PROTOCOL/SESSION_DESCRIPTION/RESUME) | 1.5 |
| Voice UDP + RTP (IP discovery, header, nonce counter) | 1 |
| libsodium AEAD (`aead_aes256_gcm_rtpsize` + xchacha) | 0.5 |
| Opus pipeline (libopus + jitter buffer + optional rnnoise) | 1 |
| WASAPI (`IAudioClient3`, shared 10ms, device-change) | 1.5 |
| **libdave / MLS E2EE** (mlspp + OpenSSL/BoringSSL, P-256, AES-128-GCM) | **3–5** |
| DPAPI token + autostart | 0.25 |
| Dear ImGui + Win32 + D3D11 + tray | 2 |
| Build / packaging (CMake + vcpkg, Authenticode) | 1 |
| Fingerprint hardening (Sec-Fetch, X-Debug-Options, `/science` stub) | 0.5 |
| Bug-hunting vs live Discord (the iceberg) | 2–3 |
| **Total** | **18–21** |

Context: abaddon is **~30k LoC C++, 80+ files in `src/discord/`**, 1,373 commits — "the thing already written." ([abaddon](https://github.com/uowuo/abaddon))

## 2. The build-system tax

`pip install discord.py-self[voice] curl_cffi PySide6` is **one line, 90 seconds**. From-scratch C++ on Windows 2026 means CMake + vcpkg + MSVC with documented pain: CRT linkage `/MT` vs `/MD` ([#16049](https://github.com/microsoft/vcpkg/issues/16049)); debug/release lib selection silently picking the wrong `.lib` ([#30577](https://github.com/microsoft/vcpkg/issues/30577)); triplet inconsistency ([#15321](https://github.com/microsoft/vcpkg/issues/15321)); VS 2026 still open ([#47302](https://github.com/microsoft/vcpkg/issues/47302)). Budget: **0.5–1 week** of yak-shaving before hello-world links libsodium + libopus + libcurl-impersonate + ImGui statically. abaddon-fork dodges this; Python dodges it (no build).

## 3. libdave is not optional, and not cheap

DAVE became **mandatory 2026-03-01** — voice without it gets close-code 4017. libdave requires **mlspp**, **OpenSSL 1.1/3.0 or BoringSSL** via vcpkg, their own vcpkg submodule, and a Makefile-wrapping-CMake that reintroduces the dual-toolchain mess on Windows. Cost from-scratch: **3–5 weeks** for FFI shims, build glue, key lifecycle, smoke-testing. ([libdave](https://github.com/discord/libdave), [cpp/README](https://github.com/discord/libdave/blob/main/cpp/README.md))

**Killer counter-point:** [DisnakeDev/dave.py](https://github.com/DisnakeDev/dave.py) ships **Python bindings to libdave with prebuilt PyPI wheels**. Python doesn't dodge libdave — it dodges the *integration*. `pip install dave.py` runs the same C++ behind a maintained API. abaddon-fork inherits its existing `dave.cpp` wiring. Only from-scratch C++ pays from zero.

## 4. You will reinvent abaddon's fingerprint bugs — worse

Bugs abaddon paid 4+ years to debug, you re-pay from blank ([BLOCKER-fingerprinting](./BLOCKER-fingerprinting-and-detection.md)): stale `client_build_number` (`363557` hardcoded, drifts without daily scraping); stale UA (`Chrome/67.0.3396.87` from May 2018, current is 131+); header order matters; `X-Context-Properties` required for join-guild/friend flows; `capabilities` drifts (4605 → 16381 → next). You're writing *two* projects: a client and an unofficial Discord research program. Path A inherits bugs-already-found. Path C inherits a community of selfbot users debugging this. Path B has you, alone.

## 5. Dear ImGui isn't free either

The C++ brief calls ImGui "~100 KB, zero deps." Reality: `example_win32_directx11/main.cpp` is **285 lines** just for a blank window ([example](https://github.com/ocornut/imgui/blob/master/examples/example_win32_directx11/main.cpp)). You own window class + `WndProc` + WM_SIZE/DPI/DEVICECHANGE; D3D11 init/cleanup/reset + WARP fallback; per-frame backend→ImGui→draw→present; font atlas, DPI, IME; minimize-skip-`Present()`. Hidden cost: **400–800 LoC of GUI scaffolding** before any feature. PySide6's `QTreeView` + `QSystemTrayIcon` is click-to-join in ~80 lines and idles on the Win32 message pump for free.

## 6. Memory-unsafe C++ in token + crypto paths is real risk

Hot paths: token (DPAPI, IDENTIFY), voice handshake (32-byte key in memory), MLS state, RTP buffers (50 pps × N peers of raw `uint8_t*`). A use-after-free in the jitter buffer or one-byte off-by-one in nonce-append can leak the token into a different TLS frame, silently corrupt MLS state, or crash mid-call. The C++ brief concedes "audio raw-buffer path is highest-risk." Python isolates token to `str` and MLS to dave.py's binding boundary; abaddon-fork inherits years of fuzzing here. From-scratch starts at zero; ASan + `unique_ptr` discipline is **more weeks** on an already-blown budget.

## 7. Solo-dev velocity

| Path | First voice connection | Daily-driver |
|---|---|---|
| A: Fork abaddon, strip text/embeds | **1 weekend** | 2–3 weeks |
| C: Python (`discord.py-self[voice]` + `curl_cffi` + PySide6) | **1–2 weeks** | 3–4 weeks |
| B: From-scratch C++ | **3–5 months** | 5–7 months |

Perspective: discord.py (started ~2015, 1.0 in 2018, ~5k commits) and DSharpPlus (1,300+ commits, multi-year) are *bot* libraries; user-mode adds gateway-shape + voice complexity on top. A solo dev reimplementing even the voice-only slice takes on a multi-person, multi-year-library-shaped project. ([discord.py](https://github.com/Rapptz/discord.py/releases), [DSharpPlus](https://github.com/DSharpPlus/DSharpPlus))

## 8. "Low CPU" is met by both other paths

CPU is dominated by libopus encode (~1.5% one core) and libsodium AEAD (<0.1%, AES-NI). **Both native in all three paths.** Marginal C++ wins over Python: asyncio vs blocking I/O (~0.05% one core idle), JSON parse microseconds per ~41 s, no GC. Python idle <0.1%; C++ idle <0.05% of one core. **The user has 64 GB RAM and 8+ cores; 95% of CPU goes to their game.** Saving 0.05% of one core at the cost of 3–5 months of nights-and-weekends has no defensible cost-benefit. "Near-zero idle CPU" is met by all three.

## 9. You become Discord's QA team alone

Discord ships breaking changes regularly: `_rtpsize` AEAD modes mandated 2024, DAVE mandatory 2026-03-01, `capabilities` shifts, `READY_SUPPLEMENTAL` evolves. **Path A:** upstream patches arrive within days, cherry-pickable. **Path C:** `discord.py-self` v2.1.0 (2026-01-18) reacts within a release cycle ([discord.py-self](https://pypi.org/project/discord.py-self/)). **Path B:** you, alone, at midnight, when Discord rolls v10→v11 and your client stops. Population maintaining a from-scratch C++ voice-only Discord client with your exact libsodium build: N=1. A 3-month build becomes a 3-year obligation.

## 10. Why both alternatives beat from-scratch C++

**Path A beats Path B because** abaddon *is* the C++ codebase you'd write, ~90% finished, already linked against libsodium/libopus/libdave, shipping the right super-properties, exercising voice against live servers. Its bugs are *known, reproducible, fixable in days*; from-scratch bugs are *unknown* and found via cryptic voice close codes. Forking trades "1 weekend to remove chat UI" for "3–5 months from blank."

**Path C beats Path B because** protocol-level work is a `pip install`. `discord.py-self[voice]` covers gateway + voice + user IDENTIFY. `curl_cffi` covers TLS/JA3/JA4 *better than C++ libcurl-impersonate* because its WebSocket inherits the same fingerprint automatically — no free-bee in C++. `dave.py` covers libdave. `PySide6` covers GUI/tray. Solo-dev surface area shrinks from ~20 weeks to ~2 weeks of glue. The 0.05% CPU you lose is invisible.

## 11. One honest concession

**What from-scratch C++ does better:** binary size + packaging. Static MSVC build is **4–8 MB single .exe** — no interpreter, no self-extractor, no AV false positives. abaddon-fork is ~15 MB with GTK; Python+Nuitka is **25–35 MB extracting to ~80 MB temp on first run**. If "tiny single executable with no runtime" is a top-3 goal, only Path B delivers.

**Why it doesn't justify the cost:** the user has a **64 GB RAM, 8-core gaming laptop**. Disk and RAM are explicitly free; CPU is the binding constraint and **all three paths meet it**. Saving 25 MB disk and 50 MB RAM against **3–5 months of solo dev** plus **N=1 maintenance forever** is a trade no honest engineer takes on a hobby project. If "small .exe" becomes real later, port the Python prototype then.

---

## Citations

- abaddon (~30k LoC C++, 1,373 commits): [uowuo/abaddon](https://github.com/uowuo/abaddon)
- libdave (mlspp + OpenSSL/BoringSSL, vcpkg): [discord/libdave](https://github.com/discord/libdave), [cpp/README](https://github.com/discord/libdave/blob/main/cpp/README.md)
- Python libdave binding (PyPI wheels): [DisnakeDev/dave.py](https://github.com/DisnakeDev/dave.py)
- ImGui Win32+D3D11 reference (285 LoC): [example_win32_directx11/main.cpp](https://github.com/ocornut/imgui/blob/master/examples/example_win32_directx11/main.cpp)
- vcpkg pain: [#16049](https://github.com/microsoft/vcpkg/issues/16049) · [#30577](https://github.com/microsoft/vcpkg/issues/30577) · [#15321](https://github.com/microsoft/vcpkg/issues/15321) · [#47302](https://github.com/microsoft/vcpkg/issues/47302)
- `discord.py-self` v2.1.0 (2026-01-18): [PyPI](https://pypi.org/project/discord.py-self/) · [GitHub](https://github.com/dolfies/discord.py-self)
- `curl_cffi`: [lexiforest/curl_cffi](https://github.com/lexiforest/curl_cffi)
- DSharpPlus / discord.py: [DSharpPlus](https://github.com/DSharpPlus/DSharpPlus) · [Rapptz/discord.py releases](https://github.com/Rapptz/discord.py/releases)
- DAVE enforcement (close 4017, 2026-03-01): [docs.discord.food/voice-connections](https://docs.discord.food/topics/voice-connections) · [Discord blog](https://discord.com/blog/meet-dave-e2ee-for-audio-video)
- abaddon fingerprint gaps: per `BLOCKER-fingerprinting-and-detection.md`

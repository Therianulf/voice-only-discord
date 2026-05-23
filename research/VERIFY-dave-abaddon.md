# VERDICT: WORKS

Confidence: HIGH. Abaddon's `master` branch contains a complete DAVE/MLS implementation merged via PR #410 on 2026-03-27 and shipped in release v0.2.4 on 2026-04-06 with the explicit changelog line "Added support for DAVE E2EE voice calls." The maintainer's earlier "will not implement" statement (v0.2.3, 2026-02-09) was reversed and acknowledged in the v0.2.4 notes ("I said I wouldn't but for a handful of reasons I basically had to"). No open issue post-2026-04-06 reports voice as broken on DAVE grounds.

---

## 1. Repository fetch (default branch, last commit)

Repo: https://github.com/uowuo/abaddon — default branch `master`. Most recent commit is `7fb4a42` "remove boringssl hack for openbsd. (#412)" dated 2026-03-31.

## 2. DAVE/MLS code presence in `src/discord/`

Both files exist on `master`:

- `src/discord/dave.cpp` — ~330 lines, implements class `DaveSession`.
- `src/discord/dave.hpp` — header, includes `<dave/dave_interfaces.h>` (libdave).

Constructor:

```
DaveSession(Snowflake channelId, Snowflake userId,
            const std::unordered_map<uint32_t, Snowflake> &ssrcUserMap);
```

`dave.cpp` invokes real libdave/MLS calls: `discord::dave::mls::CreateSession()`, `discord::dave::CreateEncryptor()`, `discord::dave::CreateDecryptor()`, `discord::dave::Codec::Opus`, plus `GetMarshalledKeyPackage()`, `SetExternalSender()`, `ProcessProposals()`, `ProcessCommit()`, `ProcessWelcome()`, `GetKeyRatchet()`, `GetPairwiseFingerprint()`, `GetLastEpochAuthenticator()`. The class implements the full MLS lifecycle (Init, Reinit, OnProposals, OnAnnounceCommitTransition, OnWelcome, OnPrepareTransition, OnExecuteTransition, CompleteTransition, OnPrepareEpoch), per-SSRC decryptor management, key ratchet application, and a downgrade-to-unencrypted path. Gated by `#ifdef WITH_VOICE`. No TODO/FIXME/stub markers.

## 3. Build configuration

`CMakeLists.txt`: `find_package(libdave QUIET)` with `add_subdirectory(subprojects/libdave/cpp EXCLUDE_FROM_ALL)` fallback, equivalent setup for `mlspp` (aliases `MLSPP::mlspp`, `MLSPP::hpke`), and `target_link_libraries(abaddon libdave)`. The build option is `ENABLE_VOICE` (defining `WITH_VOICE`); there is no separate `WITH_DAVE` flag — DAVE compiles unconditionally whenever voice is enabled. PR #410 added 54 lines to CMakeLists.txt. `.gitmodules` registers `subprojects/libdave` and `subprojects/mlspp`. README lists both as "(provided as submodule, required for voice E2EE)".

## 4. Issue #407 ("establishing connection")

URL: https://github.com/uowuo/abaddon/issues/407. Author: `1rllx`. Opened 2026-03-04. Status: **Open**. Body verbatim: "Hi voice channel connection isnt working since monday just noticed that discord changed something on march 1st can this thing be fixed and it will work again? It would be very important to me because I have been using this client for a very long time thanks for the answer". No visible maintainer comments and no mention of DAVE/MLS/4017 in the issue itself. This issue confirms voice broke on the 2026-03-01 mandate for the v0.2.3 build the reporter was using, but it predates PR #410 (2026-03-27) and release v0.2.4 (2026-04-06).

## 5. Maintainer public statement on DAVE

Two contradictory statements exist, in chronological order:

- **Release v0.2.3 (2026-02-09), by `@ouwou`**, verbatim: "E2EE/dave for voice will not be implemented in Abaddon which Discord will be enforcing beginning March 1st. The aforementioned rewrite will support it tho." (https://github.com/uowuo/abaddon/releases/tag/v0.2.3)
- **Release v0.2.4 (2026-04-06), by `@ouwou`**, verbatim: "I said I wouldn't but for a handful of reasons I basically had to. Rewrite still coming :3 / Changes: / - Added support for DAVE E2EE voice calls / - treat OpenBSD like linux for resource path (#408) / - Tweaks for flathub (#399)". (https://github.com/uowuo/abaddon/releases/tag/v0.2.4)

The v0.2.4 statement is the current, operative one. The `BAKEOFF-abaddon-con.md` and `BAKEOFF-python-pro.md` claims that "the maintainer will not implement DAVE" are based on the obsolete v0.2.3 statement.

## 6. Recent commit history (last 90 days)

- `02523a2` "dave (#410)" — 2026-03-27 — 14 files changed, 856 additions, 31 deletions. Adds `dave.cpp/hpp`, libdave + mlspp submodules, CMake integration, modifies `voiceclient.cpp/hpp`, `websocket.cpp/hpp`, `discord.cpp`. PR by `ouwou`, approved by `blazed52`.
- `7fb4a42` "remove boringssl hack for openbsd. (#412)" — 2026-03-31 (latest on master).
- `f15558c` miniaudio submodule + openbsd sndio fix — 2026-03-26.
- Earlier: `dbf8115` "fix not respecting libsodiums reported mlen on decrypt" (2026-01-01); `d10d71f` "use new encryption" (2025-12-15).

## 7. Post-mandate user reports

- Issue #407 is the only voice-breakage report tied to the 2026-03-01 mandate; filed against the pre-DAVE v0.2.3 build, weeks before v0.2.4 shipped.
- No "voice broken / 4017 / cannot connect" issues filed since v0.2.4's release on 2026-04-06. Open issues from April/May 2026: #421 (compiler error 2026-05-17), #420 (naming question 2026-05-11), #419 (macOS keychain linking 2026-04-30), #418 (MLSPP namespace 2026-04-30), #417 (X-Super-Properties 2026-04-29), #415 (UI height 2026-04-22), #414 (image rendering 2026-04-21). None report voice failure or DAVE handshake errors.
- Issue #418 is a build-time concern when linking system mlspp (abaddon forces `MLS_CXX_NAMESPACE=mlspp`) — affects distro packagers, not runtime DAVE functionality. The bundled submodule build is unaffected.
- Issue #326 ("Support Discord's new E2EE using libdave", 2024-09-19) remains administratively open; PR #410 effectively resolves it. Could not verify Reddit / abaddon Discord server reports.

## Final verdict

**WORKS.** Evidence: (1) `src/discord/dave.{cpp,hpp}` contain full libdave/MLS lifecycle code with no stubs; (2) PR #410 merged 2026-03-27 with 856 additions; (3) v0.2.4 release notes (2026-04-06) explicitly state "Added support for DAVE E2EE voice calls"; (4) libdave and mlspp are wired into CMake and registered as submodules; (5) no post-v0.2.4 issues report voice failure or 4017. The `BAKEOFF-abaddon-con.md` and `BAKEOFF-python-pro.md` claims rely on the now-superseded v0.2.3 statement and on issue #407 (filed against the pre-DAVE build). Only outstanding DAVE-adjacent concern: issue #418, which affects distro packaging with system mlspp, not the default bundled-submodule build. A new project forking abaddon `master` (or building v0.2.4+) inherits a working DAVE implementation.

---

## Citations

- https://github.com/uowuo/abaddon (repo root, master branch, README dependencies section)
- https://github.com/uowuo/abaddon/tree/master/src/discord (directory listing showing dave.cpp, dave.hpp, voiceclient.cpp)
- https://raw.githubusercontent.com/uowuo/abaddon/master/src/discord/dave.cpp (DaveSession implementation, ~330 lines)
- https://raw.githubusercontent.com/uowuo/abaddon/master/src/discord/dave.hpp (DaveSession header, includes <dave/dave_interfaces.h>)
- https://raw.githubusercontent.com/uowuo/abaddon/master/CMakeLists.txt (libdave/mlspp find_package + add_subdirectory)
- https://raw.githubusercontent.com/uowuo/abaddon/master/.gitmodules (libdave + mlspp submodules)
- https://raw.githubusercontent.com/uowuo/abaddon/master/README.md (libdave and mlspp listed as "required for voice E2EE")
- https://github.com/uowuo/abaddon/pull/410 (PR "dave" by ouwou, merged 2026-03-27, approved by blazed52)
- https://github.com/uowuo/abaddon/pull/410/files (14 files changed including dave.cpp, dave.hpp, voiceclient.*, websocket.*, CMakeLists.txt, .gitmodules)
- https://github.com/uowuo/abaddon/commit/02523a2 (commit "dave (#410)", 856 additions, 31 deletions)
- https://github.com/uowuo/abaddon/commits/master (commit log, most recent 7fb4a42 on 2026-03-31)
- https://github.com/uowuo/abaddon/releases/tag/v0.2.4 (release notes 2026-04-06: "Added support for DAVE E2EE voice calls")
- https://github.com/uowuo/abaddon/releases/tag/v0.2.3 (release notes 2026-02-09: "E2EE/dave for voice will not be implemented in Abaddon")
- https://github.com/uowuo/abaddon/issues/407 (open, "establishing connection", 1rllx, 2026-03-04, pre-DAVE v0.2.3 build)
- https://github.com/uowuo/abaddon/issues/326 (open, "Support Discord's new E2EE using libdave", StayBlue, 2024-09-19)
- https://github.com/uowuo/abaddon/issues/418 (open, "Mismatching namespace for MLSPP", barracuda156, 2026-04-30 — build-time only)
- https://support.discord.com/hc/en-us/articles/38749827197591-A-V-E2EE-Enforcement-for-Non-Stage-Voice-Calls (Discord's DAVE enforcement policy)
- https://discord.com/blog/bringing-dave-to-all-discord-platforms (Discord's DAVE rollout)

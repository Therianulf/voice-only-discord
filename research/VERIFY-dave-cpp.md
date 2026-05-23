# VERDICT: MODERATE

Confidence: HIGH on buildability and license, MEDIUM on person-week estimate.
libdave is MIT, tagged (v1.1.1, Jan 30 2025), has a clean public C++ API and abaddon ships a 320-line working integration. There is no examples/ folder and no Discord-authored wiring guide — you derive opcode→API binding from the protocol whitepaper and abaddon's source. Call it 2–4 focused weeks for a C++ dev who has touched MLS/WebRTC SFrame before, 5–8 weeks otherwise.

---

## 1. Build instructions and dependencies

From `cpp/README.md` (libdave): the documented steps are

```
git submodule update --recursive
./vcpkg/bootstrap-vcpkg.sh
make cclean
make            # static lib; or `make shared` for .so/.dll
```

Dependencies (from `cpp/README.md`, `cpp/CMakeLists.txt`, `cpp/Makefile`):

- **mlspp** — configured with `-DMLS_CXX_NAMESPACE="mlspp"` and `-DDISABLE_GREASE=ON`. Linked as `MLSPP::mlspp` (private).
- **SSL**: OpenSSL 3 (default), OpenSSL 1.1, or BoringSSL. Selected via `VCPKG_MANIFEST_DIR` (`vcpkg-alts/openssl_3` | `vcpkg-alts/openssl_1.1` | `vcpkg-alts/boringssl`). OpenSSL pinned to **3.0.7** in the overrides.
- **nlohmann_json** — required.
- **googletest / AFLplusplus** — testing/fuzzing only.

CMake project metadata: `project(libdave VERSION 1.0 LANGUAGES CXX C)`, C++17 required. Public include dirs are `${PROJECT_SOURCE_DIR}/includes` (note: `includes/`, not `include/`).

Only one git submodule is declared: `cpp/vcpkg` → `https://github.com/microsoft/vcpkg.git`. mlspp is **not** a submodule — it is pulled by a vcpkg overlay port.

## 2. License

libdave is **MIT** (Copyright 2024 Discord). Quoted obligation: "The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software." No copyleft, no derivative-project poisoning. mlspp is BSD-2-Clause; nlohmann_json/OpenSSL/BoringSSL are permissive. The DAVE whitepaper is CC BY-NC-SA 4.0 (restricts redistributing the spec text, not implementing it).

## 3. Public API surface

Headers under `cpp/includes/dave/` (5 files): `array_view.h`, `dave.h` (C API), `dave_interfaces.h` (C++ API), `logger.h`, `version.h`. C++ API in `namespace discord::dave`, MLS in `discord::dave::mls`. Three pillar interfaces:

- **`mls::ISession`** — built via `mls::CreateSession(KeyPairContextType, std::string authSessionId, MLSFailureCallback)`. Methods: `Init(ProtocolVersion, uint64_t groupId, std::string selfUserId, std::shared_ptr<mlspp::SignaturePrivateKey>&)`, `Reset`, `SetProtocolVersion`, `GetProtocolVersion`, `GetLastEpochAuthenticator`, `SetExternalSender`, `ProcessProposals`, `ProcessCommit`, `ProcessWelcome`, `GetMarshalledKeyPackage`, `GetKeyRatchet`, `GetPairwiseFingerprint`.
- **`IEncryptor`** (via `CreateEncryptor()`): `SetKeyRatchet`, `SetPassthroughMode`, `HasKeyRatchet`, `AssignSsrcToCodec`, `Encrypt(MediaType, ssrc, frame, encryptedFrame, bytesWritten)`, `GetMaxCiphertextByteSize`, `SetProtocolVersionChangedCallback`.
- **`IDecryptor`** (via `CreateDecryptor()`): `TransitionToKeyRatchet`, `TransitionToPassthroughMode`, `Decrypt`, `GetMaxPlaintextByteSize`.

Plus `IKeyRatchet` (consumer-implementable), enums `MediaType` and `Codec {Unknown, Opus, VP8, VP9, H264, H265, AV1}`, and an opaque-handle C API (`DAVESessionHandle`) in `dave.h` for FFI.

## 4. Integration documentation in the repo

Thin. **No `examples/` or `docs/` directory** under `cpp/`. Reference material is `cpp/test/` (five gtest files: `codec_utils_tests.cpp`, `cryptor_manager_tests.cpp`, `cryptor_tests.cpp`, `dave_test.cpp`, `xssl_cryptor_tests.cpp`, plus `external_sender.cpp/h` and `static_key_ratchet.cpp/h` helpers and a `capi/` subdir). The cryptor tests show realistic `IEncryptor`/`IDecryptor`/`IKeyRatchet` use via gmock (`MOCK_METHOD(EncryptionKey, GetKey, ...)`, `CryptorManager::GetCryptor(generation)`). `cpp/afl-driver/` is a fuzz harness. The opcode→API mapping must be inferred from `protocol.md` and abaddon. Could not verify any official Discord sample app.

## 5. Voice-gateway opcodes (from `discord/dave-protocol/protocol.md` v1.1)

Negotiation and transitions (JSON):
- **op 21 `dave_protocol_prepare_transition`** — `{protocol_version, transition_id}` (transition_id=0 means reinitialization).
- **op 22 `dave_protocol_execute_transition`** — `{transition_id}`.
- **op 23 `dave_protocol_ready_for_transition`** — client → gateway readiness with `transition_id`.
- **op 24 `dave_protocol_prepare_epoch`** — announces epoch change; `epoch=1` triggers MLS group recreation.

MLS group operations (binary):
- **op 25 `dave_mls_external_sender_package`** — `SignaturePublicKey + Credential(credential_type=1, identity<V>)` for the gateway as external sender. Feed into `ISession::SetExternalSender`.
- **op 26 `dave_mls_key_package`** — `MLSMessage` carrying the client's KeyPackage. Produce via `ISession::GetMarshalledKeyPackage`.
- **op 27 `dave_mls_proposals`** — proposals with `enum { append(0), revoke(1) } ProposalsOperationType`, `MLSMessage proposal_messages<V>` or `ProposalRef proposal_refs<V>`. Feed into `ISession::ProcessProposals`.
- **op 28 `dave_mls_commit_welcome`** — `MLSMessage` commit + optional Welcome.
- **op 29 `dave_mls_announce_commit_transition`** — commit + `transition_id` (uint16). Drives `ISession::ProcessCommit`.
- **op 30 `dave_mls_welcome`** — Welcome + `transition_id`. Drives `ISession::ProcessWelcome`.
- **op 31 `dave_mls_invalid_commit_welcome`** — client → gateway failure report with `transition_id`.

Identify (op 0) must include `max_dave_protocol_version`; `select_protocol_ack` (op 4) returns `dave_protocol_version`. Encrypted frame format: `[payload]` + 8-byte truncated AES-GCM tag + ULEB128 nonce + ULEB128 unencrypted ranges + 1-byte supplemental size + 2-byte magic `0xFAFA`. AES128-GCM media; MLS ciphersuite `DHKEMP256_AES128GCM_SHA256_P256`; MLS-Exporter label `"Discord Secure Frames v0"`; key rotation per epoch or per 2^24 frames. Codec quirks (OPUS/VP9 fully encrypted, VP8 leaves 1 or 10 bytes, H.264/265 leave VCL headers, AV1 leaves OBU headers) are handled inside `IEncryptor`/`IDecryptor`.

## 6. mlspp build status

libdave does not vendor mlspp as a submodule; it ships a **vcpkg overlay port** at `cpp/vcpkg-alts/<ssl>/overlay-ports/mlspp/`. The overlay's `vcpkg.json` pins `"version-string": "1cc50a124a3bc4e143a787ec934280dc70c1034d"` and `portfile.cmake` uses `REF "${VERSION}"` with a sha512 hash. That is an **exact commit pin against `cisco/mlspp`** — the supported build path takes this commit through vcpkg, not `mlspp/main`, so the "is main compatible?" question is moot. mlspp's transitive deps (hpke etc.) are vcpkg-owned. Could not verify a CI matrix; v1.1.1 (Jan 30 2025) is the latest release.

## 7. abaddon as a reference integration

Confirmed at `https://github.com/uowuo/abaddon/blob/master/src/discord/dave.cpp` (HTTP 200, ~320 lines, ~10.6 KB) with companion `dave.hpp`. The wrapper class is **`DaveSession`** in the global namespace. Public surface (~21 methods plus 4 signals):

- Lifecycle: `DaveSession()`, `~DaveSession()`, `Init()`, `Reinit()`.
- Binary opcode handlers: `OnExternalSenderPackage()`, `OnProposals()`, `OnAnnounceCommitTransition()`, `OnWelcome()`.
- JSON opcode handlers: `OnPrepareTransition()`, `OnExecuteTransition()`, `OnPrepareEpoch()`, `CompleteTransition()`.
- Crypto access: `GetEncryptor()`, `GetOrCreateDecryptor()`, `ApplyKeyRatchetForSSRC()`.
- Roster/SSRC: `SetLocalSSRC()`, `AddConnectedUser()`, `RemoveConnectedUser()`.
- Identity: `GetPairwiseFingerprint()`, `GetLastEpochAuthenticator()`.
- libsigc++ signals: `signal_send_binary`, `signal_send_ready_for_transition`, `signal_send_invalid_commit_welcome`, `signal_state_changed`.

Includes are `#include "dave.hpp"` and `#include <dave/logger.h>`; no TODO comments; entire file gated on `#ifdef WITH_VOICE`. Wiring in `voiceclient.cpp` (line ~893): `m_dave = std::make_unique<DaveSession>(m_channel_id, m_user_id, m_ssrc_user_map);` followed by `m_dave->signal_send_binary().connect(...)` and opcode dispatch around lines 788–861. **This is a real, portable wiring blueprint** — a from-scratch C++ project can lift the structure (handler-per-opcode + signals/callbacks back to the WebSocket sender) almost verbatim.

(An older comment elsewhere that "E2EE/DAVE will not be implemented in abaddon" is stale; the file is present on `master`.)

## 8. Person-week estimate

- **Experienced** (prior MLS or WebRTC SFrame, fluent with vcpkg/CMake): **2–3 weeks**. Days 1–3: build libdave + mlspp, round-trip a marshalled KeyPackage. Week 1: wire opcodes 21–30 to `ISession` using abaddon as a map. Week 2: integrate `IEncryptor`/`IDecryptor` into the RTP path with per-SSRC decryptor map, codec assignment, passthrough toggling on transitions. Week 3: fingerprints/authenticator UI and soak testing.
- **New to MLS but competent C++**: **5–8 weeks**. Add a week to internalize the whitepaper (transitions, generations, ratchets), a week to debug vcpkg/mlspp builds on Windows or macOS arm64, a week of testing against Discord's live gateway (no staging endpoint).
- Risk multipliers: cross-compile to mobile/wasm, custom SSL backend, or rolling your own MLS instead of mlspp — each adds weeks.

No blocker: library exists, builds, is MIT, tagged, wire protocol fully documented, working open-source C++ integration to copy. MODERATE rather than EASY because nothing in libdave itself binds opcodes to API methods.

---

## Citations

- libdave repo + C++ README: https://github.com/discord/libdave and https://github.com/discord/libdave/blob/main/cpp/README.md
- `dave_interfaces.h` (public API): https://raw.githubusercontent.com/discord/libdave/main/cpp/includes/dave/dave_interfaces.h
- LICENSE: https://github.com/discord/libdave/blob/main/LICENSE
- Releases (v1.1.0 2025-01-17, v1.1.1 2025-01-30): https://github.com/discord/libdave/releases
- mlspp overlay portfile (`REF "${VERSION}"`, sha512): https://raw.githubusercontent.com/discord/libdave/main/cpp/vcpkg-alts/openssl_3/overlay-ports/mlspp/portfile.cmake
- mlspp upstream: https://github.com/cisco/mlspp
- DAVE whitepaper + `protocol.md` (v1.1, CC BY-NC-SA 4.0): https://github.com/discord/dave-protocol/blob/main/protocol.md
- abaddon `dave.cpp` / `dave.hpp` / `voiceclient.cpp`: https://github.com/uowuo/abaddon/blob/master/src/discord/dave.cpp
- Discord.Net libdave guide: https://docs.discordnet.dev/guides/voice/libdave.html
- Disnake `dave.py` bindings (independent confirmation libdave is consumable): https://github.com/DisnakeDev/dave.py

Uncertainties marked "could not verify":
- No CI status badge on libdave; could not verify whether the v1.1.1 release builds out-of-the-box on macOS arm64 or Windows MSVC today.
- Could not verify whether mlspp `main` (post 1cc50a1) is drop-in compatible; the supported answer is "use the pinned commit via vcpkg."
- Could not verify any official end-to-end sample from Discord beyond the test suite.

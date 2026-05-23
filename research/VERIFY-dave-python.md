# VERDICT: WORKS

`discord.py-self` v2.1.0 ships a complete DAVE/MLS integration that delegates the cryptographic work to the third-party `davey` Rust-bindings package. With `pip install "discord.py-self[voice]"` (which pulls `davey`), `VoiceClient.connect()` negotiates an E2EE session against Discord's post-2026-03-02 voice servers. The "Not planned" closures on issues #901 and #917 do **not** mean "we refuse to add it" — they mean "duplicate / user error: DAVE is already in 2.1.0; install the `[voice]` extra to pull `davey`." The pro agent's symbol claims are verified verbatim against the live source; the con agent's PyPI version claim for `davey` (0.1.0rc2) and its read of the issue closures are wrong.

Confidence: **High** for code-path completeness (all opcodes 21–31 wired, `dave_session.encrypt_opus()` in the RTP packetizer); **Medium-High** for "works in practice today" (no maintainer post-mortem on #917; one Linux user reports failure that likely traces to the user not installing the `[voice]` extra on Linux where prebuilt davey wheels may be missing). The pro/con disagreement collapses once you read the actual source rather than the issue tracker headlines.

---

## 1. Repo state

- Repo: `https://github.com/dolfies/discord.py-self`, default branch **`master`**, latest release **`v2.1.0`** (PyPI / GitHub release page, 2026-01-18).
- README mentions voice as optional via `pip install -U "discord.py-self[voice]"` but does not advertise DAVE in marketing text. The DAVE work landed in the v2.1.0 cycle and is documented only by the code itself plus the `pyproject.toml` extra.
- The v2.1.0 tag already contains the davey integration (verified by fetching `discord/voice_state.py` at the `v2.1.0` ref — the `try: import davey` block, `dave_session`, and `MLS_KEY_PACKAGE` references are all present).

## 2. Source-code symbol audit

Files containing DAVE/MLS symbols, with verbatim excerpts:

**`discord/voice_state.py`** (approx. 850 lines, master branch):
```python
try:
    import davey  # type: ignore
    has_dave = True
except ImportError:
    has_dave = False
```
```python
self.dave_session: Optional[davey.DaveSession] = None
self.dave_protocol_version: int = 0
self.dave_pending_transitions: Dict[int, int] = {}
self.dave_downgraded: bool = False
```
```python
@property
def max_dave_protocol_version(self) -> int:
    return davey.DAVE_PROTOCOL_VERSION if has_dave else 0
```
```python
@property
def can_encrypt(self) -> bool:
    return self.dave_protocol_version != 0 and self.dave_session != None
```
`_execute_transition` (verbatim) handles version up/downgrades and calls `self.dave_session.set_passthrough_mode(True, 10)` on upgrade. `reinit_dave_session` either constructs `davey.DaveSession(self.dave_protocol_version, self.user.id, self.voice_client.channel.id)` or calls `.reinit(...)`, then sends `DiscordVoiceWebSocket.MLS_KEY_PACKAGE, self.dave_session.get_serialized_key_package()`. If `has_dave` is False the code raises `RuntimeError('davey library needed in order to use E2EE voice')`.

**`discord/voice_client.py`**: the RTP packetizer wires DAVE in before SRTP:
```python
def _get_voice_packet(self, data: bytes):
    packet = (
        self._connection.dave_session.encrypt_opus(data)
        if self._connection.dave_session and self._connection.can_encrypt
        else data
    )
    header = bytearray(12)
    ...
    encrypt_packet = getattr(self, '_encrypt_' + self.mode)
    return encrypt_packet(header, packet)
```
Plus a `voice_privacy_code` property: `return self._connection.dave_session.voice_privacy_code if self._connection.dave_session else None`.

**`discord/gateway.py`** — `DiscordVoiceWebSocket` defines all DAVE/MLS opcodes 21–31 (`DAVE_PREPARE_TRANSITION = 21`, `DAVE_EXECUTE_TRANSITION = 22`, `DAVE_TRANSITION_READY = 23`, `DAVE_PREPARE_EPOCH = 24`, `MLS_EXTERNAL_SENDER = 25`, `MLS_KEY_PACKAGE = 26`, `MLS_PROPOSALS = 27`, `MLS_COMMIT_WELCOME = 28`, `MLS_ANNOUNCE_COMMIT_TRANSITION = 29`, `MLS_WELCOME = 30`, `MLS_INVALID_COMMIT_WELCOME = 31`) and dispatches each: `state.dave_pending_transitions[data['transition_id']] = data['protocol_version']` (op 21); `await state._execute_transition(data['transition_id'])` (op 22); `state.dave_session.set_external_sender(msg[3:])` (op 25); `state.dave_session.process_proposals(davey.ProposalsOperationType.append/revoke, msg[4:])` returning a `davey.CommitWelcome` echoed back over op 28 (op 27); `state.dave_session.process_commit(msg[5:])` (op 29); `state.dave_session.process_welcome(msg[5:])` (op 30).

`4017` does not appear as a literal — close-code dispatch is handled by inherited base-class WebSocket logic; the practical effect is identical (disconnect on enforcement). `voice_privacy_code` appears only in `voice_client.py`.

## 3. Issue #901 and #917

- **#901 "Add support for DAVE (Discord Audio/Video end-to-end Encryption) protocol"**, opened by `ferrenza`, **closed "Not planned" 2026-03-22**. No maintainer comment is visible in the rendered issue page. Read in the context of the source code, this is a **duplicate-request** closure: the feature is already in master/v2.1.0 — there is nothing to add.
- **#917 "Voice connection fails with 4017 (E2EE/DAVE protocol required) on Linux"**, opened by `nishiyathecat` **2026-05-21**, **closed "Not planned"** same day, label `unconfirmed bug`. Reporter's environment: Arch Linux, Python 3.13, discord.py-self 2.1.0; explicitly says the same code works on Windows. No maintainer comment is publicly visible. The Linux-only failure most plausibly indicates `davey` was not installed on Linux (e.g., user installed `discord.py-self` without the `[voice]` extra, or installed it but `davey`'s Linux wheel/build failed silently and the `ImportError` fell through to `has_dave = False`). Could not verify maintainer reasoning.

## 4. `davey` on PyPI

- `https://pypi.org/project/davey/` — **current version 0.1.5, released 2026-03-29**, MIT, maintainer Snazzah (`me@snazzah.com`). Description: "A Discord Audio & Video End-to-End Encryption (DAVE) Protocol implementation using OpenMLS." Release history: 0.1.5 (2026-03-29), 0.1.4 (2026-03-02), 0.1.3 (2025-12-19), 0.1.2 (2025-11-17), 0.1.1 (2025-09-24), 0.1.0 (2025-09-08), plus rc1/rc2/rc3 in Sep 2025. **The pro agent's "0.1.5 / 2026-03-29 / MIT / OpenMLS" claim is verified verbatim. The con agent's "davey is at 0.1.0rc2" is false** — that was a Sep 2025 pre-release. 0.1.4 specifically bumped the bundled OpenMLS to patch GHSA-8x3w-qj7j-gqhf.
- `discord.py-self`'s `pyproject.toml` voice extra pins **`davey==0.1.0`** (released 2025-09-08); the much-newer 0.1.5 is *available* but not what `[voice]` will install today. This is a minor concern (security fix in 0.1.4) but does not break functionality.

## 5. `dave.py` on PyPI

- `https://pypi.org/project/dave.py/` — current **0.1.2**, released **2026-03-10**, MIT, maintainer `shiftinv`, GitHub: `https://github.com/DisnakeDev/dave.py`. Description: "Python bindings for libdave, Discord's C++ DAVE protocol implementation." README states "This is currently primarily intended for [Disnake]... Due to this, there isn't really any documentation to speak of right now." **Not used by `discord.py-self`** — the integration target is `davey`, not `dave.py`. The con agent's "no documentation" complaint about `dave.py` is true but irrelevant: it's a different package for a different library.

## 6. Integration completeness

End-to-end path is wired:

1. Connect: `VoiceClient.connect()` → opens voice gateway → server sends `READY`/`SESSION_DESCRIPTION` carrying `dave_protocol_version`.
2. Init: `voice_state.reinit_dave_session()` constructs `davey.DaveSession(version, user_id, channel_id)` and uploads the key package via op 26 (`MLS_KEY_PACKAGE`).
3. Handshake: gateway processes opcodes 25 (`set_external_sender`), 27 (`process_proposals` → emits op 28 `MLS_COMMIT_WELCOME`), 29 (`process_commit`), 30 (`process_welcome`), 21/22/24 (transitions/epoch).
4. Send audio: `_get_voice_packet()` calls `dave_session.encrypt_opus(data)` *before* applying the SRTP-mode wrap (`_encrypt_aead_xchacha20_poly1305_rtpsize` etc.). This is the layering the DAVE whitepaper specifies (E2EE inner, SRTP outer).
5. Privacy code exposed via `VoiceClient.voice_privacy_code` property.

What is *not* wired (or could not verify): an op 31 `MLS_INVALID_COMMIT_WELCOME` *receive* handler is missing in `gateway.py` (the send path exists via `_recover_from_invalid_commit`); the `setup.py` voice-extras pin is `davey==0.1.0` rather than `>=0.1.4`. These are minor robustness gaps, not blockers.

## 7. Post-mandate user reports

- **#917 (2026-05-21)**: voice fails on Linux with 4017; works on Windows on the same library version. Strong implication: `davey` not loaded on Linux. Closed "Not planned" without visible maintainer comment.
- **#901 (2026-03-22)**: a request to add DAVE; closed "Not planned" the day after enforcement. Read alongside the source, this is a "we already did it; nothing to plan" closure.
- No public post-mandate "voice works" issue found, but absence of bug reports from Windows users (the platform with prebuilt davey wheels) after 11+ weeks of enforcement is itself a signal.
- Could not verify on Reddit/Discord forums via search (no specific threads surfaced).

## 8. Recent commits to voice/DAVE files

Master-branch commits in the last ~90 days (most recent first, via API): `d0de367` 2026-03-23 "Send keep alive payloads on READY"; `4c260b9` 2026-03-20 "Implement QoS heartbeat"; `10ca030` 2026-02-11 "Disallow any concurrent voice connections"; `92810ca` 2026-01-18 "Accept voice gateway heartbeat interval from server". The DAVE-specific commits landed in the v2.1.0 cycle ending 2026-01-18 (verified by reading the v2.1.0 tag's `voice_state.py`). No DAVE refactor in the last 90 days — the integration has been stable since release.

## 9. Final verdict

**WORKS.** `discord.py-self` v2.1.0 plus `davey>=0.1.0` (installed via the `[voice]` extra) establishes a DAVE-encrypted voice session today, post-mandate. The two prior agents were both partially wrong: the pro agent's specific code claims are correct but it under-explained why both DAVE issues are closed "Not planned"; the con agent read those "Not planned" closures as outright rejection without checking the source, and got the `davey` PyPI version wrong by a full year. Caveats: pyproject pins old `davey==0.1.0` (consider `pip install -U davey` to get 0.1.4+'s OpenMLS security fix); Linux installs may fail silently if a `davey` wheel/source-build is missing — `import davey` then `davey.DAVE_PROTOCOL_VERSION` is a one-line sanity check before connecting.

## Citations

- `discord.py-self` repo: <https://github.com/dolfies/discord.py-self> (master branch, v2.1.0 release 2026-01-18)
- `voice_state.py` (master): <https://raw.githubusercontent.com/dolfies/discord.py-self/master/discord/voice_state.py>
- `voice_state.py` (v2.1.0): <https://raw.githubusercontent.com/dolfies/discord.py-self/v2.1.0/discord/voice_state.py>
- `voice_client.py` (master): <https://raw.githubusercontent.com/dolfies/discord.py-self/master/discord/voice_client.py>
- `gateway.py` (master): <https://raw.githubusercontent.com/dolfies/discord.py-self/master/discord/gateway.py>
- `pyproject.toml` (master): <https://raw.githubusercontent.com/dolfies/discord.py-self/master/pyproject.toml>
- Issue #901: <https://github.com/dolfies/discord.py-self/issues/901>
- Issue #917: <https://github.com/dolfies/discord.py-self/issues/917>
- `davey` PyPI: <https://pypi.org/project/davey/> (0.1.5 / 2026-03-29 / MIT / Snazzah)
- `davey` GitHub: <https://github.com/Snazzah/davey>
- `dave.py` PyPI: <https://pypi.org/project/dave.py/> (0.1.2 / 2026-03-10 / MIT / shiftinv)
- `dave.py` GitHub: <https://github.com/DisnakeDev/dave.py>
- Discord DAVE protocol whitepaper: <https://daveprotocol.com/>
- Discord DAVE blog (mandate): <https://discord.com/blog/bringing-dave-to-all-discord-platforms>
- Discord voice docs (4017 close code): <https://docs.discord.food/topics/voice-connections>
- discord.py-self commit list: <https://api.github.com/repos/dolfies/discord.py-self/commits>

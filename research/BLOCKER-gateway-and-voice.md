# BLOCKER: Discord Gateway & Voice-Channel Protocol Requirements

## TL;DR

- A voice-only Discord client needs **one persistent gateway WebSocket** (read/write) plus, **only while in a voice channel**, **one voice WebSocket + one UDP socket** carrying RTP/Opus.
- For a **user-account** login (not a bot), the `intents` bitmask is **ignored** — user accounts receive nearly all relevant events by default and instead opt in to per-guild noise via OP 14. We do **not** subscribe to messages; we just discard `MESSAGE_CREATE` on receipt. This is the unavoidable price of user-account auth.
- Server + voice-channel state arrives from one event flow: **READY** (skeleton guild IDs) → **GUILD_CREATE** per guild (channels[] + voice_states[] inline) → live updates via **CHANNEL_CREATE/UPDATE/DELETE** and **VOICE_STATE_UPDATE**. Nothing else is structurally required.
- Joining voice is a fixed 6-step handshake (gateway OP 4 → VOICE_STATE_UPDATE + VOICE_SERVER_UPDATE → voice WS Identify/Hello/Ready → UDP IP discovery → Select Protocol → Session Description) followed by 50 Opus/RTP packets per second per stream.
- Realistic CPU budget on a modern laptop: **<0.5 % idle** (gateway heartbeat every ~41 s) and **2–5 % active** in a voice call (Opus encode + decode of N peers + AEAD). The official Electron client runs **10–30 %** for the same workload because of Chromium overhead.
- Send `presence` with `status: "invisible"` (or omit `presence` entirely, which defaults to invisible-equivalent for user accounts) to avoid appearing online to friends.

---

## 1. Gateway connection

### 1.1 Bootstrap

```
GET https://discord.com/api/v9/gateway       → { "url": "wss://gateway.discord.gg" }
WSS wss://gateway.discord.gg/?v=10&encoding=json
```

`v=10` is current stable; the web client speaks v9 with `encoding=json`. Use **v9** to mimic the web client (abaddon does, on purpose). Skip `encoding=etf` — the binary parse savings are dwarfed by everything else.

### 1.2 Opcode table (gateway, send/receive)

| Op | Name                  | Dir   | Use here                                      |
|----|-----------------------|-------|-----------------------------------------------|
| 0  | Dispatch              | recv  | All events (`t` field = event name)          |
| 1  | Heartbeat             | both  | Keepalive; send every `heartbeat_interval`   |
| 2  | Identify              | send  | After HELLO, once per session                |
| 3  | Presence Update       | send  | (Optional) set invisible at start            |
| 4  | Voice State Update    | send  | **Join/leave voice channel**                 |
| 6  | Resume                | send  | After dropped WS, use `resume_gateway_url`    |
| 7  | Reconnect             | recv  | Re-open, then send Resume                    |
| 8  | Request Guild Members | send  | Not needed                                    |
| 9  | Invalid Session       | recv  | Re-identify (full reconnect)                 |
| 10 | Hello                 | recv  | First packet; provides `heartbeat_interval`  |
| 11 | Heartbeat ACK         | recv  | Confirms last heartbeat                      |
| 14 | Guild Subscriptions   | send  | **Avoid sending** — see §1.6                  |

### 1.3 HELLO → IDENTIFY

```jsonc
// Server → client (immediately on connect)
{ "op": 10, "d": { "heartbeat_interval": 41250 } }
```

Heartbeat interval is typically **~41 s**. Send the first heartbeat at `heartbeat_interval * Math.random()` (jitter), then every `heartbeat_interval` ms exactly. Failing to ACK = zombie disconnect.

```jsonc
// Client → server, IDENTIFY (user account, web-client mimicry)
{
  "op": 2,
  "d": {
    "token": "<user_token>",
    "capabilities": 16381,
    "properties": {
      "os": "Windows",
      "browser": "Chrome",
      "device": "",
      "system_locale": "en-US",
      "browser_user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
      "browser_version": "120.0.0.0",
      "os_version": "10",
      "referrer": "",
      "referring_domain": "",
      "referrer_current": "",
      "referring_domain_current": "",
      "release_channel": "stable",
      "client_build_number": 270000,
      "client_event_source": null
    },
    "presence": {
      "status": "invisible",
      "since": 0,
      "activities": [],
      "afk": false
    },
    "compress": false,
    "client_state": {
      "guild_versions": {},
      "highest_last_message_id": "0",
      "read_state_version": 0,
      "user_guild_settings_version": -1,
      "user_settings_version": -1,
      "private_channels_version": "0",
      "api_code_version": 0
    }
  }
}
```

Key facts about user-account identify:

- **`intents` is omitted.** User accounts predate intents. The server ignores it. The client filters events itself and opts into expensive per-guild streams via OP 14. We will **not** send OP 14.
- **`capabilities` is a bitfield** (current stable web value: `16381`). It toggles modern payload shapes — most importantly `PRIORITIZED_READY_PAYLOAD`, which splits READY into a tiny first packet plus a deferred `READY_SUPPLEMENTAL`. Cargo-cult this value.
- **`properties` (super-properties)** match the base64 `X-Super-Properties` HTTP header the web client sends. Send it raw inside `d.properties` on IDENTIFY *and* base64-encoded as `X-Super-Properties` on every REST call. abaddon does exactly this ("tries to make Discord think it's a legitimate web client by ... sending the same IDENTIFY message that the official web client does").
- **`client_state`** lets the server skip data we already have on re-IDENTIFY. On cold start, send the empty values shown.

### 1.4 READY shape

```jsonc
{ "op": 0, "t": "READY", "s": 1, "d": {
    "v": 9,
    "user": { "id": "...", "username": "...", ... },
    "users": [...],                  // user-acct only: full friend/DM users
    "guilds": [
      { "id": "...", "unavailable": true }   // skeleton; full data in GUILD_CREATE
    ],
    "session_id": "...",
    "resume_gateway_url": "wss://gateway-us-east1-d.discord.gg",
    "session_type": "normal",
    "auth_session_id_hash": "...",
    "user_settings_proto": "...",    // user-acct only: base64 protobuf settings
    "relationships": [...],          // user-acct only: friends list
    "private_channels": [...],       // user-acct only: DMs
    "read_state": { ... },           // user-acct only
    "user_guild_settings": { ... }   // user-acct only
} }
```

For user accounts with `PRIORITIZED_READY_PAYLOAD` enabled (which `capabilities=16381` does), the heavy fields land in a second event:

```jsonc
{ "op": 0, "t": "READY_SUPPLEMENTAL", "d": {
    "merged_presences": { "guilds": [...], "friends": [...] },
    "merged_members": [[...], ...],   // parallel array to guilds[]
    "guilds": [{ "voice_states": [...], "embedded_activities": [...] }]
} }
```

`READY_SUPPLEMENTAL.guilds[i].voice_states` arrives **before** GUILD_CREATE in some cases — keep a buffer.

### 1.5 GUILD_CREATE — the structural event we actually care about

```jsonc
{ "op": 0, "t": "GUILD_CREATE", "d": {
    "id": "guild_snowflake",
    "name": "My Server",
    "icon": "...",
    "channels": [
      { "id": "...", "type": 4, "name": "Voice category", "position": 0 },
      { "id": "...", "type": 2, "name": "General",   "parent_id": "...", "bitrate": 64000, "user_limit": 0, "rtc_region": null },
      { "id": "...", "type": 13, "name": "Stage",    "parent_id": "...", "bitrate": 40000 }
    ],
    "voice_states": [
      { "user_id": "...", "channel_id": "...", "session_id": "...", "self_mute": false, "self_deaf": false, "self_video": false, "suppress": false, "mute": false, "deaf": false }
    ],
    "members": [...],   // truncated; we discard
    "presences": [...], // we discard
    "threads": [...]    // we discard
} }
```

**Channel types we care about:**
- `2` = guild voice
- `13` = stage voice
- `4` = category (needed only to display voice channels under their category header)

All other types (`0` text, `5` announcement, `15` forum, `16` media, `10/11/12` threads) we **store the IDs in a set but never display or fetch**.

### 1.6 The minimum event set we actually consume

Listen for everything (we have no choice — user accounts have no intent filter), but only **act on**:

| Event              | Action                                                      |
|--------------------|-------------------------------------------------------------|
| READY              | Build initial user object, store `session_id` + `resume_gateway_url` |
| READY_SUPPLEMENTAL | Merge inline `voice_states` into pending guild buffer       |
| GUILD_CREATE       | Add guild + voice channels + voice_states                   |
| GUILD_DELETE       | Remove guild                                                |
| GUILD_UPDATE       | Update name/icon                                            |
| CHANNEL_CREATE     | If type 2/13/4 → add to UI                                  |
| CHANNEL_UPDATE     | If type 2/13/4 → mutate; else ignore                        |
| CHANNEL_DELETE     | Remove from UI                                              |
| VOICE_STATE_UPDATE | Update per-user voice presence (who's in which voice room)  |
| VOICE_SERVER_UPDATE| Only relevant when joining voice (see §5)                   |
| RESUMED            | Confirm resume worked                                       |
| Everything else    | **Drop on the floor.** Don't parse `d`, don't allocate.     |

**Yes, we ignore `MESSAGE_CREATE` entirely.** The events still arrive over the wire (unavoidable on a user account) but we early-out on `t` before deserializing `d`. Trick: keep `d` as a raw JSON slice and only parse when `t` is whitelisted.

**Do NOT send OP 14.** abaddon sends it (`SendLazyLoad` in `discord.cpp`) for member-list display in text channels. We have no member list — sending OP 14 starts a `GUILD_MEMBER_LIST_UPDATE` stream we don't want.

---

## 2. Guild structure data flow

```
Gateway WS connect
        │
        ▼
    HELLO ─────────────────► start heartbeat loop
        │
   IDENTIFY ─────────────►
        │
        ◄───── READY          (guild ID skeletons, session_id, resume_url)
        ◄───── READY_SUPPLEMENTAL (voice_states inline per guild)
        ◄───── GUILD_CREATE   ┐
        ◄───── GUILD_CREATE   │  one per guild we're in
        ◄───── GUILD_CREATE   ┘
        ◄───── (live) CHANNEL_CREATE/UPDATE/DELETE
        ◄───── (live) VOICE_STATE_UPDATE
        ◄───── (every ~41 s) heartbeat / ACK
```

Voice channels are **delivered in `GUILD_CREATE.channels[]` inline**, not as a separate fetch. No REST call needed unless we want to resync a single guild (`GET /guilds/{id}/channels`, rarely required).

`VOICE_STATE_UPDATE` is the live event for "user X joined/left/muted voice channel Y." Payload:

```jsonc
{ "op": 0, "t": "VOICE_STATE_UPDATE", "d": {
    "guild_id": "...",
    "channel_id": "..." | null,        // null = left voice
    "user_id": "...",
    "session_id": "...",
    "self_mute": false, "self_deaf": false, "self_video": false,
    "mute": false, "deaf": false, "suppress": false,
    "member": { ... }                  // sometimes present
} }
```

When `user_id == our user_id`, the `session_id` field is **the session ID we need for the voice WS Identify** (§5). Store it.

---

## 3. Presence — appearing offline

Set `d.presence` in IDENTIFY. Values for `status`:

| Status      | Visible to others as | Receive presence events? | Notes                          |
|-------------|----------------------|--------------------------|--------------------------------|
| `online`    | Green                | Yes                      | Default if not specified       |
| `idle`      | Yellow               | Yes                      |                                |
| `dnd`       | Red                  | Yes                      |                                |
| `invisible` | **Offline (grey)**   | Yes                      | **Use this.** Connection stays full-duplex. |

**You appear fully offline to friends with `status: "invisible"`.** Voice channel presence (the "joined voice" indicator) is *separately* visible to anyone in the same guild — you can't hide it short of not joining voice.

Omitting `presence` is account-state-dependent (Discord persists last status server-side). Be deterministic: always send `status: "invisible"`. You can later mutate via OP 3 (`{ "op": 3, "d": { "since": 0, "activities": [], "status": "invisible", "afk": false } }`), but ideally send once at IDENTIFY and never again. **No custom-status activities** — those force PRESENCE_UPDATE broadcasts.

---

## 4. Heartbeat / keepalive / hibernation

- **Cadence:** every `heartbeat_interval` ms from HELLO. Typical value: **41250 ms** (41.25 s).
- **Payload:** `{ "op": 1, "d": <last_sequence_or_null> }` where `last_sequence` is the `s` field of the most recent dispatch we received.
- **Cost:** one ~30-byte WS frame every 41 s plus parsing one ACK. Negligible.
- **Hibernation:** Discord **will disconnect** if no ACK within `heartbeat_interval` ms. Options: (1) keep heartbeat running regardless of window focus, or (2) on long backgrounding, close gracefully and OP 6 RESUME via `resume_gateway_url` with the last sequence — Discord replays missed events.
- **Rate limit:** max 120 outbound events per 60 s. Nowhere near it.
- **Resume payload (OP 6):** `{ "op": 6, "d": { "token": "...", "session_id": "...", "seq": 12345 } }` to `resume_gateway_url` (not original URL).

---

## 5. Voice connection — the join sequence

```
USER CLICKS VOICE CHANNEL
   │
   │ 1. Gateway OP 4 (Voice State Update)
   ▼
{ "op": 4, "d": { "guild_id": "G", "channel_id": "C", "self_mute": false, "self_deaf": false, "self_video": false } }
   │
   ▼
   ◄── VOICE_STATE_UPDATE   (our own; gives us session_id)
   ◄── VOICE_SERVER_UPDATE  ({ token, guild_id, endpoint: "rtc.us-east1.discord.media:443" })
   │
   │ 2. Open second WS: wss://{endpoint}/?v=8
   ▼
   ◄── voice OP 8 HELLO  { "heartbeat_interval": 13750 }    ← faster than main GW
   │
   │ 3. Send voice OP 0 IDENTIFY
   ▼
{ "op": 0, "d": {
    "server_id":  "G",
    "user_id":    "U",
    "session_id": "<from VOICE_STATE_UPDATE>",
    "token":      "<from VOICE_SERVER_UPDATE>",
    "max_dave_protocol_version": 1
} }
   │
   ▼
   ◄── voice OP 2 READY { ssrc, ip, port, modes:[ "aead_aes256_gcm_rtpsize",
                                                  "aead_xchacha20_poly1305_rtpsize", ... ] }
   │
   │ 4. Open UDP socket to ip:port; send 74-byte IP discovery packet:
   │       [0x00 0x01][0x00 0x46][SSRC ×4][zeros ×64][0x00 0x00]
   │    Receive 74-byte response: parse external IP (offset 8, null-term string)
   │    and external port (last 2 bytes, big-endian).
   │
   │ 5. Voice OP 1 SELECT_PROTOCOL
   ▼
{ "op": 1, "d": {
    "protocol": "udp",
    "data": { "address": "<our external IP>", "port": <our external port>,
              "mode": "aead_aes256_gcm_rtpsize" }
} }
   │
   ▼
   ◄── voice OP 4 SESSION_DESCRIPTION { mode, secret_key: [32 bytes], dave_protocol_version }
   │
   │ 6. We can now encrypt + send RTP.
   ▼
   Speaking OP 5 (announce mic active) → start Opus encoder pipeline → RTP packets at 50 Hz.
```

### 5.1 Voice WS opcodes

| Op | Name               | Dir  | Notes                                      |
|----|--------------------|------|--------------------------------------------|
| 0  | Identify           | send |                                            |
| 1  | Select Protocol    | send |                                            |
| 2  | Ready              | recv | ssrc, ip, port, supported modes            |
| 3  | Heartbeat          | send | v8+: `{ t: epoch_ms, seq_ack: <last_seq> }` |
| 4  | Session Description| recv | secret_key (32 bytes), encryption mode     |
| 5  | Speaking           | both | bitmask: 1=mic, 2=soundshare, 4=priority   |
| 6  | Heartbeat ACK      | recv |                                            |
| 7  | Resume             | send | Reconnect within same session              |
| 8  | Hello              | recv | heartbeat_interval (~13.75 s)              |
| 9  | Resumed            | recv |                                            |
| 13 | Client Disconnect  | recv | A peer left                                |
| 21–31 | DAVE / MLS      | both | E2EE (optional; only if enabled)           |

### 5.2 RTP packet layout

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
| 0x80 (ver+flags) | 0x78 (PT=120) |      sequence number      |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                          timestamp                            |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                            SSRC                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|              encrypted Opus payload + AEAD tag + nonce        |
```

- Payload type `0x78` (120) = Discord's Opus mapping.
- Sequence increments per packet; timestamp increments by 960 (samples/packet at 48 kHz / 20 ms frame).
- Nonce (4-byte little-endian counter, padded to 24 bytes for xchacha or used directly for AES-GCM) is appended to the ciphertext for `_rtpsize` modes.

### 5.3 Encryption modes

| Mode                              | Status     | Notes                                |
|-----------------------------------|------------|--------------------------------------|
| `aead_aes256_gcm_rtpsize`         | **Preferred** | Hardware-accelerated AES-NI; fastest on Windows |
| `aead_xchacha20_poly1305_rtpsize` | Required fallback | libsodium provides this everywhere |
| `xsalsa20_poly1305*`              | Deprecated | Remove if seen                       |

Discord mandates at least one AEAD `_rtpsize` mode. Use `aead_aes256_gcm_rtpsize` when offered (every modern voice server does), fall back to `aead_xchacha20_poly1305_rtpsize`. Both in libsodium; AES-GCM also in BCrypt / OpenSSL EVP.

### 5.4 Opus on Windows

- **libopus** (BSD, official). Static link ~400 KB or use `opus.dll`. No faster alternative; every Discord client uses it.
- **Format: 48 kHz, stereo, 20 ms frames (960 samples × 2 channels).** abaddon uses 10 ms (480 samples); 20 ms halves the call rate and is what the official client uses.
- **Bitrate:** 64 kbps default (matches the channel's `bitrate` field). Range 8–510 kbps; capped per guild boost tier.
- **CPU per stream:** libopus VOIP-mode encode @ 64 kbps stereo 20 ms ≈ 0.3 ms/frame, decode ≈ 0.1 ms. At 50 fps that's ~1.5 % of one core to encode, ~0.5 % per decoded peer.
- **VAD/noise suppression (optional):** rnnoise (~1 ms per 10 ms frame). Lets us suppress sending when silent → 0 CPU + 0 bandwidth idle.
- **Jitter buffer:** required for incoming streams. 100–200 ms depth standard.

---

## 6. Read-only mode vs voice-active mode

```
IDLE STATE                                  VOICE-ACTIVE STATE
──────────                                  ──────────────────
gateway WS (open, ~41 s heartbeat)          gateway WS (open, ~41 s heartbeat)
                                          + voice WS (open, ~13.75 s heartbeat)
                                          + UDP socket (50 pps × N streams)
                                          + audio devices open (capture+playback)
                                          + Opus encoder + N decoders
                                          + rnnoise (optional)
```

Yes — **completely tear down** voice WS + UDP + audio devices + Opus state when not in a channel. On leave: (1) gateway OP 4 with `channel_id: null`, (2) close voice WS (code 1000), (3) close UDP, (4) `ma_device_uninit`, (5) `opus_encoder_destroy` / `opus_decoder_destroy`.

**Idle steady-state** = one gateway heartbeat every 41 s + discarding a trickle of events (1–5/min typical). CPU well under 0.1 %.

---

## 7. abaddon study

Repo: <https://github.com/uowuo/abaddon> — C++17 / GTK 3, MIT licensed, ~80 files under `src/discord/`.

**Voice files:**
- `src/discord/voiceclient.hpp` / `.cpp` — voice WS state machine, UDP socket, opcode enum (0–13 plus DAVE 21–31 in `VoiceGatewayOp`), `VoiceReadyData`, `VoiceSessionDescriptionData`, `UDPSocket` class with platform `_WIN32` branch.
- `src/discord/voicestate.hpp` / `.cpp` — voice presence state per user.
- `src/discord/dave.hpp` / `.cpp` — DAVE/MLS E2EE.
- `src/audio/manager.cpp` — miniaudio + libopus + (optional) rnnoise integration. 48 kHz stereo, 480-sample (10 ms) Opus frames, two VAD methods (peak gate or rnnoise probability).

**Gateway:**
- `src/discord/discord.cpp` — main client. Confirms:
  - **No intents sent** (user account behavior).
  - Builds IDENTIFY with `m_build_number` + `m_user_agent` set from settings to mimic the web client.
  - Sends OP 14 lazy-load (`SendLazyLoad`) with channel member ranges `[0,99]` and `[100,199]` *when a text channel is opened*. **We will not do this.**
  - Heartbeat in dedicated `std::thread` using `m_heartbeat_msec` from HELLO; tracks `m_heartbeat_acked` for zombie detection.

**Copy from abaddon:** web-client mimicry IDENTIFY, voice state machine (`ConnectingToWebsocket → EstablishingConnection → Connected → DisconnectedBy*`), per-user `SetUserVolume / GetSSRCOfUser` mapping (for per-peer volume sliders), jitter buffer + rnnoise VAD.

**Skip from abaddon:** text rendering / messages / members / attachments / embeds / threads / forums, OP 14 lazy load, DAVE/MLS E2EE (lots of code; set `max_dave_protocol_version: 0` or 1-without-implementing).

---

## 8. CPU-cost estimates

Reference: modern x86_64 laptop CPU (Ryzen 7 / i7, ~2023).

| Component                          | CPU (one core %) | Notes                                |
|------------------------------------|------------------|--------------------------------------|
| Gateway heartbeat (every 41 s)     | <0.01 %          | Single small WS frame                |
| Gateway event ingest, idle         | <0.05 %          | A handful of events/min discarded    |
| Voice WS heartbeat (every 13.75 s) | <0.01 %          | Only while in voice                  |
| Opus encode @ 64 kbps 20 ms        | ~1.5 %           | 50 frames/sec                        |
| Opus decode per peer               | ~0.5 %           | Linear in number of speakers         |
| AEAD AES-256-GCM en/decrypt        | <0.1 %           | AES-NI accelerated                   |
| rnnoise (optional)                 | ~1 %             | 480-sample frames                    |
| UI redraw (Skia/native, no DOM)    | <1 %             | If we draw only on event             |
| **Total idle (no voice)**          | **<0.1 %**       |                                      |
| **Total voice w/ 3 active peers**  | **3–5 %**        |                                      |

**Official Electron Discord on Windows:** 10–30 % CPU in voice, 100 MB–4 GB RAM. The gap is Chromium + V8 + DOM + GPU compositor, not the protocol work.

A native (Rust/C++/Zig) client with a non-Chromium UI (Slint, egui, Skia, native Win32, GTK, Qt) hits the totals above. **Memory target: <50 MB** — abaddon idles 30–60 MB on Windows.

---

## Citations

**Official docs:** Gateway <https://docs.discord.com/developers/topics/gateway> · Gateway events <https://docs.discord.com/developers/events/gateway-events> · Voice connections <https://docs.discord.com/developers/topics/voice-connections>

**Reverse-engineered docs:** discord-userdoccers <https://docs.discord.food/topics/gateway> · Auth/Authorization (DeepWiki) <https://deepwiki.com/discord-userdoccers/discord-userdoccers/3.2-authentication-and-authorization> · Lazy guilds (OP 14) <https://arandomnewaccount.gitlab.io/discord-unofficial-docs/lazy_guilds.html> · X-Super-Properties <https://github.com/KhafraDev/discord-verify/wiki/X-Super-Properties> · Discord-S.C.U.M <https://github.com/Merubokkusu/Discord-S.C.U.M/blob/master/docs/using/Gateway_Actions.md>

**abaddon source:** Repo <https://github.com/uowuo/abaddon> · `src/discord/voiceclient.{hpp,cpp}` · `src/discord/voicestate.{hpp,cpp}` · `src/discord/discord.cpp` · `src/audio/manager.cpp`

**Codec/libraries:** libopus <https://opus-codec.org/> · Opus 20 ms default <https://en.wikipedia.org/wiki/Opus_(audio_format)> · rnnoise <https://github.com/xiph/rnnoise> · libsodium AEAD <https://doc.libsodium.org/secret-key_cryptography/aead> · miniaudio <https://miniaud.io/>

**CPU/RAM comparison:** Discord resource-hog admission (2025/12) <https://www.windowslatest.com/2025/12/06/discord-admits-its-windows-11-app-is-a-resource-hog-tests-auto-restart-when-ram-usage-exceeds-4gb/> · Discord CPU spike thread <https://support.discord.com/hc/en-us/community/posts/360055591352-Discord-is-Eating-a-lot-of-CPU-for-some-reason>

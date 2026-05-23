# DESIGN — Wildcard: The "Household Voice Broker"

## TL;DR

Put the heavy, persistent Discord gateway connection on a Raspberry Pi (or NAS, or always-on desktop) sitting on the user's LAN. That box holds the WebSocket session 24/7, keeps the friends/channel tree warm, and exposes a tiny JSON+SSE API. The gaming laptop runs a ~5 MB native panel that just renders the tree and, when the user clicks a voice channel, asks the broker for routing info. The laptop then opens its **own** short-lived gateway and voice connection *only for the duration of the call* — direct UDP to Discord, no relay in the audio path. The Pi never touches audio. The laptop never holds an idle gateway. Same Discord account, two simultaneous sessions (which Discord explicitly supports, [up to 15](https://docs.discord.food/resources/presence)). It looks 100% like a person using Discord on a tablet *and* a PC — because functionally that's exactly what it is.

## Why this, and not the other two mavericks

The WebView-shell maverick is shipping a 200 MB Edge runtime to render a channel list. The minimum-native maverick is hand-rolling a tray menu and re-implementing all of Discord's gateway logic on the very machine that's already CPU-bound during a game. Both put the keepalive on the gaming laptop. **The keepalive is the problem.** Discord's gateway sends a heartbeat every ~41 s and the client must parse every guild/channel/presence event for every server the user is in — for a user in 30 servers, that's thousands of events per minute even while idle, every one of which has to be JSON-decoded by the CPU that's trying to render frames in Elden Ring.

Moving the persistent session off the gaming machine is the single highest-leverage move available, and *neither of the other two mavericks can do it* — they're both single-machine architectures by construction. This is the unexplored axis.

## Architecture

```
+--------------------------------------------------------+
|                  RASPBERRY PI / NAS                    |
|                                                        |
|  +----------------------------------+                  |
|  |  discord-broker (Rust, ~12 MB)   |                  |
|  |                                  |                  |
|  |  - Persistent WSS to gateway.discord.gg            |
|  |  - Parses READY, GUILD_CREATE,                     |
|  |    CHANNEL_UPDATE, VOICE_STATE_UPDATE              |
|  |  - In-memory tree: guilds -> voice channels        |
|  |  - DOES NOT touch audio                            |
|  |                                                    |
|  |  HTTP+SSE on 127.0.0.1:7777 (LAN-only, mTLS)       |
|  +----------------------------------+                  |
+----------------------|---------------------------------+
                       |  LAN (Gigabit, sub-1ms RTT)
                       |  GET /tree   -> JSON channel tree
                       |  GET /events -> SSE stream
                       |  POST /join  -> broker yields the
                       |                 token+session info
                       |                 needed for laptop's
                       |                 own short-lived
                       |                 voice connection
                       |
+----------------------V---------------------------------+
|                GAMING LAPTOP (Windows)                 |
|                                                        |
|  +----------------------------------+                  |
|  |  vc-panel.exe (Rust + Slint, ~6 MB)                |
|  |                                  |                  |
|  |  IDLE STATE:                                       |
|  |    - GPU-rendered tree view                        |
|  |    - SSE listener on LAN socket                    |
|  |    - 0 outbound internet sockets                   |
|  |    - <0.1% CPU                                     |
|  |                                                    |
|  |  CLICK-TO-JOIN STATE:                              |
|  |    - Spin up short-lived gateway WS                |
|  |    - Send Op 4 Voice State Update                  |
|  |    - Receive Voice Server Update                   |
|  |    - Open UDP to Discord media endpoint            |
|  |    - DAVE/MLS handshake, Opus encode mic input     |
|  |    - On disconnect: tear EVERYTHING down           |
|  +----------------------------------+                  |
+----------------------|---------------------------------+
                       |
                       |  Direct UDP (no relay)
                       V
              [Discord voice region]
```

Voice **media** flows directly laptop -> Discord. The broker never sees a single Opus frame. Latency is identical to a normal client. The broker only handles the *control plane*.

## Feasibility check

### Will Discord let one account hold two simultaneous sessions?

Yes. The gateway docs describe a `sessions` array on the user's presence with up to 15 entries, each tagged with platform (desktop/web/mobile/embedded). The user's overall presence is computed across all of them ([source](https://docs.discord.food/resources/presence)). Practical evidence: anyone who has ever left Discord open on their phone and their PC simultaneously is using this. The PS5 integration is literally another simultaneous session ([Discord blog](https://discord.com/blog/playstation-5-voice-integration-announcement)). The broker would identify as `desktop` and the panel can also identify as `desktop`; Discord doesn't seem to gate on uniqueness of platform string.

### Voice on two devices at once?

No — Discord enforces voice-on-one-device-at-a-time at the gateway layer ([source](https://support.discord.com/hc/en-us/community/posts/360041722612-Multiple-device-voice-connectivity)). That's *fine for us*: the broker never tries to be on a voice channel. Only the laptop does, and only while the user is actually talking.

### What about the DAVE protocol (E2EE for voice as of March 2026)?

This is a **hard requirement** as of March 2, 2026: third-party clients must implement DAVE/MLS or they cannot send/receive voice ([Discord blog](https://discord.com/blog/meet-dave-e2ee-for-audio-video), [whitepaper](https://daveprotocol.com/)). The good news: Discord open-sourced the DAVE protocol spec and reference implementation ([github.com/discord/dave-protocol](https://github.com/discord/dave-protocol/blob/main/protocol.md)). It uses MLS for group key exchange and WebRTC encoded transforms for per-frame encryption.

For the wildcard architecture, this *helps* us: MLS group state is per-call, not persistent, so it lives naturally on the laptop for the duration of the call. The broker is uninvolved. The laptop already has GPU and idle audio cycles to spare while the user is *in* a voice call (a game's audio thread is small; what's heavy is the game's render loop and physics, which don't compete with Opus encode).

### Will this flag the account?

This is the most important question and the answer is "low risk, with discipline". Three reasons:

1. **No "selfbot" behavior.** A selfbot is an account that automates messaging, reactions, friend requests, etc. We do *none* of that. We just hold gateway sessions and join voice channels in response to direct user clicks. That's indistinguishable from "user has Discord on two devices".
2. **No accelerated request patterns.** Discord's anomaly detection cares about request rate and timing patterns ([discussion](https://medium.com/@scarlettokun/selfbots-explanation-and-perspectives-51d437ce0849)). Our broker is *slower* than the official client, not faster. It heartbeats at the protocol-specified interval and reacts only to user input.
3. **Honest client identifier.** We send a plausible browser identify payload (the same one [discord.js](https://discord.js.org) and most third-party clients use). We do not impersonate the desktop client's protocol-version-specific behaviors. Abaddon ([reference repo](https://github.com/uowuo/abaddon)) has been running this pattern for years without flagging accounts.

The risk that *does* exist: if Discord rolls out attestation (already shipped in mobile via SafetyNet / Play Integrity), the laptop-side voice client may eventually need a real signed handshake. The broker is unaffected by this because it's not the one in the voice call. Two-machine split actually **isolates** the attestation surface to a single, short-lived process.

## Prototype path (1-2 weekends)

**Stage 1 — broker only.** Rust + `tokio-tungstenite`. Connect to gateway, parse READY, dump guild + voice channel tree to stdout. ~300 lines. Validate that the connection stays alive under typical idle conditions for 72 hours.

**Stage 2 — local API.** Add an `axum` server on 127.0.0.1:7777. Expose `GET /tree` and an SSE stream at `GET /events`. mTLS using a self-signed cert pair generated on first run. Verify from the laptop with `curl`.

**Stage 3 — laptop panel.** Slint or egui (both render on GPU via wgpu/D3D). Window stays under 8 MB RAM. Hits `/tree` on launch, subscribes to `/events`. Renders nothing fancy — just a tree.

**Stage 4 — voice path.** Reuse `serenity-voice-model` or port abaddon's voice code. Implement Op 4 voice state update, voice server update parse, UDP socket open. Validate non-DAVE join against a test server.

**Stage 5 — DAVE.** Port Discord's open-source DAVE reference (it's in C++, but the protocol is small enough to write idiomatic Rust in ~1500 LOC). This is the long pole.

**Stage 6 — single user, single laptop deploy.** If the user doesn't actually have a Pi, the broker can run on the laptop too in a process with `IDLE_PRIORITY_CLASS` and a HARD CPU-affinity pin to one efficiency core. This is the "graceful degradation" mode.

## Why this is better than each rejected sibling

- It's not coupled to the desktop UI choice (could pair with WebView shell *or* minimum-native panel as the laptop component — actually composes well with them).
- It's not coupled to the game (no overlay hooks, no anti-cheat risk).
- It's not coupled to specific Discord features (no RPC pipe, no overlay).
- It does the right thing in the limit: as the gaming session gets more intense, the laptop's Discord footprint goes to zero (the panel can be minimized to tray; the SSE socket is one TCP keepalive on the LAN).
- It composes with **household scaling**: the broker can serve every device in the house. The user's roommate, partner, kid all get the same low-CPU panel without each running their own gateway.

## Risks and unknowns

- **Broker dependency.** If the Pi reboots or the LAN drops, the panel can't update its tree. Mitigation: the panel caches the last tree to disk and shows it stale-but-functional. Voice join still works because the panel can fall back to a direct gateway connect if the broker is unreachable for >5s.
- **DAVE engineering load.** This is real work, ~2000 LOC of MLS plumbing. Every voice-capable third-party client now has this problem; we're not specially burdened.
- **Multi-account is awkward.** If the user has two Discord accounts they'd want two broker sessions. Trivially supported by running two broker processes, less trivially supported by a single broker with token-per-session routing. Punt to v2.
- **Discord can change the rules.** They could ratchet on attestation, rate limits, IP reputation. Same risk faced by every third-party client; not unique to this design.

## Considered and rejected (with one-line reasons)

1. **Speaking Discord's own RPC/IPC pipe (`\\.\pipe\discord-ipc-N`)** — Rejected. Requires the official Discord client to already be running ([docs](https://docs.discord.com/developers/topics/rpc)), which defeats the whole CPU goal; you'd be paying for Electron *plus* a custom UI on top.

2. **GPU-resident UI as the headline architecture** — Worth doing as the *rendering* layer (Slint/egui both do this) but it doesn't solve the actual CPU sink, which is the gateway event stream parser. GPU rendering is table stakes here, not the wildcard.

3. **Game-overlay integration via DXGI present hook** — Rejected. BattlEye and EAC have flagged Discord's *own* overlay historically ([BattlEye support](https://www.battleye.com/support/), [forum reports](https://forum.smartlydressedgames.com/t/will-discord-overlay-trigger-battleye-or-a-ingame-ban/780)); a homegrown overlay is straight-up account-ban risk in some games. Not worth it for a channel list.

4. **Hand off voice entirely to the phone via deeplink** — Rejected. Discord has no documented `discord://` URI for "join voice channel X in guild Y" ([unofficial list](https://gist.github.com/ghostrider-05/8f1a0bfc27c7c4509b4ea4e8ce718af0)); even if it existed, the latency of "unlock phone -> open Discord -> tap channel" is too high to be the primary join mechanism. Could be a secondary fallback.

5. **AI-driven simplification ("join your friends" button)** — Rejected as primary architecture. A rules engine over the broker's friend-presence stream gets 90% of the value with 1% of the code; an LLM here is over-engineering. Worth a footnote in v2: "Most Joined" pinned channels.

6. **QUIC-native client betting on Discord migrating** — Rejected. Discord ran [QUIC tests in 2021](https://github.com/discord/discord-api-docs/discussions/3818) and never publicly committed to a gateway migration. Building on speculation about a migration that might never ship is a 2027 problem, not a 2026 problem. Their voice path *is* already UDP, which is the part that mattered for latency anyway.

7. **Pose as a Discord-compatible RPC server other apps connect to** — Rejected. Interesting but solves a problem nobody has and adds a huge attack surface (anything that thinks it's talking to real Discord). No CPU win.

8. **Steam Link / Remote Play style protocol carrying Discord** — Rejected after consideration. Steam Link is engineered to ship 4K video frames at <50ms ([Steam support](https://help.steampowered.com/en/faqs/view/3E3D-BE6B-787D-A5D2)), which is wildly over-spec for a channel tree. A 30-line SSE endpoint is the right tool. But the *idea* — let an idle box do the work and let the laptop be a thin client — is what the chosen design borrows.

## Citations

- abaddon reference client (uowuo/abaddon) — [github.com/uowuo/abaddon](https://github.com/uowuo/abaddon)
- Discord DAVE protocol spec and reference impl — [github.com/discord/dave-protocol](https://github.com/discord/dave-protocol/blob/main/protocol.md)
- Discord DAVE whitepaper — [daveprotocol.com](https://daveprotocol.com/)
- "Meet DAVE" Discord blog — [discord.com/blog/meet-dave-e2ee-for-audio-video](https://discord.com/blog/meet-dave-e2ee-for-audio-video)
- Minimum client versions / DAVE deadline — [Discord support article](https://support.discord.com/hc/en-us/articles/38025123604631-Minimum-Client-Version-Requirements-for-Voice-Chat)
- Voice connections protocol — [docs.discord.food/topics/voice-connections](https://docs.discord.food/topics/voice-connections)
- Gateway events — [docs.discord.com/developers/events/gateway-events](https://docs.discord.com/developers/events/gateway-events)
- Presence / sessions array — [docs.discord.food/resources/presence](https://docs.discord.food/resources/presence)
- Multi-device voice limitation — [Discord support post](https://support.discord.com/hc/en-us/community/posts/360041722612-Multiple-device-voice-connectivity)
- PlayStation 5 Discord integration announcement — [discord.com/blog/playstation-5-voice-integration-announcement](https://discord.com/blog/playstation-5-voice-integration-announcement)
- Discord IPC / RPC pipe docs — [docs.discord.com/developers/topics/rpc](https://docs.discord.com/developers/topics/rpc) and [robins.one notes](https://robins.one/notes/discord-rpc-documentation.html)
- "An unofficial list of discord app protocol routes" — [gist by ghostrider-05](https://gist.github.com/ghostrider-05/8f1a0bfc27c7c4509b4ea4e8ce718af0)
- Discord QUIC discussion (2021, no migration since) — [discord/discord-api-docs#3818](https://github.com/discord/discord-api-docs/discussions/3818)
- Selfbots policy and detection patterns — [Discord support article](https://support.discord.com/hc/en-us/articles/115002192352-Automated-User-Accounts-Self-Bots), [Scarletto Medium post](https://medium.com/@scarlettokun/selfbots-explanation-and-perspectives-51d437ce0849)
- BattlEye / EAC overlay risk — [BattlEye support](https://www.battleye.com/support/), [SDG forum thread](https://forum.smartlydressedgames.com/t/will-discord-overlay-trigger-battleye-or-a-ingame-ban/780)
- Opus encode on ARM benchmarks (validates Pi can keep up if it ever needed to, though we don't ask it to) — [xiph.org opus mailing list](http://lists.xiph.org/pipermail/opus/2013-December/002455.html)
- Steam Remote Play protocol design (inspiration only) — [Steam support article](https://help.steampowered.com/en/faqs/view/3E3D-BE6B-787D-A5D2)

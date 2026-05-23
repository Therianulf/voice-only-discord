# Voice-receive de-risk spike

The vodiscord plan (`/Users/blarson/.claude/plans/mellow-riding-flute.md`) is
gated on this passing. If `discord.py-self` + `discord-ext-voice-recv` cannot
receive decoded PCM frames from a voice channel using a user-account token,
the Python path is dead and we need to revisit the bake-off.

## Setup (already done)

The isolated spike venv is at `../.venv-spike/`. It has:
- `discord.py-self==2.1.0`
- `discord-ext-voice-recv==0.5.2a179`
- transitive deps (PyNaCl, davey, curl_cffi, aiohttp…)

Recreate it with:
```sh
/opt/homebrew/opt/python@3.12/bin/python3.12 -m venv .venv-spike
.venv-spike/bin/pip install --upgrade pip
.venv-spike/bin/pip install 'discord.py-self[voice]==2.1.0' 'discord-ext-voice-recv'
```

## Run

You need two things:

1. **Your Discord user token.** From a logged-in browser, open DevTools →
   Application → Local Storage → `https://discord.com` → look for a `token`
   key. Or, in the console (works on stable web client):
   ```js
   webpackChunkdiscord_app.push([[''],{},e=>{for(let t in e.c)try{let n=e.c[t].exports;if(n?.default?.getToken)return console.log(n.default.getToken())}catch{}}]);
   ```

2. **A voice channel ID** you can join. Enable Developer Mode in Discord
   (User Settings → Advanced → Developer Mode), then right-click any voice
   channel → Copy Channel ID.

Then, from the repo root:

```sh
DISCORD_TOKEN='<your-token>' \
VOICE_CHANNEL_ID='<your-channel-id>' \
.venv-spike/bin/python spike/voice_recv_spike.py
```

While the spike is running, have a friend talk in that voice channel for
~20 seconds. Or use a second account.

## What success looks like

```
Logged in as you (12345...)
Joining: MyServer -> general
Listening for 30s — please TALK in the channel now.

=== RESULTS ===
  friend_username                  812 frames  (5078.4 KB pcm)
  another_friend                   142 frames  (888.5 KB pcm)

  TOTAL: 954 PCM frames

SPIKE PASSED — voice receive works on this selfbot token.
```

Any FAIL or INCONCLUSIVE line means we need to investigate before continuing
the project. Common reasons:
- `FAIL: token rejected` — token wrong or expired.
- `FAIL: channel.connect() raised: ...` — selfbot voice-connect refused
  (very bad — biggest risk in the plan).
- `INCONCLUSIVE / no frames received` — likely nobody talked. Retry with
  someone speaking.

## After

Once the spike passes, you can delete `.venv-spike/` and the `spike/` dir.
The main venv (`.venv/`) and the rest of the project don't depend on it.

## Optional knobs

- `LISTEN_SECONDS=60` — listen longer than the default 30 s.

## Troubleshooting

- On macOS, microphone is not needed for *receiving* — only for transmitting.
  This spike only tests receive, so the OS won't prompt for mic access.
- If you see `ImportError: ... discord.ext ... voice_recv` — you're running
  from the wrong venv. Make sure you're using `.venv-spike/bin/python`,
  not `.venv/bin/python`.

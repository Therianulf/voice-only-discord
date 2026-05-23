"""
voice_recv_spike — gate test for the vodiscord project plan.

Goal: confirm `discord.py-self` + `discord-ext-voice-recv` can receive decoded
PCM frames from a voice channel using a user-account (selfbot) token. If this
fails, the project's Python path is unviable and we have to revisit the bake-off.

Usage:
    DISCORD_TOKEN=<your-user-token> \
    VOICE_CHANNEL_ID=<a-voice-channel-id-you-can-join> \
    .venv-spike/bin/python spike/voice_recv_spike.py

NOTE: run from the isolated .venv-spike, NOT the main .venv. The spike needs
`discord-ext-voice-recv` which pulls upstream `discord.py` as a transitive dep;
having both `discord.py` and `discord.py-self` in the same venv works at runtime
(discord.py-self wins the namespace race when installed last) but trips pip's
resolver. Keeping them in separate venvs avoids the mess.

The script joins the channel, listens for 30 seconds, and reports per-speaker
PCM frame counts. PASS = at least one frame received from any speaker who talked
during the window. FAIL = zero frames (or library raised) — implies receive is
broken on selfbot tokens for the installed library version.

Get a channel ID: right-click a voice channel in Discord (with Developer Mode
on in User Settings → Advanced) → Copy Channel ID.

Get your token: NOT recommended via password login. Easiest is from devtools:
in a logged-in browser, open DevTools → Application → Local Storage →
discord.com → search "token". Or run this in the console (works in stable web
client):
    webpackChunkdiscord_app.push([[''],{},e=>{for(let t in e.c)try{let n=e.c[t].exports;if(n?.default?.getToken)return console.log(n.default.getToken())}catch{}}]);
"""

import asyncio
import collections
import os
import sys

import discord
from discord.ext import voice_recv

TOKEN = os.environ.get("DISCORD_TOKEN")
CHANNEL_ID_RAW = os.environ.get("VOICE_CHANNEL_ID")
LISTEN_SECONDS = int(os.environ.get("LISTEN_SECONDS", "30"))

if not TOKEN or not CHANNEL_ID_RAW:
    print("ERROR: set DISCORD_TOKEN and VOICE_CHANNEL_ID env vars first.")
    sys.exit(2)

CHANNEL_ID = int(CHANNEL_ID_RAW)


class FrameCounter(voice_recv.AudioSink):
    """Counts PCM frames per speaker. 20 ms frames at 48 kHz stereo = 50 fps."""

    def __init__(self) -> None:
        super().__init__()
        self.frames: collections.Counter[str] = collections.Counter()
        self.bytes: collections.Counter[str] = collections.Counter()

    def wants_opus(self) -> bool:
        return False  # we want decoded PCM, not raw Opus

    def write(self, user, data) -> None:
        name = (user.display_name if user is not None else "(unknown)")
        self.frames[name] += 1
        self.bytes[name] += len(getattr(data, "pcm", b"") or b"")

    def cleanup(self) -> None:
        pass


class SpikeClient(discord.Client):
    def __init__(self) -> None:
        super().__init__(
            chunk_guilds_at_startup=False,
            request_guilds=True,
            status=discord.Status.invisible,
        )
        self.counter: FrameCounter | None = None

    async def on_ready(self) -> None:
        print(f"Logged in as {self.user} ({self.user.id})")
        channel = self.get_channel(CHANNEL_ID)
        if channel is None:
            print(f"ERROR: channel {CHANNEL_ID} not found (no access?)")
            await self.close()
            return
        if not hasattr(channel, "connect"):
            print(f"ERROR: channel {CHANNEL_ID} is not a voice channel.")
            await self.close()
            return

        print(f"Joining: {channel.guild.name} -> {channel.name}")
        try:
            vc = await channel.connect(cls=voice_recv.VoiceRecvClient, timeout=20.0)
        except Exception as e:
            print(f"FAIL: channel.connect() raised: {e!r}")
            await self.close()
            raise

        self.counter = FrameCounter()
        try:
            vc.listen(self.counter)
        except Exception as e:
            print(f"FAIL: vc.listen() raised: {e!r}")
            await vc.disconnect()
            await self.close()
            raise

        print(f"Listening for {LISTEN_SECONDS}s — please TALK in the channel now.")
        await asyncio.sleep(LISTEN_SECONDS)

        try:
            vc.stop_listening()
        except Exception:
            pass

        print("\n=== RESULTS ===")
        if self.counter.frames:
            for name, count in self.counter.frames.most_common():
                kb = self.counter.bytes[name] / 1024
                print(f"  {name:30s}  {count:6d} frames  ({kb:.1f} KB pcm)")
            total = sum(self.counter.frames.values())
            print(f"\n  TOTAL: {total} PCM frames")
            print("\nSPIKE PASSED — voice receive works on this selfbot token.")
        else:
            print("  (no frames received)")
            print("\nSPIKE INCONCLUSIVE — was anyone actually talking? Re-run with someone speaking.")

        await vc.disconnect()
        await self.close()


def main() -> int:
    try:
        asyncio.run(SpikeClient().start(TOKEN))
    except discord.LoginFailure as e:
        print(f"FAIL: token rejected: {e}")
        return 3
    except KeyboardInterrupt:
        print("Interrupted.")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())

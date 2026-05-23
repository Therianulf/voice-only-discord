# BLOCKER Research: Discord ToS and Account-Ban Risk for a Custom User Client

## TL;DR

- A custom user-account Discord client is **not explicitly named** in the ToS but sits under prohibitions on "unauthorized software designed to modify the services," reverse engineering, and the self-bot rule. [Community Guidelines Rule 14](https://discord.com/guidelines): "Do not use self-bots or user-bots. Each account must be associated with a human, not a bot."
- Real-world enforcement is **driven by anti-spam heuristics**, not deliberate hunts for unofficial clients. A Discord infra lead stated they are "[never trying to ban third party clients (that aren't self-bots)](https://news.ycombinator.com/item?id=28435490)."
- Third-party clients **trip the spam filter more often** than the official client. Common outcomes: forced password resets and temporary locks, usually appealable in under 24h.
- For a human-driven, voice-only client mimicking the web client's IDENTIFY/headers and avoiding highest-risk surfaces (mass guild joins, friend churn, message scraping, DM bursts), risk is **non-trivial but manageable** — similar to [abaddon](https://github.com/uowuo/abaddon) or [Ripcord](https://news.ycombinator.com/item?id=25217170).
- Permanent account loss is unlikely but possible. **Do not use your main account for the first weeks of testing.**

---

## 1. What the rules actually say (2024–2026)

The current [Discord Terms](https://discord.com/terms) do **not** use the words "self-bot" or "alternative client." They prohibit:

> "scraping our services... including by using any robot, spider, crawler, scraper, or other automatic device..."
>
> "using any unauthorized software designed to modify the services"
>
> "reverse engineer or decompile our software or services..."

A human-driven custom client isn't scraping or automation, so the binding hooks are the modification/reverse-engineering clauses — both broad enough to give Discord discretion.

The [Community Guidelines](https://discord.com/guidelines) sharpen this:

- **Rule 13:** "Do not send unsolicited bulk messages..."
- **Rule 14:** "Do not use self-bots or user-bots. **Each account must be associated with a human, not a bot.**"
- **Rule 15:** "Do not engage with our service in an inauthentic way."

The [Platform Manipulation Policy Explainer](https://discord.com/safety/platform-manipulation-policy-explainer) is the strictest source:

> "Modifying a user account to perform automated actions — regardless of the type of action"
>
> "Making modifications to the Discord client for the purpose of spam or any other reason is not allowed"
>
> "Using any type of client modification that alters the appearance or layout of Discord"
>
> "Operating a user or bot account with the intention of evading our anti-spam system"

This explainer explicitly bans **client modifications regardless of purpose**. Read strictly, a custom client qualifies. Read narrowly — the way Discord enforces — what matters is whether the account is *automated* and whether traffic *looks spam-like*.

**Self-bot vs alternative client.** [Userdoccers](https://docs.discord.food/intro): "Automating user accounts is against the platform Terms of Service, so doing so unsafely might get you banned." Self-bot = account acts without a human button-press. Alternative client = human drives every action; software only renders data and forwards gestures.

Discord infra lead [zorkian](https://news.ycombinator.com/item?id=28435490) said publicly: "we are never trying to ban third party clients (that aren't self-bots)." That matches the *enforcement record*, not the *text of the rules*. Not a license — only a description of current heuristic tuning.

---

## 2. Recent enforcement patterns (2023–2026)

Discord rarely announces enforcement campaigns. What is well-documented:

- **Spam-filter false positives dominate.** Across [abaddon](https://github.com/uowuo/abaddon), [Ripcord](https://news.ycombinator.com/item?id=25217170), and [discord.py-self](https://pypi.org/project/discord.py-self/) reports the pattern is the same: token invalidation → "suspicious activity" message → forced password reset → if you log in too fast or from a new IP, the account gets disabled.
- **Behaviors that reliably trip the filter:** rapid join/leave of many guilds, friend-list churn, opening many DMs in a short period, file-upload sprees, sending many messages from a new account, missing/stale `X-Super-Properties` header.
- **Vencord/BetterDiscord:** the [Vencord FAQ](https://vencord.dev/faq/) states "Client modifications are against Discord's Terms of Service" but "Discord is pretty indifferent about them and there are **no known cases of users getting banned for using client mods**!" Risk appears only when plugins do something abusive (notably `FakeNitro`-style streaming, which has produced bans).
- **Self-bot libraries (discum, discord.py-self):** terminate accounts regularly — but bans correlate with automation behavior (rate-limit violations, behavioral patterns), not mere library use.
- **Abaddon-specific:** the one high-profile report, [discussion #84](https://github.com/uowuo/abaddon/discussions/84), is a user whose throwaway account was disabled with this Discord reason text: "Sending a large number of direct messages in a short span of time" and "Automating your user account or self-botting." The maintainer's response: "Unfortunately accounts being locked/disabled/forced password reset just comes with the territory of using unofficial clients." A more recent [issue #349 (Feb 2025)](https://github.com/uowuo/abaddon/issues) reports an account flagged after file uploads.

The pattern: **Discord rarely bans for *what client you use*; it bans for *what the resulting traffic looks like*.** Unofficial clients are over-represented in bans because they (a) often miss analytics/super-properties headers, (b) reconnect or re-identify in ways the web client doesn't, and (c) are disproportionately used by power users who *also* push abuse limits.

---

## 3. abaddon's stance

The [abaddon README](https://github.com/uowuo/abaddon/blob/master/README.md) states: "Abaddon tries its best (though is not perfect) to make Discord think it's a legitimate web client." Their mitigations: browser User-Agent; gateway `IDENTIFY` payload matching the web client; API v9 endpoints exclusively; no endpoints the web client doesn't call.

The README also warns: "Discord likes disabling accounts/forcing them to reset their passwords if they think the user is a spam bot." It recommends using the official client for joining/leaving guilds, frequent reconnects, starting DMs, and friend-list operations.

The project does **not** claim ToS compliance. The maintainer's position: third-party clients are technically a grey-area violation, rarely enforced, and recovery via support ticket is usually possible.

---

## 4. Risk gradient by behavior (least → most risky)

**Tier 1 — Effectively zero marginal risk**

- **A. Gateway connect, identify as web client, send no events.** What abaddon does at idle. Discord cannot easily distinguish a silent gateway connection from a browser tab, *provided* the `IDENTIFY` payload, `X-Super-Properties` header, and TLS fingerprint are credible. Per [Userdoccers](https://docs.discord.food/intro), the super-properties header is "highly recommended due to its significance in anti-abuse systems."

**Tier 2 — Low risk**

- **B. Subscribe only to guild-create / guild-update (no message_create).** Fewer events is *quieter*, not louder. Watch-out: skipping `READY_SUPPLEMENTAL` or lazy-guild subscriptions makes your session shape distinguishable — distinguishable, not ban-triggering. **Risk: low.**
- **C. Joining a voice channel via voice gateway.** The user's actual goal. The voice-gateway flow (op 4 → endpoint → UDP) is identical to web and mobile clients. No public record of voice-join behavior alone triggering bans; Discord's anti-abuse focus is text/DM/guild activity, not VOIP RTP. **Risk: low.** Caveat: don't join/leave many voice channels per minute.

**Tier 3 — Medium risk**

- **D. Invisible / appear-offline while connected.** Invisible is a supported feature, fine by itself. Complication: per [Userdoccers](https://docs.discord.food/resources/presence) the gateway leaks invisible-vs-truly-offline. Long-term invisible *plus* 24/7 uptime, no typing, no idle/away transitions = weak fingerprinting signal, not a known ban trigger. **Risk: medium-low.**
- **E. Multiple parallel sessions (custom client + phone).** Official web/desktop/mobile clients are *built* to coexist. Risk arises only from **inconsistent client properties or IPs** clustering as one suspicious actor. Same residential IP + consistent properties = fine. VPS/datacenter IPs or mismatched super-properties = elevated. **Risk: medium.**

**Tier 4 — Don't do this**

- Mass guild-member chunk requests across many guilds in parallel.
- Friends-list or DM-channel enumeration at speed.
- Gateway reconnect in a tight loop.
- Sending messages without preceding `TYPING_START`.
- Reusing the same token from multiple IPs simultaneously.

[Userdoccers](https://docs.discord.food/intro) warns: "API users that regularly hit and ignore rate limits will have their API keys revoked, and be blocked from the platform."

---

## 5. Mitigation tactics

Synthesized from abaddon, Ripcord, and [Userdoccers](https://docs.discord.food/intro):

1. **Mimic the web client on the wire:** User-Agent, `X-Super-Properties` (base64-JSON with up-to-date `client_build_number`), gateway `IDENTIFY` properties, presence payload, capabilities bitfield.
2. **Use API v9 endpoints only.** Don't call endpoints the web client doesn't.
3. **Keep super-properties fresh** — stale `client_build_number` is the most common giveaway.
4. **Back off on gateway reconnects;** no tight loops.
5. **Don't issue privileged calls from this client** — defer guild join/leave, friend ops, DM creation, profile edits to the real client (abaddon's README recommends this).
6. **Respect rate limits and `Retry-After`.** Don't parallelize REST beyond the web client.
7. **Use a residential IP** — home Wi-Fi on the gaming laptop. Avoid VPN/VPS.
8. **Store token in OS keychain**, never plaintext. Leaked tokens get auto-revoked by Discord's secret scanners.
9. **Don't post screenshots revealing the unofficial client** in unrelated servers — server mods may enforce.
10. **Set recovery email + phone + 2FA** so a forced password reset is a 5-minute fix, not a permanent loss.

---

## 6. Bottom line

Building a voice-only, human-driven, web-client-mimicking Discord client is **not on the most-dangerous end of the third-party-client spectrum** — it is on the *safer* end. The user is not automating, not scraping messages, not modifying the official binary, and not doing any of the behaviors that produce most documented bans (mass DM, friend-list churn, guild join/leave bursts, file-upload sprees).

That said, **the risk is not zero.** Three honest takeaways:

1. **Forced password resets are likely** at some point. Discord's spam heuristics catch official-client users too; unofficial clients trip them more. Working email + 2FA recovery turns this into an annoyance, not a catastrophe.
2. **The literal text of Discord's policies prohibits "client modifications regardless of purpose"** — Discord has discretion to disable the account at any time with no obligation to reinstate. Most affected accounts get restored on appeal within 24h ([Userdoccers](https://docs.discord.food/intro), [HN](https://news.ycombinator.com/item?id=28435490), [abaddon #84](https://github.com/uowuo/abaddon/discussions/84)), but there is no SLA.
3. **Permanent account loss is a tail risk, not a routine outcome.** Across abaddon (~5 years), Ripcord (~5 years), and Vencord/BetterDiscord (millions of installs), even visible third-party tools rarely produce permanent bans absent abusive behavior.

**Recommendation:** treat the first 4–6 weeks as probation. Develop and test against a throwaway account (created in the official client, aged a week or two, phone-verified with a non-VoIP number — VoIP numbers are themselves a flag). Migrate to the main account only after sustained clean operation. Keep the official mobile app installed and signed in so account recovery stays easy.

If the user's main account holds anything irreplaceable (long DM history, paid Nitro, important server ownership, Boost history), [Vencord's FAQ](https://vencord.dev/faq/) advice applies verbatim: "if your account is very important to you and it getting disabled would be a disaster for you, you should probably not use any client mods." Use a secondary account, or accept the risk consciously.

---

## Citations

- [Discord Terms of Service](https://discord.com/terms)
- [Discord Community Guidelines](https://discord.com/guidelines)
- [Discord Platform Manipulation Policy Explainer](https://discord.com/safety/platform-manipulation-policy-explainer)
- [abaddon README](https://github.com/uowuo/abaddon/blob/master/README.md)
- [abaddon Discussion #84 — Discord account disabled after logging in](https://github.com/uowuo/abaddon/discussions/84)
- [abaddon Issues](https://github.com/uowuo/abaddon/issues)
- [HN: Discord disallows third-party clients (zorkian quote)](https://news.ycombinator.com/item?id=28435490)
- [HN: Why ban people for using Ripcord?](https://news.ycombinator.com/item?id=25217170)
- [Vencord FAQ](https://vencord.dev/faq/)
- [Discord Userdoccers — Introduction](https://docs.discord.food/intro)
- [Discord Userdoccers — Presence](https://docs.discord.food/resources/presence)
- [discord.py-self on PyPI](https://pypi.org/project/discord.py-self/)
- [Socket.dev — Malicious pycord-self package](https://socket.dev/blog/malicious-pypi-package-targets-discord-developers-with-token-theft-and-backdoor)
- [discord-userdoccers GitHub](https://github.com/discord-userdoccers/discord-userdoccers)

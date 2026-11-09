# Getting started: your accounts, step by step

This is the guide for first-timers. It takes you from nothing to **a voice agent you can talk to in your
browser** (needs only LiveKit), then to **a real phone call** (adds Twilio). Do the parts in order; each
ends with a way to check it worked.

> Provider websites change. Button names below are what the docs and consoles said when this was
> written; if a label differs, look for the closest one, and check the linked official docs. Prices and
> free allowances change too, so confirm them on the provider's pricing page before relying on them.

<!-- toc:start -->
## Table of contents

- [What you need, and what it costs](#what-you-need-and-what-it-costs)
- [Part 1: LiveKit (required)](#part-1-livekit-required)
  - [1.1 Create a LiveKit Cloud project](#11-create-a-livekit-cloud-project)
  - [1.2 Put the values into Voizy](#12-put-the-values-into-voizy)
  - [1.3 Check it works: a browser test call](#13-check-it-works-a-browser-test-call)
  - [1.4 What the free plan covers (read this before you wonder why it stopped)](#14-what-the-free-plan-covers-read-this-before-you-wonder-why-it-stopped)
- [Part 2: Twilio (only for real phone calls)](#part-2-twilio-only-for-real-phone-calls)
  - [2.1 Create the account and get a number](#21-create-the-account-and-get-a-number)
  - [2.2 Know the trial limits (they explain most first-call surprises)](#22-know-the-trial-limits-they-explain-most-first-call-surprises)
  - [2.3 Allow calling your country](#23-allow-calling-your-country)
  - [2.4 Connect Twilio in Voizy](#24-connect-twilio-in-voizy)
  - [2.5 Your first real calls](#25-your-first-real-calls)
- [If it doesn't work](#if-it-doesnt-work)
- [Optional alternatives](#optional-alternatives)
- [When you're done testing](#when-youre-done-testing)
<!-- toc:end -->

## What you need, and what it costs

| You need | For | Cost |
|---|---|---|
| **Voizy** (this repo) | everything | Free, open source |
| **Docker** with Compose v2 | running Voizy | Free |
| **A LiveKit Cloud account** | audio rooms, SIP, and (optionally) hosted speech and language models | Free plan to start. Its included allowances are **hard caps** (see below) |
| **A Twilio account** | a phone number and the phone network (only for real calls) | Trial credit to start; you may need to upgrade for some features |
| A browser, microphone and **headphones** | the browser test call | Free. Headphones stop the agent hearing itself |

You can stop after Part 1 and still have a complete, working voice agent. Phone numbers are optional.

---

## Part 1: LiveKit (required)

LiveKit carries the audio between the caller and the agent, and runs the SIP side of phone calls. In
this setup you run the voice worker yourself (in Docker); LiveKit Cloud is just the real-time service
it connects to.

### 1.1 Create a LiveKit Cloud project

1. Go to <https://cloud.livekit.io> and sign up (a free plan is enough to start).
2. Create a new **project** when prompted. Pick any name.
3. Open the project's **Settings**. You need three values:
   - the **Project URL**, which looks like `wss://your-project-name.livekit.cloud` (starts with `wss://`);
   - an **API key** and its **API secret**: open **Settings → Keys** and create a key. **Copy the
     secret straight away**; LiveKit may not show it again. If you lose it, create a new key.

Official docs: [Project management](https://docs.livekit.io/reference/developer-tools/livekit-cli/projects/)
and [Connecting to LiveKit](https://docs.livekit.io/intro/basics/connect/).

### 1.2 Put the values into Voizy

In Voizy open **Settings → LiveKit**, enter the URL, API key and API secret, and press **Test
connection**. A success message means Voizy reached your project with those keys. The voice worker
notices the saved connection within a few seconds; you do not need to restart anything.

(You can instead put `LIVEKIT_URL`, `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET` in `.env`; those win
over anything saved in Settings.)

### 1.3 Check it works: a browser test call

1. **Agents → New agent**, name it, create.
2. In the editor press **Start call** in the *Test call* panel and allow the microphone when your
   browser asks. (Browsers allow the microphone on `http://localhost`; anywhere else you need HTTPS.)
3. The agent should greet you within a couple of seconds. Talk to it; you will see the transcript and a
   response-time chart for each turn.

If nobody greets you, see [If it doesn't work](#if-it-doesnt-work).

### 1.4 What the free plan covers (read this before you wonder why it stopped)

By default each agent's speech recognition, language model and voice run through **LiveKit Inference**,
which uses your LiveKit plan's allowance. LiveKit's current
[quotas and limits](https://docs.livekit.io/deploy/admin/quotas-and-limits/) list, for the free **Build**
plan, a small Inference allowance (about $2.50 when this was written) and say Build's allowances are
**hard caps**: when they run out, requests fail (HTTP 429, "credit quota exceeded") until the next period or
until you upgrade. In testing, the language-model credits ran out after a day of heavy test calls, while the
Billing page still listed $0.00 for everything and no "remaining" figure. That is
plenty for trying things out, not for heavy use.

**Concurrency limits on the free plan.** LiveKit's console (project **Settings → Usage and limits**) shows
the fixed limits and your peak usage over the past 7 days. When this was written the free Build plan
allowed about **5 concurrent agent sessions**, **5 concurrent Twilio participants**, **5 concurrent
connections per speech-recognition and voice model**, and about **100 requests per minute per language
model**. In practice that is roughly five calls at once; a sixth fails. Keep **Calls at the same time**
on a campaign at **5 or less** on the free plan. Check that page when calls fail with "too many requests": it shows
which limit you are near. If the message says credits are used up, see the next paragraph.

Your options when you outgrow it: upgrade the LiveKit plan, or give an agent **your own provider keys**
so those components skip Inference: save a Deepgram, OpenAI, Google AI or Cartesia key in
**Settings**, then in the agent's *Voice & models* tab choose **Connect via → My … key**.
The "agent session minutes" in LiveKit's plans are for agents *hosted* on LiveKit Cloud; Voizy's worker
runs on your own machine or server, so those don't apply to you.

---

## Part 2: Twilio (only for real phone calls)

Twilio provides the phone number and connects it to the phone network. Voizy then configures the
Twilio-to-LiveKit connection for you through Twilio's and LiveKit's APIs.

### 2.1 Create the account and get a number

1. Sign up at <https://www.twilio.com/try-twilio>. You verify your email and your own mobile number.
   That number becomes a **verified** number automatically.
2. In the Twilio Console get a **voice-capable phone number** (the trial offers one; the console
   guides you, or use *Phone Numbers → Manage → Buy a number*). On a trial the number is usually
   assigned to you rather than chosen.
3. Find your credentials on the Console home page, in the account info area: **Account SID** (starts
   with `AC`) and **Auth Token** (click to reveal). Treat the token like a password.

Official docs: [Twilio free trial](https://www.twilio.com/docs/usage/tutorials/how-to-use-your-free-trial-account).

### 2.2 Know the trial limits (they explain most first-call surprises)

Per Twilio's documentation at the time of writing, a trial account:
- expires after about **30 days** and has limited free credit;
- can only call **verified numbers**: your own, plus up to a few you verify yourself under
  *Phone Numbers → Manage → Verified Caller IDs* (verification is by SMS on trials). Calls to anyone
  else are refused (Twilio error **32100** for SIP);
- may play a short "trial account" message at the start of calls;
- is restricted in which countries it can call; see the next step.

**Tested:** with a **free Twilio trial account** and the **free LiveKit Cloud plan**, Voizy created the
Elastic SIP trunk, connected a number, and placed a real outbound call to a verified phone. So a
trial is enough to try Voizy's phone features, within the limits above.

Twilio's own documentation is inconsistent about SIP trunking on trials (one page says trial SIP calls
work but only to verified numbers, another says SIP trunking needs an upgraded account), and what a
trial allows can vary by account and region. If connecting a number fails with a Twilio error, read
the message Voizy shows (it contains Twilio's reason); upgrading the account is the likely fix.

### 2.3 Allow calling your country

In the Console go to **Voice → Settings → Geo permissions** and enable the country you will call.
Twilio applies this to Elastic SIP Trunking too, and a blocked call shows up as warning **32205**.
See [Voice dialing geographic permissions](https://www.twilio.com/docs/sip-trunking/voice-dialing-geographic-permissions).

### 2.4 Connect Twilio in Voizy

1. **Settings → Twilio**: enter the Account SID and Auth Token, press **Test connection**.
2. Publish an agent (an agent must be *published* to take phone calls): in its editor, *Save as new
   version*, then *Publish*.
3. **Phone → Connect a number**: enter your Twilio number **with its country code** (like
   `+14155550134`), and optionally choose which agent answers it. Press **Connect number**.

What Voizy does in your accounts (so nothing is a surprise), through the APIs:
- Twilio: creates one **Elastic SIP trunk** named "Voizy" (first time only) with an origination URI
  pointing at your LiveKit SIP address, a termination domain and a credential list; **attaches your
  number to that trunk, which replaces any voice webhook already set on the number**.
- LiveKit: creates an inbound SIP trunk (accepting only Twilio's signaling addresses and only that
  number), a dispatch rule that sends each caller to a new room with your agent, and an outbound trunk.

If any step fails, Voizy undoes what it created. *Disconnect* (trash icon) removes the same things;
the number stays in your Twilio account.

### 2.5 Your first real calls

- **Outbound:** on the number's row press **Call**, enter a number you have verified in Twilio, choose an
  agent, tick the permission box, and start. Your phone rings; the agent speaks when you answer.
- **Inbound:** on the number's row choose an agent under **Answered by**, then call your Twilio number
  from your verified phone.

Afterwards open **Calls** to see the transcript, tools used, and the other party's number.

---

## If it doesn't work

| What you see | Likely cause and what to do |
|---|---|
| Settings → LiveKit "Test connection" fails | Check the URL starts with `wss://` and has no trailing path, and that the key and secret belong to the same project. Create a new key and try again. |
| Browser call connects but the agent never speaks | The voice worker isn't running or isn't connected: `docker compose logs agent`. After saving LiveKit keys it should log that it registered a worker. Also make sure no other worker (another machine, a dev setup) is registered on the same project with the same name; set `VOIZY_AGENT_NAME` to tell them apart. |
| The test console says LiveKit's credits are used up (429), or a service refused the request as too many | **Credits used up:** the free plan's included Inference credits ran out; the worker log says "credit quota exceeded". LiveKit's Billing page lists what you used but does not show what remains, so this message is the reliable signal. It happens after a lot of test calls. Use your own provider keys (see 1.4), upgrade, or wait for the reset. **Too many requests:** a rate or concurrency limit; wait a moment and check **Settings → Usage and limits**. |
| Microphone doesn't work | Use `http://localhost`, or HTTPS. Allow the microphone for the site. Use headphones. |
| Connecting a number fails with a Twilio message | Read the message: wrong SID/token, number not in this Twilio account, or the account must be upgraded for SIP trunking (see 2.2). Nothing is left half-created. |
| Outbound call fails or never rings | Is the destination verified (trial)? Is its country enabled in Geo permissions (2.3)? Is the agent published? Look for Twilio errors 32100 or 32205 in the Twilio Console debugger. |
| Phone rings and drops, or the caller hears nothing | See [TELEPHONY.md](TELEPHONY.md#troubleshooting). |
| Phone calls feel slower than the browser | Expected to some degree; see [TELEPHONY.md](TELEPHONY.md) and [LATENCY.md](LATENCY.md) for causes and the settings to tune. |

## Optional alternatives

- **Self-hosted LiveKit** instead of LiveKit Cloud: Voizy works with it, but Inference (hosted speech
  and language models) is a Cloud feature, so use your own provider keys, and set
  `VOIZY_LIVEKIT_SIP_HOST` to your SIP address.
- **LiveKit's own phone numbers:** LiveKit also sells numbers, but Voizy's automatic phone setup only
  supports Twilio today.

## When you're done testing

`docker compose down` stops the stack (add `-v` to also delete your data). On Twilio, disconnect the
number in Voizy if you won't use it, and remember trial accounts expire. In LiveKit you can delete the
project or the API key you created.

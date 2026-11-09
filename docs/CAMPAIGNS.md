# Campaigns

Call a list of people with an agent, inside the hours you choose, with retries. Nothing is called
until you press **Start**.

## Create one

**Campaigns -> New campaign**:

1. Pick a **published** agent and one of your connected phone numbers to call from.
2. Choose calling **days and hours**. They are judged in each person's own timezone (a `timezone`
   column in the CSV, like `America/New_York`), falling back to the campaign's default timezone.
3. Set **calls at once** (1-10), **attempts per person** (1-5, counting the first call) and the
   **wait before retrying** (5 minutes to 7 days).
4. Upload or paste a **CSV** and press *Check the list*. It needs a header row with a `phone` column.
   Optional columns: `name`, `timezone`. Every other column becomes a prompt variable with the same
   name *if the agent declares it* (for example a column `order_id` fills `{{order_id}}`); undeclared
   columns are listed as ignored. `{{contact_name}}` is always available.
5. Tick the **consent** box and create. It starts as a draft.

Numbers can be written `+1 (415) 555-0134`, `00442079460958`, or without a country code if you set a
default one. Rows that cannot be used (bad number, unknown timezone, duplicates) are listed with the
reason and skipped. Up to 5,000 people per campaign.

## While it runs

A scheduler in the API checks every 5 seconds. For each running campaign it records outcomes, then
starts calls for people who are due: the right day, inside the window in their timezone, not on the
do-not-call list, and only up to the campaign's concurrency. Pause and Resume stop and restart
dialing; Cancel is permanent (calls in progress finish).

Each person ends as one of: **Reached**, **No answer**, **Voicemail**, **Failed**,
**Asked not to be called**, or **Do not call**. No answer, voicemail and failures are retried until
attempts run out. A dial that fails (for example Twilio refuses) is counted as an attempt and shown
with its reason. A call that never starts is given up on after 2 minutes, a hung one after an hour.
Every call is linked to its person and appears in **Calls**.

## Voicemail and opting out

On outbound calls the agent has two extra tools:

- `voicemail_detected`: when it hears a recorded greeting or beep it hangs up without speaking.
  This is the model's judgement from the transcript, not a telephony answering-machine detector, so
  it can miss unusual greetings. The call is recorded as "voicemail".
- `opt_out_of_calls`: when someone asks not to be called again, their number goes on the workspace
  **do-not-call list** immediately and they are never called by any campaign.

## Do not call

The list (Campaigns -> *Do not call*) is checked at import and again at the moment of dialing, so
adding a number stops queued calls in every campaign. Numbers can be added or removed by hand. It is
per workspace.

## Safety and responsibility

- Creating a campaign needs the consent confirmation, which is stored with who confirmed and when.
  **It is your attestation, not a legal check.** Telemarketing and calling-hours rules vary by
  country (for example TCPA in the US, TRAI in India, PECR in the UK); you are responsible for
  having permission and for choosing compliant hours. Campaigns call only inside the window, but the
  window is yours to set correctly.
- Contact numbers are masked in the dashboard and API unless the reader holds `calls:view_pii`.
- Starting needs `campaigns:run`; contacts and the do-not-call list need
  `campaigns:manage_contacts`; everything is audited (no full numbers in the log).
- On LiveKit's free plan about **5 calls can run at once** (and 5 Twilio participants); the campaign
  form allows up to 10, so set **Calls at the same time** to 5 or less there, or calls beyond the limit
  fail and are retried.
- Campaign dialing is separate from the 30-calls-per-hour cap on one-off outbound calls. Concurrency
  is the limit; keep it low until you trust a campaign.

## Limits (be aware)

- The scheduler serves the **primary workspace** of a single deployment (like retention). It is a
  Postgres-backed loop, not Temporal.
- There is no automatic timezone detection from a phone number; use the `timezone` column.
- Voicemail detection is model-based (above). Leaving a voicemail message is not built.
- No per-campaign scripts beyond the agent's prompt and variables, and no outcome labels or
  summaries yet (post-call analysis is not built).

## Verified

- The scheduling rules (windows in the contact's timezone, calling days, concurrency, retries,
  do-not-call at import and at dial time, opt-out, outcomes, stuck calls) are tested in SQL against
  Postgres, and the API and routes with a fake dialer.
- On real LiveKit, the real scheduler ran a four-person campaign with only the phone leg simulated:
  one person reached (greeted by name, order number from the CSV), one never picked up (retried,
  then "no answer"), one voicemail (detected, retried, then "voicemail"), one asked to be removed
  (opted out, on the do-not-call list, never retried), and the campaign closed itself.
- **Not verified:** a real call through Twilio from a campaign (the same dialing code as one-off
  outbound calls, which was verified manually).

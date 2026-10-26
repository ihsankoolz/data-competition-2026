# Demo script

Sections are added as the demo is rehearsed. The main storyline lives in `docs/PRD.md` (DEMO-01 to DEMO-08); this file holds the walk-through beats that are optional.

Rehearse the main path with `make rehearse`: it walks steps 1–7, prints per-step timings against the 2:30 budget, and saves 1440x900 screenshots to `apps/web/test-results/rehearse/`. Press **Reset demo** before recording: it also clears any theme preview stored in the browser (`lives-mdm.theme-variant`), so the app shows the chosen theme (`THEME_VARIANT` in `apps/web/lib/theme.ts`).

## Beat 1: the messy inbox

**Steps:** open **DEMO-01** (Marcus's "Benh vien Cho Ray" email) and click **Read this email**. Over about 1.5 seconds each detail appears with its source words lit up in the email, then the category, then what is missing. Then click **Sort all**.

**Say, while it reads:** "Watch the AI read one: every detail it pulls out points at the exact words it came from. Nothing is guessed." Then: "88 real-looking emails: mixed wording, languages and scripts. One click sorts them all." (88, not 60: D-021.)

**If asked about the badge "Replaying a recorded AI response":** the AI's answer for this exact email was recorded earlier, so the live demo behaves the same every time, even without the internet (D-010, D-023). The trace replays that answer; the details still come only from words in the email. Under "reduce motion" settings everything appears at once.

## Beat 4: Wei Jie, Finance (DEMO-07 vendor, D-021)

**Set-up (off camera):** the Precision Diagnostics Asia vendor request, with its bank rows entered in the secure form, is already submitted. `make rehearse` pre-stages it the same way.

**Steps:**

1. In the messy inbox, open **DEMO-07** ("New vendor - Precision Diagnostics Asia") and read it with AI. Point at the line: *"Bank details in this email were removed before the AI read it. They are never sent to the AI, and only Finance can see them."*
2. Click **+1 day**. The clock shows Day 2.
3. Switch to **Wei Jie**. The bell shows a reminder. Open it: the vendor request, with the bank details in full.
4. Switch to **Daniel** (BU head): the same bank details are masked. Switch back to Wei Jie.
5. Wei Jie approves. Point at the audit log: who, what, when.

**Say:** "The AI never sees bank details, and nothing in an email can change them. Only Finance sees the account number, and the reminder came from the system on day 2, not from someone chasing by email."

**Why not Amy's item:** Finance is routed on customer and vendor requests only. Amy's malaria kit goes to the BU head, Business Support and Quality/Regulatory per country.

## Beat 6: the merge toggle

**Say, while toggling before → after merge:** "Same sales, cleaner customers. The customer count drops from 423 to 319, because duplicates collapse into one golden record. 'Lost customer' alerts drop from 63 to 35: 30 of the 63 were false alarms, the same customer still ordering under another record. Retention (NRR) rises from 80.7% to 91.0%. The heatmap totals don't change: merging fixes *who* the customer is, not how much we sold."

**Then point at cross-sell:** 0% before merge, the after-merge % next to it. "Before the golden record, you can't see who your cross-sell customers are." The drop-off risk and cross-sell whitespace lists (after merge only) give a USD value per account.

## Optional beat: lapsed licence

**What it shows:** an incomplete or out-of-date submission is stopped at the door, before any approver sees it (the brief's question "how do you stop incomplete submissions before an approver?", D-018 item 3). About 40 seconds.

**Why a different item:** it deliberately does NOT use DEMO-02's malaria kit, so the main demo path is never blocked. The malaria kit, with in-date registrations, goes straight through (an automated test checks this).

**Set-up:** a fresh demo (`Reset demo`). The simulated clock is Mon 5 Oct 2026. Nothing else to prepare.

**Steps (persona: Amy, SPD, Singapore):**

1. Switch to Amy. Choose **New request > Item**.
2. Enter item name `CRP Quantitative Reagent - 200 test pack`, item group `Reagents and test kits`, IVD = **Yes**, product family A, selling countries **Singapore** and **Malaysia**.
3. Registration for **Singapore**: number `DE2538958`, expiry `2029-11-23`.
4. Registration for **Malaysia**: number `GB04450349-35150`, issue date `2021-08-16`, expiry `2026-08-15`. These are the real values of the lapsed Malaysia registration of the existing item A-CRP-QT in `item_registrations.csv` (status `expired`).
5. As soon as the date is typed, the form shows under the Malaysia row, before submitting: *"The Malaysia registration expired on 15 Aug 2026. Renew it or remove Malaysia from the selling countries."* The check uses the simulated clock's today, not the laptop's date. The hint next to **Submit** says *"A registration has expired: renew or remove it first."* Expiry date is marked **Required** on every registration row, and an empty one counts in the "required fields still empty" hint.
6. Press **Submit**. It is refused with the same sentence; no approval task is created and the request stays a draft. (API: `422 {"detail": "...", "issues": [{"field": "registrations.MY.expiry_date", "kind": "expired", ...}]}`.)
7. Remove Malaysia from the selling countries (or type a renewed expiry such as `2029-08-15`). The message disappears, the hint reads *"Everything required is filled in."*, and **Submit** now routes the request to Business Support, the BU head and the Singapore Quality / Regulatory reviewer.

**Say:** "Dates are checked against the simulated clock, the same one that drives the approval reminders, so this works the same on demo day as it will in production."

**Also true, if asked:** an item whose licence lapses between approval and publishing is refused again at publish (Priya sees: *"This item can't be published: The Singapore registration expired on ..."*). Advance the clock past the expiry date to show it.

**Needs:** every regulated selling country of an IVD item needs a registration number and an expiry date that is after today. When rehearsing DEMO-02 (malaria kit, SG, MY, VN) type an expiry date for each country, for example `2030-01-10`.

**Automated check:** `tests/test_validation.py::test_optional_beat_lapsed_licence_is_stopped_at_submit`.

**Since session 13:** the beat reuses A-CRP-QT's own name and registration numbers, so the new item duplicate check now (correctly) flags it as a **Likely duplicate** of A-CRP-QT first. After step 6, click **Not the same item — explain why** (e.g. "new 200-test pack size, separate SKU") before **Submit** in step 7. `tests/test_validation.py` covers the extra step.

## Optional finals beats (session 12)

Four short beats for the live finals or Q&A. None of them is in the recorded video path, and **Reset demo** undoes each one (rule changes and clean-up decisions included).

### Finals beat A: the reply to the sender (adoption, about 20 s)

**Steps:** in the messy inbox, read **DEMO-01** as Marcus and scroll the reading panel to **Reply to sender (draft)**.

**Say:** "Nobody has to change how they ask on day one. When an email comes in, the mailbox answers with this: thanks, only the details we still need, and a link to the form already filled in from their email. It is a fixed template, not AI, and the prototype sends nothing. In production Power Automate sends it from the MDM mailbox." Click **Copy reply** or **Open form** if asked.

**If asked "why not let the AI write the reply?":** a fixed template cannot promise anything, invent a field, or be talked into changing bank details. The AI only reads; it never sends.

### Finals beat B: onboard a new team in 30 seconds (flexibility, about 40 s)

**Steps:**

1. Switch to **Priya** and open **Admin & config**. The editor opens on *Customer · QTG · Vietnam*, Marcus's new business unit.
2. Under **Add step**, choose *Quality / Regulatory* and *Nguyễn Thị Lan*, and click **Add step**. **Who would approve this?** updates at once.
3. Click **Save rule**. The change appears under **Recent changes** with who and when.
4. Optional: switch to **Marcus**, create a Vietnam customer request and submit it. Lan is among the first-stage approvers.

**Say:** "The brief says adding an approval step today means redrafting the email template and the distribution list. Here the MDM team does it in one screen, sees who would approve before saving, and only new requests pick it up. Requests already in approval keep their approvers. No IT ticket."

### Finals beat C: clean up the duplicates already in SAP (Priya, about 30 s)

**Steps:** as **Priya**, open **Clean-up queue**. The first group is two records of the same Vietnamese laboratory, with the same tax ID. Point at the reasons, then click **Confirm link**. The counter moves to "1 of 168 reviewed". On a weaker group, click **Not the same** and type a reason.

**Say:** "The duplicate check doesn't only stop new duplicates; it also finds the ones already in the master: 168 groups, most certain first. Priya confirms each one; the AI never merges. Customer and vendor records, and records in different countries, are never grouped." (168 groups = the 277 proposed links, which `results.md` scores 277 of 277 right on the synthetic data.)

**If asked whether her decisions change the regional numbers:** not in this prototype. The regional "after merge" view uses the links the check proposes, and says so under the toggle with a link to this queue. In production her confirmed links would become the golden IDs.

### Finals beat D: prove the history was not edited (governance, about 20 s)

**Steps:** on any request page, under **History**, click **Check history is untampered**: "Checks the whole history log (all requests): N entries intact." The same check is on **Admin & config**.

**Say:** "Every entry is chained to the one before it, so an edit anywhere breaks the chain from that point on. The check recomputes the chain from the first entry." If there is a terminal, run `make tamper-demo`: it changes one approval in a throwaway copy of the database and shows the check naming that entry. There is deliberately no tamper button in the app.

## Optional finals beats (session 13)

Short beats for the live finals or Q&A, none in the recorded video path. **Reset demo** undoes each one.

### Finals beat E: a fourth record type and a required field, no IT (flexibility, about 40 s)

**Steps:** as **Amy**, **New request → Cost Center**: name, start date, submit; the status page asks Finance and the BU Head at once. Then as **Priya**, **Admin & config → Required fields**: *Customer · Singapore*, switch **City** to required, save. Open a new Singapore customer form: City now says Required. Try to switch **Tax ID** off: it is locked, with the reason.

**Say:** "Cost Center is one config file, 43 lines; adding it removed more code than it added. The MDM team changes what a form asks for, per country, without a developer. New requests only, every change in the history log, and anything SAP or the approval route needs is locked."

### Finals beat F: a duplicate item (data quality, about 25 s)

**Steps:** as **Amy**, **New request → Item**, type `Rapid Dengue NS1 Antigen Test Kit, 25 tests`. The panel: **Likely duplicate** of A-DEN-NS1, "same name once pack size, units and punctuation are ignored". Optionally type an existing registration number for Singapore to show "one registration can't belong to two products".

**Say:** "The brief says duplicate items are a recurring problem. Rules only, no AI; a person decides. The generator has no planted item duplicates, so we tested it on 50 pairs we wrote ourselves: treat that as a sanity check, not an accuracy claim."

### Finals beat G: approvers in other countries, and Teams (adoption, about 30 s)

**Steps:** on a request with Nguyễn Thị Lan (Quality / Regulatory, Vietnam) as approver, point at "9:00 am SGT, 8:00 am in Vietnam". Act as Lan, open the bell, click **See it in Teams**: the card with Approve / Ask for info / Reject / Open. Download the card file.

**Say:** "Deadlines run on one clock; each person sees theirs in local time. In production Power Automate posts this exact card in Teams. Nothing is sent from here, and the buttons here do nothing; a person decides in the app. And when Priya publishes, Amy is told: 'live in SAP as A-MAL-001, so you can raise sales orders now', the moment that took 18 days in the brief."

### Finals beat H: can AI beat the Excel average for equipment? (honesty, about 30 s)

**Steps:** **Regional view → forecast panel**, scroll to the line under the backtest and the **Next 3 months plan** table.

**Say:** "We tried planning equipment from the purchase requests customers raise now, method fixed before the first run. Result: a tie with the 12-month Excel average in the demo market, 26.5% against 26.1% error, and worse in the other two, even though our synthetic data builds requests from orders and so favours it. So we would pilot it and measure the real conversion rate before trusting it. The Vietnam column is separate on purpose: Excel ran 13% low there in the backtest, so the column adds 15% on Excel's plan, and you can see it rather than have it buried."

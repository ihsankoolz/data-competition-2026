# Demo script

Sections are added as the demo is rehearsed. The main storyline lives in `docs/PRD.md` (DEMO-01 to DEMO-08); this file holds the walk-through beats that are optional.

Rehearse the main path with `make rehearse`: it walks steps 1–7, prints per-step timings against the 2:30 budget, and saves 1440x900 screenshots to `apps/web/test-results/rehearse/`.

## Beat 1: the messy inbox

**Say:** "88 real-looking emails: mixed wording, languages and scripts. One click sorts them all." (88, not 60: D-021.)

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

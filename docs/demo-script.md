# Demo script

Sections are added as the demo is rehearsed. The main storyline lives in `docs/PRD.md` (DEMO-01 to DEMO-08); this file holds the walk-through beats that are optional.

## Optional beat: lapsed licence

**What it shows:** an incomplete or out-of-date submission is stopped at the door, before any approver sees it (the brief's question "how do you stop incomplete submissions before an approver?", D-018 item 3). About 40 seconds.

**Why a different item:** it deliberately does NOT use DEMO-02's malaria kit, so the main demo path is never blocked. The malaria kit, with in-date registrations, goes straight through (an automated test checks this).

**Set-up:** a fresh demo (`Reset demo`). The simulated clock is Mon 5 Oct 2026. Nothing else to prepare.

**Steps (persona: Amy, SPD, Singapore):**

1. Switch to Amy. Choose **New request > Item**.
2. Enter item name `CRP Quantitative Reagent - 200 test pack`, item group `Reagents and test kits`, IVD = **Yes**, product family A, selling countries **Singapore** and **Malaysia**.
3. Registration for **Singapore**: number `DE2538958`, expiry `2029-11-23`.
4. Registration for **Malaysia**: number `GB04450349-35150`, issue date `2021-08-16`, expiry `2026-08-15`. These are the real values of the lapsed Malaysia registration of the existing item A-CRP-QT in `item_registrations.csv` (status `expired`).
5. The form shows next to the Malaysia expiry date, before submitting: *"The Malaysia registration expired on 15 Aug 2026. Renew it or remove Malaysia from the selling countries."*
6. Press **Submit**. It is refused with the same sentence; no approval task is created and the request stays a draft. (API: `422 {"detail": "...", "issues": [{"field": "registrations.MY.expiry_date", "kind": "expired", ...}]}`.)
7. Remove Malaysia from the selling countries (or type a renewed expiry such as `2029-08-15`). The message disappears and **Submit** now routes the request to Business Support, the BU head and the Singapore Quality / Regulatory reviewer.

**Say:** "Dates are checked against the simulated clock, the same one that drives the approval reminders, so this works the same on demo day as it will in production."

**Also true, if asked:** an item whose licence lapses between approval and publishing is refused again at publish (Priya sees: *"This item can't be published: The Singapore registration expired on ..."*). Advance the clock past the expiry date to show it.

**Needs:** every regulated selling country of an IVD item needs a registration number and an expiry date that is after today. When rehearsing DEMO-02 (malaria kit, SG, MY, VN) type an expiry date for each country, for example `2030-01-10`.

**Automated check:** `tests/test_validation.py::test_optional_beat_lapsed_licence_is_stopped_at_submit`.

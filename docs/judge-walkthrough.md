# Try it in 5 minutes

A click path through the prototype for judges, written from the automated walkthrough (`apps/web/e2e/walkthrough.spec.ts`, run by `make rehearse`). Every step below is exercised by that test on every change.

**Before you start:** `make setup` once, then `make dev`, and open http://localhost:3000. Press **Reset demo** (top right) so you start from the seeded state. No API key is needed: the AI's answers for the demo emails were recorded and are replayed (the badge says so).

The persona switcher (top right) sets who you are. There is no login; the server still enforces who may do what.

## 0. Start here (15 s)

The home page shows the five steps (email → interpreted → golden record → approvals → SAP), the headline numbers (read live from the app, not typed in), and one card per journey. The steps below follow those cards.

## 1. Marcus: an email in Vietnamese spelling becomes one golden record (60 s)

1. As **Marcus**, open **Messy inbox** and pick **DEMO-01** ("Benh vien Cho Ray").
2. Click **Read this email**. Each detail appears with the exact words it came from lit up in the email; then the category; then what is missing.
3. Under it, **Reply to sender (draft)** is the reply the MDM mailbox would send: thanks, only the missing fields, a link to the pre-filled form. Nothing is sent from the prototype.
4. Click **Create request from this email**. The form is filled in, each value showing where it came from.
5. The duplicate panel says **Likely duplicate: submit is paused**: the existing record "Bệnh viện Chợ Rẫy" (C00084), matched by tax ID and name across spellings. Click **Link to existing C00084**, then **See the request**: it is linked to the existing customer, so no new record and no approver's time.

**Look for:** nothing the AI "found" without a quote; a person makes the duplicate decision.

## 2. Amy: an item request that cannot be submitted incomplete (60 s)

1. Switch to **Amy**. In the inbox, open **DEMO-02** (malaria rapid test), read it, and click **Create request from this email**.
2. The form asks for a registration number and expiry for each selling country (SG, MY, VN). Submit stays disabled, with the reason shown, until they are in. Fill them in (any number, an expiry in the future) and submit.
3. The status page shows every approver of the first stage at the same time: BU Head, Business Support, and Quality / Regulatory for each country, each with a due time.

**Look for:** the brief's 18-day example came from one approver after another and a missing regulatory field. Here the field is required up front and approvers work in parallel.

## 3. Approvers, reminders and a history you can check (45 s)

1. Click **+1 day** next to the clock. Approvers who have not answered get a reminder (the bell).
2. On Amy's request, click **Act as <name>** next to a pending approver and **Approve**; repeat for the others. Each decision lands in **History** with who and when.
3. In History, click **Check history is untampered**. It recomputes the chain of the whole log and says how many entries are intact. (`make tamper-demo` shows the same check catching an edited entry in a copy of the database.)
4. In the inbox, open **DEMO-07** (a new vendor with bank details in the email): the details were removed before the AI read it. Only Finance sees bank details in full.

## 4. Priya: publish to SAP Business One (30 s)

1. Switch to **Priya** and open **Publish to SAP**. Pick Amy's item and click **Publish**.
2. The record is created inactive in SAP, read back, compared field by field, and only then switched on. What was sent and what SAP saved are side by side.

## 5. The regional view (60 s)

1. Open **Regional view**. Sales come from confirmed purchase orders only; enquiries and MDM requests are separate panels.
2. Switch **Before merge → After merge**. Customers drop from 423 records to 319 customers; "lost customer" alerts from 63 to 35, because 30 were the same customer still ordering under another record. Sales totals do not change.
3. Scroll for the map, the forecast backtest (honest: a tie with the Excel average, and counting enquiries as orders is the bigger error), the drop-off and cross-sell lists, and the recommended actions.

## 6. Setup without IT (30 s)

1. As **Priya**, open **Admin & config**. It opens on *Customer · QTG · Vietnam* (Marcus's new business unit). Under **Add step** choose *Quality / Regulatory* and *Nguyễn Thị Lan*, click **Add step**, and watch **Who would approve this?** update. Click **Save rule**: new requests get the new step, requests already in approval keep theirs, and the change is listed under **Recent changes** and in the history log.
2. Open **Clean-up queue**: the duplicate groups the check proposes in the existing customer master, most certain first (168 groups, made of the 277 links that [`results.md`](results.md#how-good-are-our-merged-customers) scores as 277 of 277 right). Click **Confirm link**, or **Not the same** with a reason. The regional numbers do not move: the after-merge view uses the proposed links, and says so under its toggle.

Press **Reset demo** when you are done: it restores everything, including rule changes and clean-up decisions.

Every number above is in [`results.md`](results.md), regenerated by `make eval`.

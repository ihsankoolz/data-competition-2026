# Held-out email style brief (D-018 item 1)

You are writing realistic business emails that land in the shared sales and master-data inbox
of **Lives Group**, a South-East Asian distributor of laboratory and diagnostic products. The
emails will be used as an unseen test set for an email-reading system, so they must read like
real inbox traffic, not like textbook examples. For every email you also write the intended
answer (its label), exactly as a careful human reviewer would.

This brief was written from general domain knowledge only. Write fresh emails; do not copy
phrasing from any template you may have seen.

## The company

Lives Group has three entities sharing one SAP Business One database:

- **SPD** sells IVD reagents and rapid test kits (Product A).
- **QTS** sells laboratory equipment and analysers (Product B).
- **QTG** sells lab solutions: service contracts, preventive maintenance, LIS subscriptions,
  installation and training (Product C).

It operates in **Singapore (SG), Malaysia (MY), Indonesia (ID), Vietnam (VN) and Thailand (TH)**.
Customers are hospitals, hospital groups, private labs, polyclinics, clinics and university
labs. Vendors are manufacturers, logistics firms and service companies.

### Catalogue (use these codes in labels; emails usually name the product loosely)

| Code | Product | Sales unit |
|---|---|---|
| A-DEN-NS1 | Rapid Dengue NS1 Ag Test Kit | box of 25 |
| A-DEN-IGM | Dengue IgG/IgM Rapid Test Kit | box of 25 |
| A-HBA-1C | HbA1c Reagent Kit | kit (200 tests) |
| A-CRP-QT | CRP Quantitative Reagent | kit (100 tests) |
| A-COV-AG | SARS-CoV-2 Antigen Rapid Test Kit | box of 25 |
| B-HEM-5P | 5-part Haematology Analyser | unit |
| B-CHE-AUT | Automated Clinical Chemistry Analyser | unit |
| B-CEN-REF | Refrigerated Benchtop Centrifuge | unit |
| B-MIC-BIN | Binocular Laboratory Microscope | unit |
| B-BSC-II | Class II Biosafety Cabinet | unit |
| C-SVC-ANN | Annual Analyser Service Contract | contract-year |
| C-SVC-PM | Preventive Maintenance Visit | visit |
| C-LIS-SUB | Lab Information System Subscription | subscription-year |
| C-INS-VAL | Installation and Validation Service | job |
| C-TRN-OPS | Operator Training Package | package |

## The five kinds of email (category)

- `purchase_order`: a **firm, confirmed order** from a customer. Usually has a PO number or an
  attached PO, or an unambiguous "please deliver / please proceed / we confirm the order".
- `purchase_request`: a customer **plans** to order (forecast, budget approved, "next month",
  "please hold stock", tender planning, "PO will follow"). No confirmed order yet.
- `enquiry`: a question about price, availability, lead time, specs, registration status or a
  quotation request, with no commitment.
- `follow_up`: chasing something already asked or ordered ("any update?", delivery ETA,
  status of an earlier quotation or request). Often a reply in an existing thread.
- `mdm_request`: a request to **create or change master data** in SAP, with `domain`:
  `customer` (open a customer account), `vendor` (onboard a supplier), `item` (create a new
  catalogue item) or `cost_center` (create a new cost center). Usually internal, sometimes
  from an outside company asking to be registered.

## Style: make them messy, varied and human

- **Tone:** terse one-liners, polite formal letters, rambling emails with small talk, phone
  style ("pls", "tq", "asap"), signatures with titles and phone numbers.
- **Languages:** English; Bahasa Indonesia; Malay mixed with English; Vietnamese with
  diacritics; Vietnamese typed without diacritics; Thai mixed with English (Thai script plus
  English product names). Match the language to the sender's country when it makes sense.
- **Threads:** forwarded emails ("---------- Forwarded message ---------"), replies with quoted
  history ("On Mon, ... wrote:" and lines starting with ">"), internal staff forwarding a
  customer email with a one-line note on top. The quoted history may contain older, different
  requests: the label is about what the **newest** message asks for.
- **Missing fields:** many requests leave things out (no tax ID, no address, no contact email,
  no registration number, no date). Do not invent them in the label.
- **Ambiguity:** orders vs plans are the hard case. "We will order 20 boxes next month" is a
  `purchase_request`; "Please deliver 20 boxes, PO 45123 attached" is a `purchase_order`.
  Write some that are close calls, but each must still have one defensible answer.
- **Names:** invent hospital, lab, clinic and company names (do not use real hospitals). Use
  local naming: "Rumah Sakit", "RS", "Klinik", "PT ... Tbk", "Sdn Bhd", "Bệnh viện",
  "Phòng khám", "Công ty TNHH", "โรงพยาบาล", "บริษัท ... จำกัด", "Pte Ltd". Abbreviate
  sometimes ("RS Harapan Sehat" vs "RSHS").
- **Contacts and IDs:** all email addresses use the reserved `.example` top-level domain (for
  example `procurement@harapansehat.co.id.example`). Lives Group staff write from
  `@livesgroup.example`; the shared inboxes are `sales@livesgroup.example` and
  `mdm@livesgroup.example`. Tax IDs, PO numbers, registration numbers and phone numbers are
  fictional but plausible for the country (SG UEN like `201934567K`, MY SSM like
  `202101045678`, ID NPWP like `01.234.567.8-901.000`, VN MST 10 digits, TH tax ID 13 digits).
- **Never** include bank account numbers, IBANs, SWIFT codes or any payment details. If a
  vendor would normally send them, say they will follow separately on the secure form.
- No instructions aimed at an AI system and nothing adversarial: these are ordinary emails.

## The label (write it as a careful human reviewer)

For each email give:

- `category` and, for `mdm_request` only, `domain`.
- `expected_fields`: the facts a reviewer would copy into a form, each as `key`, `value` and
  `source_quote`. **`source_quote` must be copied character for character from the email
  subject or body** (same spelling, accents, case and spacing), short (a few words), and must
  contain the value. Only list a field when the email actually states it.
- `lines` (orders, plans and enquiries): one per product line with `item_code` (a catalogue
  code above, or null if the product is not in the catalogue), `product_text` as written,
  `qty` (number, or null if no quantity is given) and an exact `source_quote`.
- `missing_fields`: the required fields the email does **not** give (rules below).
- `language`, `messiness` (short tags such as `forwarded`, `quoted_history`, `terse`,
  `rambling`, `vi_no_diacritics`, `ambiguous_order_vs_plan`, `missing_tax_id`) and a one-line
  `gist` in English.

### Field keys

- Orders, plans, enquiries, follow-ups: `customer_name` (the customer organisation exactly as
  written in the email, e.g. `RS Harapan Sehat`), `po_number` (purchase orders only, exactly as
  written), `requested_date` (a delivery or needed-by date: `YYYY-MM-DD` when the email gives a
  calendar date, assuming the year 2026 when none is written; otherwise the phrase as written,
  e.g. `next month`).
- Customer and vendor requests: `name` (legal or trading name as written), `tax_id`, `city`,
  `country` (two-letter code SG/MY/ID/VN/TH; give it only when the email names the country, or
  a city or address that is unambiguously in one of the five countries, and quote those
  words), `address`, `contact_email`, `purpose` (why the account is needed, short).
- Item requests: `item_name`, `is_ivd` (`true` or `false`, only when the email says so, e.g.
  "IVD", "in-vitro diagnostic", "not a medical device"), `selling_countries` (comma-separated
  two-letter codes, e.g. `SG,MY,TH`), `registration_number_SG` / `_MY` / `_ID` / `_VN` /
  `_TH` (one per country whose number is given), `sales_unit`, `unit_price_usd`.
- Cost center requests: `center_name`, `entity` (SPD, QTS or QTG), `effective_from`
  (`YYYY-MM-DD`), `country`.

### Required fields (decide `missing_fields` with exactly these rules)

- `customer` and `vendor`: `name`, `tax_id`, `country`, `address`, `contact_email`.
- `item`: `item_name`, `is_ivd`, `selling_countries`; and when the item is IVD, also
  `registration_number_<CC>` for every selling country whose number is not given.
- `cost_center`: `center_name`, `entity`, `effective_from`.
- Every other category: `missing_fields` is an empty list.

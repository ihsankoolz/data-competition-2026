"""Vendors (with BPBankAccounts), items and per-country item registrations (data-spec §5)."""

from __future__ import annotations

from datetime import date

import numpy as np

from .common import WINDOW_END, add_days, pick, stream, wpick
from .master import COUNTRY_ORDER, ENTITIES, Master, make_tax_id

# ItemCode, ItemName, family, unit, USD unit price, U_IVD, risk class (HSA-style A-D)
ITEMS = [
    ("A-DEN-NS1", "Rapid Dengue NS1 Ag Test Kit", "A", "box of 25", 118.00, True, "C"),
    ("A-DEN-IGM", "Dengue IgG/IgM Rapid Test Kit", "A", "box of 25", 96.00, True, "C"),
    ("A-HBA-1C", "HbA1c Reagent Kit", "A", "kit (200 tests)", 165.00, True, "B"),
    ("A-CRP-QT", "CRP Quantitative Reagent", "A", "kit (100 tests)", 72.00, True, "B"),
    ("A-COV-AG", "SARS-CoV-2 Antigen Rapid Test Kit", "A", "box of 25", 54.00, True, "C"),
    ("B-HEM-5P", "5-part Haematology Analyser", "B", "unit", 38500.00, True, "B"),
    ("B-CHE-AUT", "Automated Clinical Chemistry Analyser", "B", "unit", 62000.00, True, "B"),
    ("B-CEN-REF", "Refrigerated Benchtop Centrifuge", "B", "unit", 9800.00, False, ""),
    ("B-MIC-BIN", "Binocular Laboratory Microscope", "B", "unit", 4200.00, False, ""),
    ("B-BSC-II", "Class II Biosafety Cabinet", "B", "unit", 12500.00, False, ""),
    ("C-SVC-ANN", "Annual Analyser Service Contract", "C", "contract-year", 6800.00, False, ""),
    ("C-SVC-PM", "Preventive Maintenance Visit", "C", "visit", 950.00, False, ""),
    (
        "C-LIS-SUB",
        "Lab Information System Subscription",
        "C",
        "subscription-year",
        11500.00,
        False,
        "",
    ),
    ("C-INS-VAL", "Installation and Validation Service", "C", "job", 3200.00, False, ""),
    ("C-TRN-OPS", "Operator Training Package", "C", "package", 1500.00, False, ""),
]
ITEM_GROUP = {"A": 101, "B": 102, "C": 103}
ENTITY_OF = {"A": "SPD", "B": "QTS", "C": "QTG"}

ITEM_COLS = [
    "ItemCode",
    "ItemName",
    "ItemType",
    "ItemsGroupCode",
    "PurchaseItem",
    "SalesItem",
    "InventoryItem",
    "U_IVD",
    "product_family",
    "entity",
    "sales_unit",
    "unit_price_usd",
]
REG_COLS = [
    "item_code",
    "country",
    "is_ivd",
    "risk_class",
    "reg_no",
    "assumed_format",
    "reg_holder_entity",
    "issue_date",
    "expiry_date",
    "status",
]


def _yn(b: bool) -> str:
    return "tYES" if b else "tNO"


def item_rows() -> list[list]:
    rows = []
    for code, name, fam, unit, price, ivd, _ in ITEMS:
        physical = fam != "C"
        rows.append(
            [
                code,
                name,
                "itItems",
                ITEM_GROUP[fam],
                _yn(physical),
                "tYES",
                _yn(physical),
                _yn(ivd),
                fam,
                ENTITY_OF[fam],
                unit,
                f"{price:.2f}",
            ]
        )
    return rows


def _reg_no(country: str, rng: np.random.Generator, year: int) -> tuple[str, bool]:
    d = lambda n: "".join(str(int(x)) for x in rng.integers(0, 10, n))  # noqa: E731
    if country == "SG":
        return f"DE{d(7)}", False
    if country == "VN":
        return f"{year % 100:02d}{d(6)}ĐKLH/BYT-HTTB", False
    if country == "ID":
        return f"AKL 2{d(10)}", False
    if country == "MY":
        return f"GB{d(8)}-{d(5)}", True
    return f"TH {year % 100:02d}-{d(7)}", True


def registration_rows(seed: int) -> list[list]:
    """One row per IVD item x country. Exactly one `expired` (Stretch 'block publish' demo)."""
    rng = stream(seed, "catalog.registrations")
    ivd = [it for it in ITEMS if it[5]]
    keys = [(it[0], c) for it in ivd for c in COUNTRY_ORDER]
    expired_key = ("A-CRP-QT", "MY")
    pending_idx = set(int(i) for i in rng.choice(len(keys), 4, replace=False))
    rows = []
    for i, (code, c) in enumerate(keys):
        it = next(x for x in ITEMS if x[0] == code)
        holder = ENTITY_OF[it[2]]
        if (code, c) == expired_key:
            status, issue = "expired", date(2021, 8, 16)
            expiry = date(2026, 8, 15)
        elif i in pending_idx and (code, c) != expired_key:
            status, issue, expiry = "pending", None, None
        else:
            status = "active"
            issue = date(
                int(rng.integers(2019, 2026)), int(rng.integers(1, 13)), int(rng.integers(1, 28))
            )
            expiry = date(issue.year + 5, issue.month, issue.day)
            if expiry <= date(2026, 12, 31):
                expiry = date(2027 + int(rng.integers(0, 3)), issue.month, issue.day)
        reg_no, assumed = (
            ("", c in ("MY", "TH")) if status == "pending" else _reg_no(c, rng, issue.year)
        )
        rows.append(
            [
                code,
                c,
                True,
                it[6],
                reg_no,
                assumed,
                holder,
                issue.isoformat() if issue else "",
                expiry.isoformat() if expiry else "",
                status,
            ]
        )
    return rows


# --------------------------------------------------------------------------------------------
# Vendors
# --------------------------------------------------------------------------------------------

VENDOR_COLS = [
    "CardCode",
    "CardName",
    "CardType",
    "GroupCode",
    "FederalTaxID",
    "Currency",
    "PayTermsGrpCode",
    "CreditLimit",
    "EmailAddress",
    "Phone1",
    "City",
    "Country",
    "U_Entity",
    "CreateDate",
    "CreatedBy",
    "vendor_kind",
    "BankCode",
    "AccountNo",
    "AccountName",
    "BICSwiftCode",
    "IBAN",
    "BankCountry",
]
VENDOR_GROUP = {"manufacturer": 110, "logistics": 111, "services": 112, "customer_twin": 113}
ROOTS = [
    "Aster",
    "Brava",
    "Corvex",
    "Delmar",
    "Elvion",
    "Fennix",
    "Galenor",
    "Halcyon",
    "Isotek",
    "Junova",
    "Kestrel",
    "Lumira",
    "Medrix",
    "Norvel",
    "Orbitek",
    "Pellar",
    "Quorra",
    "Rivelle",
    "Sanvia",
    "Tavira",
    "Ulmero",
    "Veltra",
    "Wexfor",
    "Xandra",
    "Yarrow",
    "Zentis",
    "Calder",
    "Brisca",
    "Mirada",
    "Ostara",
    "Pyxis",
    "Solvia",
]
FOREIGN = {  # country: (legal suffix, currency, city)
    "DE": ("GmbH", "EUR", "Hamburg"),
    "CH": ("AG", "EUR", "Basel"),
    "US": ("Inc.", "USD", "San Diego"),
    "JP": ("K.K.", "USD", "Osaka"),
    "KR": ("Co., Ltd.", "USD", "Seoul"),
    "CN": ("Co., Ltd.", "USD", "Suzhou"),
}
LOCAL_SUFFIX = {"SG": "Pte Ltd", "MY": "Sdn Bhd", "ID": "PT", "VN": "Co., Ltd", "TH": "Co., Ltd."}
LOCAL_CITY = {
    "SG": "Singapore",
    "MY": "Kuala Lumpur",
    "ID": "Jakarta",
    "VN": "Ho Chi Minh City",
    "TH": "Bangkok",
}
CURRENCY = {"SG": "SGD", "MY": "MYR", "ID": "IDR", "VN": "VND", "TH": "THB"}
ACCOUNT_LEN = {
    "SG": 10,
    "MY": 12,
    "ID": 10,
    "VN": 13,
    "TH": 10,
    "US": 12,
    "JP": 7,
    "KR": 12,
    "CN": 16,
}
DIAL = {
    "SG": "65",
    "MY": "60",
    "ID": "62",
    "VN": "84",
    "TH": "66",
    "DE": "49",
    "CH": "41",
    "US": "1",
    "JP": "81",
    "KR": "82",
    "CN": "86",
}
IBAN_BBAN = {"DE": 18, "CH": 17}


def iban(country: str, bban: str) -> str:
    """ISO 13616 IBAN with a valid mod-97 check (fake account, well-formed)."""
    rearranged = bban + country + "00"
    num = "".join(str(int(ch, 36)) for ch in rearranged)
    check = 98 - int(num) % 97
    return f"{country}{check:02d}{bban}"


def _bank(country: str, holder: str, rng: np.random.Generator) -> list[str]:
    d = lambda n: "".join(str(int(x)) for x in rng.integers(0, 10, n))  # noqa: E731
    letters = "".join(chr(65 + int(x)) for x in rng.integers(0, 26, 4))
    loc = "".join(chr(65 + int(x)) for x in rng.integers(0, 26, 2))
    bic = f"{letters}{country}{loc}" + ("XXX" if rng.random() < 0.5 else "")
    if country in IBAN_BBAN:
        bban = d(IBAN_BBAN[country])
        return [
            bban[:8] if country == "DE" else bban[:5],
            bban[-10:],
            holder,
            bic,
            iban(country, bban),
            country,
        ]
    return [d(4), d(ACCOUNT_LEN[country]), holder, bic, "", country]


def vendor_rows(m: Master, params: dict, seed: int) -> tuple[list[list], dict[int, str]]:
    """Returns rows and {golden idx: vendor CardCode} for the customer/vendor twins."""
    rng = stream(seed, "catalog.vendors")
    vp = params["vendors"]
    recs: list[dict] = []
    for g in m.cv_golden:
        prim = g.records[0]
        name = (
            prim.card_name
            if (g.spec.forced_card_name or rng.random() < 0.6)
            else (g.spec.legal_rom if g.country == "TH" else g.spec.legal)
        )
        create = add_days(prim.create_date, int(rng.integers(30, 400)))
        recs.append(
            dict(
                name=name,
                tax=g.tax_id,
                country=g.country,
                city=g.spec.city,
                kind="customer_twin",
                create=min(create, WINDOW_END),
                twin=g.idx,
                email=f"sales@{g.email_domain}",
            )
        )
    n_other = vp["n_total"] - len(recs)
    roots = list(rng.permutation(ROOTS))
    for i in range(n_other):
        kind = wpick(rng, vp["kinds"])
        root = str(roots[i % len(roots)]) + ("" if i < len(roots) else " Global")
        if kind == "manufacturer" and rng.random() < 0.7:
            c = pick(rng, sorted(FOREIGN))
            suffix, _, city = FOREIGN[c]
            word = pick(
                rng,
                ["Diagnostics", "Biotech", "Medical Instruments", "Life Sciences", "Bioreagents"],
            )
            name = f"{root} {word} {suffix}"
        else:
            c = pick(rng, COUNTRY_ORDER)
            city = LOCAL_CITY[c]
            word = {
                "manufacturer": "Medical Manufacturing",
                "logistics": pick(
                    rng, ["Cold Chain Logistics", "Freight Services", "Express Logistics"]
                ),
                "services": pick(
                    rng, ["Calibration Services", "Biomedical Engineering", "Packaging"]
                ),
            }[kind]
            sfx = LOCAL_SUFFIX[c]
            name = f"PT {root} {word}" if sfx == "PT" else f"{root} {word} {sfx}"
        if c in COUNTRY_ORDER:
            tax = make_tax_id(c, rng, city)
        elif c == "DE":
            tax = "DE" + "".join(str(int(x)) for x in rng.integers(0, 10, 9))
        elif c == "US":
            tax = f"{int(rng.integers(10, 99))}-{int(rng.integers(1000000, 9999999))}"
        else:
            tax = "".join(str(int(x)) for x in rng.integers(0, 10, 13))
        create = date(
            int(rng.integers(2014, 2026)), int(rng.integers(1, 13)), int(rng.integers(1, 28))
        )
        slug = root.lower().replace(" ", "")
        recs.append(
            dict(
                name=name,
                tax=tax,
                country=c,
                city=city,
                kind=kind,
                create=create,
                twin=None,
                email=f"ar@{slug}.{c.lower()}.example",
            )
        )
    for i, r in enumerate(recs):
        r["seq"] = i
    recs.sort(key=lambda r: (r["create"], r["seq"]))
    rows, twin_codes = [], {}
    for i, r in enumerate(recs):
        code = f"V{i + 1:05d}"
        if r["twin"] is not None:
            twin_codes[r["twin"]] = code
        c = r["country"]
        currency = CURRENCY.get(c) or FOREIGN[c][1]
        phone = f"+{DIAL[c]} {int(rng.integers(10, 99))} {int(rng.integers(1000000, 9999999))}"
        rows.append(
            [
                code,
                r["name"],
                "cSupplier",
                VENDOR_GROUP[r["kind"]],
                r["tax"],
                currency,
                int(pick(rng, [1, 2, 3])),
                "0.00",
                r["email"],
                phone,
                r["city"],
                c,
                pick(rng, ENTITIES),
                r["create"].isoformat(),
                f"proc.{c.lower()}{int(rng.integers(1, 3)):02d}",
                r["kind"],
                *_bank(c, r["name"], rng),
            ]
        )
    return rows, twin_codes

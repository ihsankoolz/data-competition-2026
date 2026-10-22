"""Seeded users (data-spec §9, D-015 contract): demo personas, backup approvers, requestors.

The 8 personas mirror `services/api/personas.py` exactly (a test checks this). Requestor user
IDs are the SAP user codes found in `bp_records.CreatedBy` (`<entity>.<country><nn>`) and
`vendors.CreatedBy` (`proc.<country><nn>`), so every record's creator resolves to a user.
"""

from __future__ import annotations

USER_COLS = ["user_id", "name", "title", "roles", "entity", "country", "backup_for"]

# user_id, name, title, roles, entity, country (must match services/api/personas.py)
PERSONAS = [
    ("amy", "Amy", "Product Manager", ["requestor"], "SPD", "SG"),
    ("marcus", "Marcus", "Regional Sales (new BU)", ["requestor"], "QTG", "VN"),
    ("weijie", "Wei Jie", "Finance Manager", ["finance"], "Group", "SG"),
    ("priya", "Priya", "MDM Analyst", ["mdm_analyst"], "Group", "SG"),
    ("daniel", "Daniel", "BU Head", ["bu_head"], "SPD", "SG"),
    ("nurul", "Nurul", "Quality / Regulatory", ["quality_regulatory"], "Group", "MY"),
    ("meiling", "Mei Ling", "Business Support", ["business_support"], "Group", "SG"),
    ("huimin", "Hui Min", "Finance (second approver)", ["finance"], "Group", "SG"),
]

# Approvers beyond the personas (D-007 routing). Columns as PERSONAS + backup_for.
# - BU Head per entity: SPD (daniel, persona), QTS and QTG, each with a backup.
# - Quality / Regulatory per country (nurul covers MY), each with a backup in that country.
# - One backup each for Finance, Business Support and the MDM Analyst.
QR = ["quality_regulatory"]
BACKUPS = [
    ("kelvin", "Kelvin Ong", "Deputy BU Head (backup)", ["bu_head"], "SPD", "SG", "daniel"),
    ("victor", "Victor Lim", "BU Head", ["bu_head"], "QTS", "SG", ""),
    ("shanti", "Shanti Pillai", "Deputy BU Head (backup)", ["bu_head"], "QTS", "MY", "victor"),
    ("tuan", "Nguyễn Minh Tuấn", "BU Head", ["bu_head"], "QTG", "VN", ""),
    ("arif", "Arif Hakim", "Deputy BU Head (backup)", ["bu_head"], "QTG", "ID", "tuan"),
    ("siti", "Siti Aminah", "Finance Executive (backup)", ["finance"], "Group", "MY", "weijie"),
    ("joanne", "Joanne Yeo", "Quality / Regulatory (SG)", QR, "Group", "SG", ""),
    ("ratna", "Ratna Dewi", "Quality / Regulatory (ID)", QR, "Group", "ID", ""),
    ("lan", "Nguyễn Thị Lan", "Quality / Regulatory (VN)", QR, "Group", "VN", ""),
    ("pornthip", "Pornthip Siriwan", "Quality / Regulatory (TH)", QR, "Group", "TH", ""),
    ("kenneth", "Kenneth Ho", "Regulatory Affairs (backup, SG)", QR, "Group", "SG", "joanne"),
    (
        "hidayah",
        "Nur Hidayah Salleh",
        "Regulatory Affairs (backup, MY)",
        QR,
        "Group",
        "MY",
        "nurul",
    ),
    ("yoga", "Yoga Prasetyo", "Regulatory Affairs (backup, ID)", QR, "Group", "ID", "ratna"),
    ("binh", "Trần Quốc Bình", "Regulatory Affairs (backup, VN)", QR, "Group", "VN", "lan"),
    ("nattaya", "Nattaya Sombat", "Regulatory Affairs (backup, TH)", QR, "Group", "TH", "pornthip"),
    (
        "farah",
        "Farah Hassan",
        "Business Support (backup)",
        ["business_support"],
        "Group",
        "MY",
        "meiling",
    ),
    ("junhao", "Lim Jun Hao", "MDM Analyst (backup)", ["mdm_analyst"], "Group", "SG", "priya"),
]

# 9 invented staff names per country: entity index * 3 + (nn - 1)
STAFF_NAMES = {
    "SG": [
        "Jasmine Lee",
        "Ravi Kumar",
        "Melissa Goh",
        "Darren Tan",
        "Nur Aisyah Rahim",
        "Eugene Chua",
        "Priscilla Ng",
        "Arjun Menon",
        "Sharon Koh",
    ],
    "MY": [
        "Aisyah Ismail",
        "Lim Wei Ming",
        "Kavitha Raj",
        "Hafiz Abdullah",
        "Tan Mei Yee",
        "Suresh Pillai",
        "Nadia Kamal",
        "Ong Chee Keong",
        "Zulaikha Omar",
    ],
    "ID": [
        "Dewi Lestari",
        "Budi Santoso",
        "Rina Wijaya",
        "Agus Setiawan",
        "Sari Rahayu",
        "Hendra Gunawan",
        "Putri Maharani",
        "Yusuf Hidayat",
        "Indah Permata",
    ],
    "VN": [
        "Nguyễn Văn An",
        "Trần Thị Bích",
        "Lê Minh Quân",
        "Phạm Thu Hà",
        "Võ Quốc Bảo",
        "Đặng Thị Mai",
        "Hoàng Đức Huy",
        "Bùi Ngọc Trâm",
        "Đỗ Thanh Tùng",
    ],
    "TH": [
        "Somchai Wongsakul",
        "Pimchanok Srisuk",
        "Anan Chaiyaporn",
        "Kanokwan Boonmee",
        "Thanawat Rattanakul",
        "Siriporn Khamsri",
        "Nattapong Saelim",
        "Waraporn Chaiwong",
        "Krit Phromma",
    ],
}
PROC_NAMES = {
    "SG": ["Grace Teo", "Benjamin Lau"],
    "MY": ["Farid Yusof", "Chong Li Ying"],
    "ID": ["Wulan Sari", "Rizky Pratama"],
    "VN": ["Ngô Thị Hương", "Lý Văn Khoa"],
    "TH": ["Chanida Meesuk", "Pongsak Thongdee"],
}
COUNTRIES = ["SG", "MY", "ID", "VN", "TH"]
ENTITY_ORDER = ["SPD", "QTS", "QTG"]
REQ_TITLES = ["Sales Executive", "Sales Admin", "Product Specialist"]


def requestor_ids() -> list[tuple[str, str, str]]:
    """(user_id, entity, country) for every SAP creator code in bp_records."""
    return [
        (f"{e.lower()}.{c.lower()}{n:02d}", e, c)
        for e in ENTITY_ORDER
        for c in COUNTRIES
        for n in (1, 2, 3)
    ]


def user_rows() -> list[list]:
    rows: list[list] = []
    for uid, name, title, roles, ent, c in PERSONAS:
        rows.append([uid, name, title, "|".join(roles), ent, c, ""])
    for uid, name, title, roles, ent, c, backup in BACKUPS:
        rows.append([uid, name, title, "|".join(roles), ent, c, backup])
    for uid, ent, c in requestor_ids():
        n = int(uid[-2:])
        name = STAFF_NAMES[c][ENTITY_ORDER.index(ent) * 3 + n - 1]
        rows.append([uid, name, f"{REQ_TITLES[n - 1]}, {ent} {c}", "requestor", ent, c, ""])
    for c in COUNTRIES:
        for n in (1, 2):
            rows.append(
                [
                    f"proc.{c.lower()}{n:02d}",
                    PROC_NAMES[c][n - 1],
                    f"Procurement Officer, {c}",
                    "requestor",
                    "Group",
                    c,
                    "",
                ]
            )
    return rows


def requestors_for(entity: str, country: str) -> list[str]:
    """Requestor user IDs who raise MDM requests for an entity x country (personas included)."""
    ids = [uid for uid, e, c in requestor_ids() if e == entity and c == country]
    for uid, _, _, roles, e, c in PERSONAS:
        if "requestor" in roles and e == entity and c == country:
            ids.append(uid)
    return ids

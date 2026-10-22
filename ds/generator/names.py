"""Customer name specs: curated anchors plus templated names per country x segment.

Faker has no en_SG / ms_MY locale (D-014), so SG and MY names are templated here.
Faker id_ID / vi_VN are used only for doctor names in some clinic names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from anyascii import anyascii
from faker import Faker

SEGMENTS = ["public_hospital", "private_hospital", "laboratory", "clinic", "distributor"]


@dataclass
class NameSpec:
    """All the ways one legal entity can be written. Native script is kept for display."""

    country: str
    segment: str
    local: str  # trading name in native script / with diacritics
    english: str  # English or romanised trading name
    legal: str  # registered legal name (official script), with legal suffix
    legal_rom: str  # registered legal name, romanised / English
    city: str
    acronyms: tuple[str, ...] = ()
    lang_alts: tuple[str, ...] = ()  # other-language / expanded forms (for local_language dups)
    key: str = ""  # demo anchor key
    group_id: str | None = None
    pair_key: str | None = None  # similar_name_different_site pair
    forced_card_name: str | None = None  # anchors: exact CardName of the primary record

    @property
    def rom(self) -> str:
        if self.country == "TH":
            return self.english
        return anyascii(self.local) if self.country == "VN" else self.local

    def forms(self) -> dict[str, str]:
        return {
            "legal": self.legal,
            "legal_rom": self.legal_rom,
            "local": self.local,
            "rom": self.rom,
            "english": self.english,
        }

    def core_key(self) -> str:
        return norm_key(self.english)


def norm_key(s: str) -> str:
    s = anyascii(s).lower()
    s = re.sub(r"\b(pte|ltd|sdn|bhd|pt|tbk|co|jsc|pcl)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def make_spec(
    country: str,
    segment: str,
    local: str,
    english: str | None = None,
    legal: str | None = None,
    legal_rom: str | None = None,
    city: str = "",
    **kw,
) -> NameSpec:
    english = english or (anyascii(local) if country in ("VN", "TH") else local)
    legal = legal or local
    if legal_rom is None:
        if country == "VN":
            legal_rom = anyascii(legal)
        elif country == "TH":
            legal_rom = english if legal == local else english + " Co., Ltd."
        else:
            legal_rom = legal
    return NameSpec(country, segment, local, english, legal, legal_rom, city, **kw)


# --------------------------------------------------------------------------------------------
# Word lists (invented brand words; real public hospital names live in curated.py)
# --------------------------------------------------------------------------------------------

EN_WORDS = [
    "Apex",
    "Zenith",
    "Meridian",
    "Pinnacle",
    "Unity",
    "Crest",
    "Summit",
    "Helix",
    "Vertex",
    "Nova",
    "Primacare",
    "Vista",
    "Aurora",
    "Emerald",
    "Sapphire",
    "Keystone",
    "Beacon",
    "Evergreen",
    "Horizon",
    "Lumen",
    "Cedar",
    "Maple",
    "Banyan",
    "Tembusu",
    "Raintree",
    "Marina",
    "Bayfront",
    "Sterling",
    "Pacifica",
    "Silverline",
    "Northstar",
    "Bluewater",
    "Greenleaf",
    "Lotus",
    "Jade",
    "Pearl",
    "Starlight",
    "Solace",
    "Trinity",
    "Vitalis",
    "Wellspring",
    "Clearview",
    "Brightway",
    "Oakwood",
    "Kingfisher",
    "Harmony",
    "Radiant",
    "Corall",
    "Ivory",
    "Avalon",
]
SG_SURNAMES = [
    "Tan",
    "Lim",
    "Lee",
    "Ng",
    "Ong",
    "Wong",
    "Goh",
    "Chua",
    "Chan",
    "Koh",
    "Teo",
    "Ang",
    "Yeo",
    "Tay",
    "Ho",
    "Low",
    "Toh",
    "Sim",
    "Chong",
    "Chia",
    "Kumar",
    "Rahman",
    "Pillai",
    "Nair",
]
SG_PLACES = [
    "Toa Payoh",
    "Bedok North",
    "Jurong West",
    "Clementi",
    "Bishan",
    "Serangoon",
    "Hougang",
    "Punggol",
    "Sengkang",
    "Yishun",
    "Ang Mo Kio",
    "Bukit Timah",
    "Tiong Bahru",
    "Queenstown",
    "Pasir Ris",
    "Bukit Merah",
    "Holland Village",
    "Katong",
    "Choa Chu Kang",
    "Bukit Batok",
]
MY_WORDS = [
    "Mesra",
    "Bestari",
    "Harmoni",
    "Murni",
    "Setia",
    "Cahaya",
    "Damai",
    "Sejahtera",
    "Bakti",
    "Permata",
    "Indah",
    "Mutiara",
    "Seri",
    "Gemilang",
    "Bahagia",
    "Kasih",
    "Wawasan",
    "Delima",
    "Kenanga",
    "Cempaka",
    "Melati",
    "Suria",
    "Nilam",
    "Teratai",
]
MY_SURNAMES = [
    "Lim",
    "Tan",
    "Wong",
    "Lee",
    "Ong",
    "Chong",
    "Raju",
    "Kumar",
    "Ismail",
    "Rahman",
    "Hashim",
    "Yusof",
    "Siva",
    "Chin",
    "Teh",
    "Aziz",
    "Nair",
    "Lau",
]
MY_CITIES = [
    ("Kuala Lumpur", 5),
    ("Petaling Jaya", 2),
    ("Shah Alam", 1),
    ("Subang Jaya", 1),
    ("Johor Bahru", 2),
    ("Georgetown", 2),
    ("Ipoh", 1),
    ("Kuching", 1),
    ("Kota Kinabalu", 1),
    ("Seremban", 1),
    ("Melaka", 1),
    ("Kuantan", 1),
    ("Klang", 1),
    ("Cheras", 1),
]
ID_WORDS = [
    "Sehat",
    "Husada",
    "Bakti",
    "Cahaya",
    "Permata",
    "Mulia",
    "Bunda",
    "Insani",
    "Utama",
    "Sejahtera",
    "Kasih",
    "Sinar",
    "Pelita",
    "Anugerah",
    "Karya",
    "Sentra",
    "Abdi",
    "Bina",
    "Citra",
    "Dharma",
    "Graha",
    "Hikmah",
    "Kurnia",
    "Lestari",
    "Makmur",
    "Nirmala",
    "Restu",
    "Sahabat",
    "Tirta",
    "Wijaya",
    "Medika",
    "Mandiri",
    "Aulia",
    "Berkah",
    "Amanah",
    "Ihsan",
]
ID_CITIES = [
    ("Jakarta", 6),
    ("Surabaya", 2),
    ("Bandung", 2),
    ("Medan", 2),
    ("Semarang", 1),
    ("Makassar", 1),
    ("Yogyakarta", 1),
    ("Denpasar", 1),
    ("Palembang", 1),
    ("Tangerang", 1),
    ("Bekasi", 1),
    ("Bogor", 1),
    ("Malang", 1),
    ("Balikpapan", 1),
]
VN_WORDS = [
    "Phúc An",
    "Minh Khang",
    "Hòa Bình",
    "An Khang",
    "Thiên Phúc",
    "Việt Mỹ",
    "Đông Á",
    "Nam Việt",
    "Tân Phú",
    "Bình An",
    "Hưng Thịnh",
    "Hồng Đức",
    "Thành Công",
    "Hạnh Phúc",
    "Trường An",
    "Bảo Châu",
    "Phương Đông",
    "Hoàng Long",
    "Quang Minh",
    "Ánh Dương",
    "Việt Hàn",
    "Việt Nhật",
    "Đức Tâm",
    "Nhân Ái",
    "Thiện Tâm",
    "Tâm Đức",
    "Kim Ngân",
    "Phú Mỹ",
    "Vạn Phúc",
    "Mỹ Đức",
    "Thanh Bình",
    "An Phước",
    "Sao Mai",
    "Hải Đăng",
    "Bách Khoa",
    "Tín Đức",
]
VN_CITIES = [
    # (english, vietnamese, weight)
    ("Ho Chi Minh City", "Sài Gòn", 5),
    ("Hanoi", "Hà Nội", 4),
    ("Da Nang", "Đà Nẵng", 2),
    ("Hai Phong", "Hải Phòng", 1),
    ("Can Tho", "Cần Thơ", 1),
    ("Hue", "Huế", 1),
    ("Nha Trang", "Nha Trang", 1),
    ("Bien Hoa", "Biên Hòa", 1),
    ("Vung Tau", "Vũng Tàu", 1),
]
TH_WORDS = [
    ("สยาม", "Siam"),
    ("รุ่งเรือง", "Rungruang"),
    ("ศรีสวัสดิ์", "Srisawat"),
    ("เจริญสุข", "Charoensuk"),
    ("พัฒนา", "Phatthana"),
    ("สุขสวัสดิ์", "Suksawat"),
    ("ไทยเมด", "Thai Med"),
    ("เกษมสุข", "Kasemsuk"),
    ("วัฒนา", "Watthana"),
    ("ปิยะมิตร", "Piyamit"),
    ("ศุภมิตร", "Suphamit"),
    ("บูรพา", "Burapha"),
    ("อุดมสุข", "Udomsuk"),
    ("ประชาสุข", "Prachasuk"),
    ("มิตรภาพ", "Mittraphap"),
    ("รักษ์สุข", "Raksuk"),
    ("ชัยพฤกษ์", "Chaiyaphruek"),
    ("ทองคำ", "Thongkham"),
    ("ศรีเมือง", "Si Mueang"),
    ("นวเวช", "Nawavej"),
    ("ธนารักษ์", "Thanarak"),
    ("พรประเสริฐ", "Pornprasert"),
    ("สุขใจ", "Sukjai"),
    ("เมตตา", "Metta"),
]
TH_PLACES = [
    # (thai, english, city, weight)
    ("ลาดพร้าว", "Lat Phrao", "Bangkok", 2),
    ("บางนา", "Bang Na", "Bangkok", 2),
    ("รัชดา", "Ratchada", "Bangkok", 2),
    ("สาทร", "Sathorn", "Bangkok", 2),
    ("ทองหล่อ", "Thong Lo", "Bangkok", 1),
    ("รังสิต", "Rangsit", "Pathum Thani", 1),
    ("นนทบุรี", "Nonthaburi", "Nonthaburi", 1),
    ("เชียงใหม่", "Chiang Mai", "Chiang Mai", 2),
    ("ขอนแก่น", "Khon Kaen", "Khon Kaen", 1),
    ("หาดใหญ่", "Hat Yai", "Hat Yai", 1),
    ("พัทยา", "Pattaya", "Pattaya", 1),
    ("อุดรธานี", "Udon Thani", "Udon Thani", 1),
    ("โคราช", "Korat", "Nakhon Ratchasima", 1),
    ("หัวหิน", "Hua Hin", "Hua Hin", 1),
]


class NameFactory:
    """Templated names. `used` holds normalised core keys so no two golden share a name."""

    def __init__(self, rng: np.random.Generator, seed: int, used: set[str]):
        self.rng = rng
        self.used = used
        self.fakers: dict[str, Faker] = {}
        for i, loc in enumerate(["id_ID", "vi_VN"]):
            f = Faker(loc)
            f.seed_instance(seed * 100 + i)
            self.fakers[loc] = f

    # ---- helpers -------------------------------------------------------------------------
    def pick(self, items: list):
        return items[int(self.rng.integers(len(items)))]

    def wpick(self, items: list[tuple]):
        w = np.array([t[-1] for t in items], dtype=float)
        return items[int(self.rng.choice(len(items), p=w / w.sum()))]

    def chance(self, p: float) -> bool:
        return bool(self.rng.random() < p)

    def build(self, country: str, segment: str) -> NameSpec:
        fn = getattr(self, f"_{country.lower()}")
        for _ in range(200):
            spec = fn(segment)
            k = spec.core_key()
            if k not in self.used:
                self.used.add(k)
                return spec
        raise RuntimeError(f"name pool exhausted for {country}/{segment}")

    # ---- Singapore -----------------------------------------------------------------------
    def _sg(self, seg: str) -> NameSpec:
        w = self.pick(EN_WORDS)
        if seg == "public_hospital":
            local = f"{self.pick(SG_PLACES)} Community Hospital"
            return make_spec("SG", seg, local, legal=f"{local} Ltd", city="Singapore")
        if seg == "private_hospital":
            kind = self.pick(
                [
                    "Specialist Hospital",
                    "Medical Centre",
                    "Surgical Centre",
                    "Heart & Vascular Centre",
                    "Women's Hospital",
                ]
            )
            local = f"{w} {kind}"
        elif seg == "laboratory":
            kind = self.pick(
                ["Diagnostics", "Laboratories", "Pathology Lab", "Clinical Lab", "BioAnalytics"]
            )
            local = f"{w} {kind}"
        elif seg == "clinic":
            r = self.rng.random()
            if r < 0.4:
                local = f"{self.pick(SG_SURNAMES)} Family Clinic {self.pick(SG_PLACES)}"
            elif r < 0.75:
                local = f"{w} Medical Clinic {self.pick(SG_PLACES)}"
            else:
                local = f"{self.pick(SG_SURNAMES)} & {self.pick(SG_SURNAMES)} Surgery"
        else:
            local = f"{w} {self.pick(['Medical Supplies', 'Scientific', 'Healthcare Trading'])}"
        return make_spec("SG", seg, local, legal=f"{local} Pte Ltd", city="Singapore")

    # ---- Malaysia ------------------------------------------------------------------------
    def _my(self, seg: str) -> NameSpec:
        city = self.wpick(MY_CITIES)[0]
        w, mw = self.pick(EN_WORDS), self.pick(MY_WORDS)
        alts: tuple[str, ...] = ()
        if seg == "public_hospital":
            local, english = f"Hospital {city}", f"{city} Hospital"
            return make_spec("MY", seg, local, english, city=city, lang_alts=(english,))
        if seg == "private_hospital":
            if self.chance(0.5):
                local = english = f"{w} {self.pick(['Specialist Hospital', 'Medical Centre'])}"
            elif self.chance(0.5):
                local, english = f"Hospital Pakar {mw}", f"{mw} Specialist Hospital"
            else:
                local, english = f"Pusat Perubatan {mw}", f"{mw} Medical Centre"
            legal = f"{local} Sdn Bhd"
        elif seg == "laboratory":
            if self.chance(0.5):
                local = english = f"{w} {self.pick(['Diagnostics', 'Lab Services'])}"
            else:
                local, english = f"Makmal Patologi {mw}", f"{mw} Pathology Laboratory"
            legal = f"{local} Sdn Bhd"
        elif seg == "clinic":
            x = self.pick(MY_SURNAMES) if self.chance(0.5) else mw
            if self.chance(0.6):
                local, english = f"Klinik {x} {city}", f"{x} Clinic {city}"
            else:
                local, english = f"Poliklinik {x}", f"{x} Polyclinic"
            legal = f"{local} Sdn Bhd" if self.chance(0.4) else local
        else:
            if self.chance(0.5):
                local = english = f"{w} Medical Supplies"
            else:
                local, english = f"{mw} Saintifik", f"{mw} Scientific"
            legal = f"{local} Sdn Bhd"
        if english != local:
            alts = (english,)
        return make_spec("MY", seg, local, english, legal=legal, city=city, lang_alts=alts)

    # ---- Indonesia -----------------------------------------------------------------------
    def _id(self, seg: str) -> NameSpec:
        city = self.wpick(ID_CITIES)[0]
        a, b = self.pick(ID_WORDS), self.pick(ID_WORDS)
        core = f"{a} {b}" if a != b else a
        if seg == "public_hospital":
            local = f"RSUD {city}"
            return make_spec(
                "ID",
                seg,
                local,
                f"{city} Regional Hospital",
                legal=f"Rumah Sakit Umum Daerah {city}",
                city=city,
                lang_alts=(f"Rumah Sakit Umum Daerah {city}", f"{city} Regional Hospital"),
            )
        if seg == "private_hospital":
            local, english = f"RS {core}", f"{core} Hospital"
            legal = f"PT Rumah Sakit {core}" + (" Tbk" if self.chance(0.1) else "")
            alts = (f"Rumah Sakit {core}", english)
        elif seg == "laboratory":
            local, english = f"Laboratorium Klinik {core}", f"{core} Clinical Laboratory"
            legal = f"PT Laboratorium Klinik {core}"
            alts = (english,)
        elif seg == "clinic":
            r = self.rng.random()
            if r < 0.3:
                doc = self.fakers["id_ID"].name()
                doc = re.sub(r"^(dr\.|Dr\.|Ir\.|Drs\.|Hj\.|H\.)\s*", "", doc)
                doc = re.sub(r",.*$", "", doc)
                local, english = f"Klinik dr. {doc}", f"Dr. {doc} Clinic"
            elif r < 0.65:
                local, english = f"Klinik Pratama {core}", f"{core} Primary Clinic"
            else:
                local, english = f"Klinik {core}", f"{core} Clinic"
            legal = local
            alts = (english,)
        else:
            local, english = f"{core} Medika Indonesia", f"{core} Medical Indonesia"
            legal = f"PT {local}" + (" Tbk" if self.chance(0.2) else "")
            alts = (english,)
        return make_spec("ID", seg, local, english, legal=legal, city=city, lang_alts=alts)

    # ---- Vietnam -------------------------------------------------------------------------
    def _vn(self, seg: str) -> NameSpec:
        city_en, city_vn, _ = self.wpick(VN_CITIES)
        vw = self.pick(VN_WORDS)
        if self.chance(0.3):
            vw = f"{vw} {city_vn}"
        vr = anyascii(vw)
        if seg == "public_hospital":
            local = f"Bệnh viện Đa khoa {city_vn}"
            return make_spec(
                "VN", seg, local, f"{anyascii(city_vn)} General Hospital", city=city_en
            )
        if seg == "private_hospital":
            if self.chance(0.5):
                local, english = f"Bệnh viện Đa khoa {vw}", f"{vr} General Hospital"
                legal = f"Công ty Cổ phần Bệnh viện Đa khoa {vw}"
                alts = (english, f"{vr} General Hospital JSC")
            else:
                local, english = f"Bệnh viện Quốc tế {vw}", f"{vr} International Hospital"
                legal = f"Công ty TNHH Bệnh viện Quốc tế {vw}"
                alts = (english,)
        elif seg == "laboratory":
            local, english = f"Trung tâm Xét nghiệm {vw}", f"{vr} Laboratory Center"
            legal = f"Công ty TNHH Xét nghiệm Y khoa {vw}"
            alts = (english, f"{vr} Medical Laboratory Co., Ltd")
        elif seg == "clinic":
            if self.chance(0.25):
                doc = self.fakers["vi_VN"].name()
                local, english = (
                    f"Phòng khám Nhi BS. {doc}",
                    f"Dr. {anyascii(doc)} Paediatric Clinic",
                )
            else:
                local, english = f"Phòng khám Đa khoa {vw}", f"{vr} General Clinic"
            legal = f"Công ty TNHH {local}" if self.chance(0.4) else local
            alts = (english,)
        else:
            local, english = f"Thiết bị Y tế {vw}", f"{vr} Medical Equipment"
            kind = "TNHH" if self.chance(0.6) else "Cổ phần"
            legal = f"Công ty {kind} Thiết bị Y tế {vw}"
            alts = (english, f"{vr} Medical Equipment " + ("Co., Ltd" if kind == "TNHH" else "JSC"))
        return make_spec("VN", seg, local, english, legal=legal, city=city_en, lang_alts=alts)

    # ---- Thailand ------------------------------------------------------------------------
    def _th(self, seg: str) -> NameSpec:
        th, en = self.pick(TH_WORDS)
        pth, pen, city, _ = self.wpick(TH_PLACES)
        if self.chance(0.45):
            th, en = f"{th} {pth}", f"{en} {pen}"
        else:
            city = "Bangkok" if self.chance(0.6) else city
        if seg == "public_hospital":
            local, english = f"โรงพยาบาล{pth}", f"{pen} Hospital"
            return make_spec("TH", seg, local, english, city=city, lang_alts=(english,))
        if seg == "private_hospital":
            local, english = f"โรงพยาบาล{th}", f"{en} Hospital"
            if self.chance(0.15):
                legal, legal_rom = f"บริษัท โรงพยาบาล{th} จำกัด (มหาชน)", f"{en} Hospital PCL"
            else:
                legal, legal_rom = f"บริษัท โรงพยาบาล{th} จำกัด", f"{en} Hospital Co., Ltd."
        elif seg == "laboratory":
            if self.chance(0.5):
                local, english = f"{th} แล็บ", f"{en} Lab"
            else:
                local, english = f"ห้องปฏิบัติการ{th}", f"{en} Laboratory"
            legal, legal_rom = f"บริษัท {local} จำกัด", f"{english} Co., Ltd."
        elif seg == "clinic":
            if self.chance(0.5):
                local, english = f"คลินิกเวชกรรม{th}", f"{en} Medical Clinic"
            else:
                local, english = f"คลินิก{th}", f"{en} Clinic"
            legal, legal_rom = local, english
        else:
            local, english = f"{th} เมดิคอล ซัพพลาย", f"{en} Medical Supply"
            legal, legal_rom = f"บริษัท {local} จำกัด", f"{english} Co., Ltd."
        return make_spec(
            "TH",
            seg,
            local,
            english,
            legal=legal,
            legal_rom=legal_rom,
            city=city,
            lang_alts=(english,),
        )


def segment_counts(n: int, mix: dict[str, float]) -> dict[str, int]:
    """Largest-remainder allocation, ties broken by SEGMENTS order."""
    return largest_remainder(n, {s: mix[s] for s in SEGMENTS})


def largest_remainder(n: int, shares: dict[str, float]) -> dict[str, int]:
    keys = list(shares)
    total = sum(shares.values())
    raw = {k: n * shares[k] / total for k in keys}
    out = {k: int(raw[k]) for k in keys}
    rem = n - sum(out.values())
    order = sorted(keys, key=lambda k: (-(raw[k] - out[k]), keys.index(k)))
    for k in order[:rem]:
        out[k] += 1
    return out

"""Name transformations that turn a source CardName into a labelled duplicate (data-spec §4.1).

Each function returns the new name, or None when the transformation does not apply to this
source (the caller then tries another record or another type).
"""

from __future__ import annotations

import re

import numpy as np
from anyascii import anyascii

from .names import NameSpec, norm_key

DUP_TYPES = [
    "cross_entity_recreate",
    "abbreviation",
    "suffix_punctuation",
    "diacritics",
    "local_language",
    "typo",
    "missing_tax_id",
]

# Legal suffixes recognised for the toggle (order matters: longest first)
_SUFFIX_RE = re.compile(
    r"(\s*\((S|M)\))?\s+(Pte\.? Ltd\.?|Sdn\.? Bhd\.?|Co\., Ltd\.?|Co\.,Ltd|PCL|Tbk\.?|JSC|Ltd)$"
)
_PREFIX_RE = re.compile(r"^(PT\.? |Công ty (TNHH|Cổ phần) |Cong ty (TNHH|Co phan) )")

_ABBREV = [
    (r"\bRumah Sakit Umum Pusat\b", "RSUP"),
    (r"\bRumah Sakit Umum Daerah\b", "RSUD"),
    (r"\bRumah Sakit\b", "RS"),
    (r"\bWomen's and Children's\b", "W&C"),
    (r"\bHospital\b", "Hosp."),
    (r"\bMedical\b", "Med."),
    (r"\bCentre\b", "Ctr"),
    (r"\bCenter\b", "Ctr"),
    (r"\bLaboratories\b", "Labs"),
    (r"\bLaboratory\b", "Lab"),
    (r"\bLaboratorium\b", "Lab."),
    (r"\bDiagnostics\b", "Diag."),
    (r"\bInternational\b", "Intl"),
    (r"\bNational\b", "Natl"),
    (r"\bUniversity\b", "Univ."),
    (r"\bSpecialist\b", "Spec."),
    (r"\bGeneral\b", "Gen."),
    (r"\bSupplies\b", "Supp."),
    (r"\bScientific\b", "Sci."),
    (r"\bSingapore\b", "S'pore"),
    (r"\bPusat Perubatan\b", "PP"),
    (r"\bKlinik Pratama\b", "KP"),
    (r"\bBệnh viện\b", "BV"),
    (r"\bBenh vien\b", "BV"),
    (r"\bPhòng khám\b", "PK"),
    (r"\bPhong kham\b", "PK"),
    (r"\bĐa khoa\b", "ĐK"),
    (r"\bDa khoa\b", "DK"),
    (r"\bCông ty\b", "Cty"),
    (r"\bCong ty\b", "Cty"),
    (r"\bTrung tâm\b", "TT"),
    (r"\bTrung tam\b", "TT"),
    (r"\bXét nghiệm\b", "XN"),
    (r"\bXet nghiem\b", "XN"),
    (r"\bThiết bị Y tế\b", "TBYT"),
    (r"\bThiet bi Y te\b", "TBYT"),
    (r"\bQuốc tế\b", "QT"),
    (r"\bQuoc te\b", "QT"),
    (r"\bTrung ương\b", "TW"),
]
_TH_ABBREV = [("โรงพยาบาล", "รพ."), ("บริษัท ", "บจก. "), ("คลินิกเวชกรรม", "คลินิก")]

_KEYBOARD = {
    "a": "sq",
    "b": "vn",
    "c": "xv",
    "d": "sf",
    "e": "wr",
    "f": "dg",
    "g": "fh",
    "h": "gj",
    "i": "uo",
    "j": "hk",
    "k": "jl",
    "l": "k",
    "m": "n",
    "n": "bm",
    "o": "ip",
    "p": "o",
    "q": "w",
    "r": "et",
    "s": "ad",
    "t": "ry",
    "u": "yi",
    "v": "cb",
    "w": "qe",
    "x": "zc",
    "y": "tu",
    "z": "x",
}


def _pick(rng: np.random.Generator, items: list):
    return items[int(rng.integers(len(items)))]


def _differs(a: str, b: str | None) -> bool:
    return b is not None and b.strip() != "" and b != a and len(b) <= 100


def has_suffix(name: str) -> bool:
    return bool(
        _SUFFIX_RE.search(name)
        or _PREFIX_RE.search(name)
        or ("จำกัด" in name and name.startswith("บริษัท"))
    )


def strip_suffix(name: str) -> str:
    out = _PREFIX_RE.sub("", _SUFFIX_RE.sub("", name))
    if out.startswith("บริษัท ") and "จำกัด" in out:
        out = out.removeprefix("บริษัท ").replace(" จำกัด (มหาชน)", "").replace(" จำกัด", "")
    return out.strip()


def add_suffix(name: str, spec: NameSpec) -> str:
    c = spec.country
    if c == "SG":
        return f"{name} Pte Ltd"
    if c == "MY":
        return f"{name} Sdn Bhd"
    if c == "ID":
        return f"PT {name}"
    if c == "VN":
        return ("Công ty TNHH " if anyascii(name) != name else "Cong ty TNHH ") + name
    if re.search(r"[฀-๿]", name):
        return f"บริษัท {name} จำกัด"
    return f"{name} Co., Ltd."


# --------------------------------------------------------------------------------------------
def cross_entity_recreate(src: str, spec: NameSpec, rng: np.random.Generator) -> str | None:
    """Another BU re-creates the customer, typing the name slightly differently."""
    # one op per group, at most two groups (so we never stack two location suffixes)
    groups: list[list] = []
    if spec.segment != "public_hospital":
        groups.append([lambda s: strip_suffix(s) if has_suffix(s) else add_suffix(s, spec)])
    spelling = []
    if "Centre" in src or "Center" in src:
        spelling.append(
            lambda s: (
                s.replace("Centre", "Center") if "Centre" in s else s.replace("Center", "Centre")
            )
        )
    if " and " in src or " & " in src:
        spelling.append(
            lambda s: s.replace(" and ", " & ") if " and " in s else s.replace(" & ", " and ")
        )
    if spelling:
        groups.append(spelling)
    city = spec.city
    location = [
        lambda s: f"{s} - {_pick(rng, ['Lab Dept', 'Laboratory', 'Procurement', 'Pathology'])}"
    ]
    if anyascii(city).lower() not in anyascii(src).lower():
        location += [lambda s: f"{s} - {city}", lambda s: f"{s} ({city})"]
    groups.append(location)
    case = []
    if re.search(r"[A-Za-z]", src) and src != src.title():
        case.append(lambda s: s.title())
    if src.startswith(("Bệnh viện", "Phòng khám", "Trung tâm")):
        case.append(lambda s: " ".join(w[:1].upper() + w[1:] for w in s.split(" ")))
    if case:
        groups.append(case)
    n_groups = 2 if rng.random() < 0.3 and len(groups) > 1 else 1
    out = src
    for gi in sorted(int(j) for j in rng.permutation(len(groups))[:n_groups]):
        out = _pick(rng, groups[gi])(out)
    return out if _differs(src, out) else None


def abbreviation(src: str, spec: NameSpec, rng: np.random.Generator) -> str | None:
    """Acronym (NUH) or abbreviated words (Natl Univ. Hosp.)."""
    if spec.acronyms and rng.random() < 0.6:
        out = spec.acronyms[0]
        return out if _differs(src, out) else None
    out = src
    for th, short in _TH_ABBREV:
        if th in out:
            out = out.replace(th, short, 1)
    applicable = [(p, r) for p, r in _ABBREV if re.search(p, out)]
    if applicable:
        keep = [a for a in applicable if rng.random() < 0.7] or [applicable[0]]
        for p, r in keep:
            out = re.sub(p, r, out)
    if _differs(src, out):
        return out
    if spec.acronyms:
        return spec.acronyms[0] if _differs(src, spec.acronyms[0]) else None
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z']+", strip_suffix(src)) if len(w) > 2]
    if len(words) >= 3:
        acr = "".join(w[0].upper() for w in words)
        return acr if _differs(src, acr) else None
    return None


def suffix_punctuation(src: str, spec: NameSpec, rng: np.random.Generator) -> str | None:
    """'BioLab Pte Ltd' -> 'BIOLAB PTE. LTD.'; dots, commas, case and legal-form spelling."""
    swaps = [
        ("Pte Ltd", ["Pte. Ltd.", "PTE LTD", "Pte. Ltd", "Private Limited"]),
        ("Sdn Bhd", ["Sdn. Bhd.", "SDN BHD", "Sendirian Berhad", "Sdn.Bhd."]),
        ("Co., Ltd.", ["Co.,Ltd", "CO LTD", "Company Limited", "Co. Ltd"]),
        ("Co., Ltd", ["Co.,Ltd.", "CO., LTD", "Company Limited"]),
        ("Tbk", ["Tbk.", "TBK"]),
        ("PCL", ["Public Company Limited", "P.C.L."]),
        ("JSC", ["J.S.C", "Joint Stock Company"]),
        ("Công ty TNHH", ["CÔNG TY TNHH", "Công Ty TNHH"]),
        ("Cong ty TNHH", ["CONG TY TNHH", "Cong Ty TNHH"]),
        ("Công ty Cổ phần", ["CÔNG TY CỔ PHẦN", "Công Ty Cổ Phần"]),
        ("จำกัด (มหาชน)", ["จำกัด(มหาชน)"]),
        (" จำกัด", ["จำกัด"]),
    ]
    out = src
    if src.startswith("PT "):
        out = _pick(rng, [f"PT. {src[3:]}", f"{src[3:]}, PT", f"P.T. {src[3:]}"])
    else:
        for old, news in swaps:
            if old in src:
                out = src.replace(old, _pick(rng, news))
                break
    if out == src:
        generic = [
            src.upper(),
            src.replace("'", ""),
            src.replace(". ", " ").replace(".", ""),
            f"{src}.",
            src.replace("-", " "),
        ]
        out = _pick(rng, [g for g in generic if g != src] or [src.upper()])
    elif rng.random() < 0.5 and re.search(r"[a-z]", out):
        out = out.upper()
    return out if _differs(src, out) else None


def diacritics(src: str, spec: NameSpec, rng: np.random.Generator) -> str | None:
    """Vietnamese with and without diacritics."""
    if spec.country != "VN":
        return None
    if anyascii(src) != src:
        return anyascii(src)
    for form in (spec.legal, spec.local, *spec.lang_alts):
        if anyascii(form) != form and anyascii(form) == src:
            return form
    return None


def local_language(src: str, spec: NameSpec, rng: np.random.Generator) -> str | None:
    """Swap language or script: Rumah Sakit/RS/English, Thai script/English, Malay/English."""

    def same(a: str, b: str) -> bool:
        return anyascii(a).lower().strip() == anyascii(b).lower().strip()

    def core(a: str) -> str:
        return norm_key(strip_suffix(a))

    english_family = same(src, spec.english) or (same(src, spec.legal_rom) and spec.country == "TH")
    if english_family:
        cands = [spec.local, spec.rom, *spec.lang_alts]
    else:
        cands = [spec.english, *spec.lang_alts]
    # a real language/script switch: not the same name with only a suffix or diacritics changed
    cands = [c for c in dict.fromkeys(cands) if not same(c, src) and core(c) != core(src)]
    if not cands:
        return None
    out = _pick(rng, cands)
    return out if _differs(src, out) else None


def typo(src: str, spec: NameSpec, rng: np.random.Generator) -> str | None:
    """1-2 character edits, or two words swapped."""
    words = src.split(" ")
    if len(words) >= 3 and rng.random() < 0.2:
        i = int(rng.integers(len(words) - 1))
        words[i], words[i + 1] = words[i + 1], words[i]
        out = " ".join(words)
        return out if _differs(src, out) else None
    chars = list(src)
    for _ in range(1 + int(rng.random() < 0.35)):
        pos = [i for i in range(1, len(chars)) if chars[i].isalpha()]
        if not pos:
            return None
        i = _pick(rng, pos)
        c = chars[i]
        op = _pick(
            rng, ["sub", "del", "dup", "swap"] if c.lower() in _KEYBOARD else ["del", "dup", "swap"]
        )
        if op == "sub":
            n = _pick(rng, list(_KEYBOARD[c.lower()]))
            chars[i] = n.upper() if c.isupper() else n
        elif op == "del":
            del chars[i]
        elif op == "dup":
            chars.insert(i, c)
        elif i + 1 < len(chars):
            chars[i], chars[i + 1] = chars[i + 1], chars[i]
    out = "".join(chars)
    return out if _differs(src, out) else None


def missing_tax_id(src: str, spec: NameSpec, rng: np.random.Generator) -> str | None:
    """Same name (sometimes re-cased); the tax ID is blank or malformed."""
    if rng.random() < 0.3 and re.search(r"[a-z]", src):
        return src.upper()
    return src


TRANSFORMS = {
    "cross_entity_recreate": cross_entity_recreate,
    "abbreviation": abbreviation,
    "suffix_punctuation": suffix_punctuation,
    "diacritics": diacritics,
    "local_language": local_language,
    "typo": typo,
    "missing_tax_id": missing_tax_id,
}

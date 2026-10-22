"""Layers 2 and 3 of the duplicate check: normalise names and other keys (D-005).

Pure functions. The original string is always kept for display; everything here is only
used for comparison.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml
from anyascii import anyascii
from cleanco import basename

_HERE = Path(__file__).parent

COUNTRY_NAMES = {
    "SG": {"singapore"},
    "MY": {"malaysia"},
    "ID": {"indonesia"},
    "VN": {"vietnam"},
    "TH": {"thailand"},
}
_ROMAN = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}


# --------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Vocab:
    thai_script: tuple[tuple[str, str], ...]
    thai_legal: tuple[str, ...]
    abbreviations: dict[tuple[str, ...], tuple[str, ...]]
    translations: dict[tuple[str, ...], tuple[str, ...]]
    stopwords: frozenset[str]
    aliases: dict[str, str]
    prefixes: dict[str, tuple[tuple[str, ...], ...]]
    suffixes: dict[str, tuple[tuple[str, ...], ...]]


def _phrase_map(d: dict[str, str]) -> dict[tuple[str, ...], tuple[str, ...]]:
    return {tuple(k.split()): tuple(str(v).split()) for k, v in (d or {}).items()}


def _by_len(items: list[str]) -> tuple[tuple[str, ...], ...]:
    return tuple(sorted({tuple(s.split()) for s in items}, key=len, reverse=True))


@lru_cache(maxsize=4)
def load_vocab(terms_path: str | None = None, suffixes_path: str | None = None) -> Vocab:
    terms = yaml.safe_load(Path(terms_path or _HERE / "terms.yaml").read_text(encoding="utf-8"))
    sfx = yaml.safe_load(Path(suffixes_path or _HERE / "suffixes.yaml").read_text(encoding="utf-8"))
    common = sfx.get("common", {})
    prefixes: dict[str, tuple[tuple[str, ...], ...]] = {}
    suffixes: dict[str, tuple[tuple[str, ...], ...]] = {}
    for country in ("SG", "MY", "ID", "VN", "TH", "_"):
        spec = sfx.get(country, {}) if country != "_" else {}
        prefixes[country] = _by_len(list(spec.get("prefix", [])) + list(common.get("prefix", [])))
        suffixes[country] = _by_len(list(spec.get("suffix", [])) + list(common.get("suffix", [])))

    def nfkc(x: str) -> str:  # names are NFKC-normalised before lookup (ำ decomposes)
        return unicodedata.normalize("NFKC", x)

    thai = sorted(
        ((nfkc(k), v) for k, v in (terms.get("thai_script") or {}).items()),
        key=lambda kv: len(kv[0]),
        reverse=True,
    )
    return Vocab(
        thai_script=tuple(thai),
        thai_legal=tuple(
            sorted((nfkc(x) for x in sfx.get("thai_script", [])), key=len, reverse=True)
        ),
        abbreviations=_phrase_map(terms.get("abbreviations")),
        translations=_phrase_map(terms.get("translations")),
        stopwords=frozenset(terms.get("stopwords") or []),
        aliases={str(k).lower(): str(v) for k, v in (terms.get("aliases") or {}).items()},
        prefixes=prefixes,
        suffixes=suffixes,
    )


# --------------------------------------------------------------------------------------------
_THAI_PREPOSED = "เแโใไ"  # เ แ โ ใ ไ are written before the consonant
_THAI_CONS = "ก-ฮ"
_THAI_RE = re.compile("[฀-๿]")


def has_thai(s: str) -> bool:
    return bool(_THAI_RE.search(s))


def romanise_thai(s: str) -> str:
    """Rough Thai romanisation for candidate retrieval only (D-005 / D-014).

    anyascii transliterates letter by letter in written order. Two cheap fixes make the
    result closer to how people romanise: pre-posed vowels are moved after their consonant
    (ไทย -> "thai" not "aithy"), and a consonant carrying the silent mark ์ is dropped.
    """
    s = re.sub(f"[{_THAI_CONS}]์", "", s)
    s = re.sub(f"([{_THAI_PREPOSED}])([{_THAI_CONS}])", r"\2\1", s)
    return anyascii(s)


def to_ascii(s: str) -> str:
    """NFKC, then anyascii (strips Vietnamese diacritics, đ -> d, rough Thai romanisation)."""
    s = unicodedata.normalize("NFKC", s)
    return romanise_thai(s) if has_thai(s) else anyascii(s)


def simple_tokens(s: str) -> list[str]:
    s = to_ascii(s).lower().replace("&", " and ").replace("'", "").replace("’", "")
    return [t for t in re.split(r"[^a-z0-9]+", s) if t]


def _replace_phrases(
    tokens: list[str], mapping: dict[tuple[str, ...], tuple[str, ...]], hits: list
) -> list[str]:
    if not mapping:
        return tokens
    max_len = max(len(k) for k in mapping)
    out: list[str] = []
    i = 0
    while i < len(tokens):
        for n in range(min(max_len, len(tokens) - i), 0, -1):
            key = tuple(tokens[i : i + n])
            if key in mapping:
                rep = mapping[key]
                if rep != key:
                    hits.append((" ".join(key), " ".join(rep)))
                out.extend(rep)
                i += n
                break
        else:
            out.append(tokens[i])
            i += 1
    return out


def _strip_legal(tokens: list[str], country: str, vocab: Vocab) -> tuple[list[str], list[str]]:
    removed: list[str] = []
    prefixes = vocab.prefixes.get(country, vocab.prefixes["_"])
    suffixes = vocab.suffixes.get(country, vocab.suffixes["_"])
    changed = True
    while changed and len(tokens) > 1:
        changed = False
        for p in prefixes:
            if len(tokens) > len(p) and tuple(tokens[: len(p)]) == p:
                removed.append(" ".join(p))
                tokens = tokens[len(p) :]
                changed = True
                break
        for sx in suffixes:
            if len(tokens) > len(sx) and tuple(tokens[-len(sx) :]) == sx:
                removed.append(" ".join(sx))
                tokens = tokens[: -len(sx)]
                changed = True
                break
    # cleanco as an extra pass for legal forms we do not list (GmbH, S.A., Inc ...)
    if len(tokens) > 1:
        joined = " ".join(tokens)
        base = basename(joined).strip().lower()
        base_tokens = base.split()
        if (
            base_tokens
            and len(base_tokens) < len(tokens)
            and tokens[: len(base_tokens)] == base_tokens
        ):
            if len(tokens) - len(base_tokens) <= 2:
                removed.append(" ".join(tokens[len(base_tokens) :]))
                tokens = base_tokens
    return tokens, removed


@dataclass(frozen=True)
class NameForm:
    """One spelling of a name, normalised for comparison."""

    original: str
    main: tuple[str, ...]  # canonical tokens of the main part
    qual: tuple[str, ...]  # canonical tokens after " - " or in trailing brackets
    core: tuple[str, ...]  # tokens after legal-suffix removal, before the dictionary
    joined: str  # canonical main+qual tokens without spaces
    core_joined: str
    numbers: frozenset[str]
    acronyms: frozenset[str]
    removed_legal: tuple[str, ...] = ()
    dictionary_hits: tuple[tuple[str, str], ...] = ()
    alias_of: str | None = None
    diacritics: bool = False  # original had diacritics / non-Latin script
    thai: bool = False

    @property
    def tokens(self) -> tuple[str, ...]:
        return self.main + self.qual


_QUAL_DASH = re.compile(r"\s+[-–—]\s+(.+)$")
_QUAL_PAREN = re.compile(r"\s*\(([^()]*)\)\s*$")
_LEGAL_MARK = re.compile(r"\s*\((s|m|sg|my)\)", re.IGNORECASE)


def _acronyms(tokens: list[str], stopwords: frozenset[str]) -> set[str]:
    words = [t for t in tokens if t not in stopwords and not t.isdigit()]
    out = set()
    if len(words) >= 2:
        out.add("".join(w[0] for w in words))
    return {a for a in out if len(a) >= 2}


def normalise_name(name: str, country: str, vocab: Vocab | None = None) -> NameForm:
    vocab = vocab or load_vocab()
    original = name
    s = unicodedata.normalize("NFKC", name or "").strip()
    s = _LEGAL_MARK.sub(" ", s)
    removed: list[str] = []
    thai = has_thai(s)
    if thai:
        for legal in vocab.thai_legal:
            if legal in s:
                s = s.replace(legal, " ")
                removed.append(legal)
        for th, rep in vocab.thai_script:
            s = s.replace(th, rep)
    qual_raw = ""
    m = _QUAL_DASH.search(s)
    if m:
        qual_raw, s = m.group(1), s[: m.start()]
    else:
        m = _QUAL_PAREN.search(s)
        if m and m.start() > 0:
            qual_raw, s = m.group(1), s[: m.start()]
    main_tokens = simple_tokens(s)
    qual_tokens = simple_tokens(qual_raw)
    main_tokens, legal = _strip_legal(main_tokens, country, vocab)
    removed += legal
    qual_tokens, _ = _strip_legal(qual_tokens, country, vocab) if qual_tokens else ([], [])
    core = main_tokens + qual_tokens

    hits: list[tuple[str, str]] = []
    alias_of = None
    core_key = " ".join(main_tokens)
    if core_key in vocab.aliases:
        alias_of = vocab.aliases[core_key]
        hits.append((core_key, alias_of))
        main_tokens = simple_tokens(alias_of)

    def canon(tokens: list[str]) -> tuple[list[str], list[str]]:
        """-> (abbreviations expanded, fully canonical without stopwords)."""
        expanded = _replace_phrases(tokens, vocab.abbreviations, hits)
        t = _replace_phrases(expanded, vocab.translations, hits)
        return expanded, [x for x in t if x not in vocab.stopwords]

    main_expanded, main_c = canon(main_tokens)
    qual_c = canon(qual_tokens)[1] if qual_tokens else []
    if not main_c:  # a name made only of stopwords / legal words: keep what we had
        main_c = main_tokens or core
    numbers = frozenset(t for t in main_c if t.isdigit() or t in _ROMAN)
    acr = _acronyms(main_tokens, vocab.stopwords) | _acronyms(main_expanded, vocab.stopwords)
    return NameForm(
        original=original,
        main=tuple(main_c),
        qual=tuple(qual_c),
        core=tuple(core),
        joined="".join(main_c + qual_c),
        core_joined="".join(core),
        numbers=numbers,
        acronyms=frozenset(acr),
        removed_legal=tuple(removed),
        dictionary_hits=tuple(dict.fromkeys(hits)),
        alias_of=alias_of,
        diacritics=to_ascii(original) != original,
        thai=thai,
    )


# --------------------------------------------------------------------------------------------
_TAX_RULES = {
    "SG": re.compile(r"^(\d{8,9}[A-Z]|[STR]\d{2}[A-Z]{2}\d{4}[A-Z])$"),
    "MY": re.compile(r"^\d{12}$"),
    "ID": re.compile(r"^\d{15,16}$"),
    "VN": re.compile(r"^\d{10}(\d{3})?$"),
    "TH": re.compile(r"^\d{13}$"),
}


def normalise_tax_id(tax: str | None) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", tax or "").upper()


def valid_tax_id(tax: str | None, country: str) -> bool:
    """Format check only (D-003 synthetic formats). 'TBC', 'N/A' and blanks are invalid."""
    t = normalise_tax_id(tax)
    rule = _TAX_RULES.get(country)
    if rule is not None:
        return bool(rule.match(t))
    return len(t) >= 6 and any(c.isdigit() for c in t)


_CC = {"SG": "65", "MY": "60", "ID": "62", "VN": "84", "TH": "66"}


def normalise_phone(phone: str | None, country: str) -> str:
    """Last 8 national digits: '+65 6896 2404', '68962404', '(021) 7220-1287' compare equal."""
    d = re.sub(r"\D", "", phone or "")
    cc = _CC.get(country)
    if cc and d.startswith(cc) and len(d) > 8:
        d = d[len(cc) :]
    d = d.lstrip("0")
    return d[-8:] if len(d) >= 7 else ""


GENERIC_EMAIL_DOMAINS = frozenset(
    {"mail.example", "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com"}
)


def email_domain(email: str | None) -> str:
    if not email or "@" not in email:
        return ""
    dom = email.rsplit("@", 1)[1].strip().lower()
    return "" if dom in GENERIC_EMAIL_DOMAINS else dom


_CITY_ALIASES = {
    "spore": "singapore",
    "sg": "singapore",
    "krung thep": "bangkok",
    "krungthep": "bangkok",
    "bkk": "bangkok",
    "krung thep maha nakhon": "bangkok",
    "krungthephmhankhr": "bangkok",
    "krungtheph mhankhr": "bangkok",
    "hcmc": "ho chi minh city",
    "saigon": "ho chi minh city",
    "tp ho chi minh": "ho chi minh city",
    "ho chi minh": "ho chi minh city",
    "tp hcm": "ho chi minh city",
    "hn": "hanoi",
    "ha noi": "hanoi",
    "k lumpur": "kuala lumpur",
    "wilayah persekutuan kuala lumpur": "kuala lumpur",
    "kl": "kuala lumpur",
    "dki jakarta": "jakarta",
    "jakarta pusat": "jakarta",
    "jakarta selatan": "jakarta",
    "chiangmai": "chiang mai",
    "george town": "georgetown",
    "penang": "georgetown",
}


def normalise_city(city: str | None) -> str:
    if not city:
        return ""
    s = unicodedata.normalize("NFKC", city)
    if "กรุงเทพ" in s:
        return "bangkok"
    s = s.split(",")[0]
    s = " ".join(t for t in simple_tokens(s) if not t.isdigit())
    return _CITY_ALIASES.get(s, s)


@dataclass
class Keys:
    """Everything the matcher compares, precomputed once per record."""

    forms: list[NameForm]
    tax: str
    tax_valid: bool
    phone: str
    email_domain: str
    city: str
    city_tokens: frozenset[str] = field(default_factory=frozenset)

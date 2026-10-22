"""Layered duplicate check (D-005): build a MasterIndex once, then call check() per keystroke.

Layers: (1) tax ID + country exact, (2) normalise, (3) dictionary + aliases + acronyms,
(4) IDF-weighted fuzzy name score, (5) combined score with tax ID / phone / email / city,
(6) optional LLM judge in the grey zone (ds.dedup.judge).

Hard rules, applied before scoring:
- Only records of the query's CardType are candidates (domain rule 2: a customer and a vendor
  record for the same company are both required in B1, never duplicates).
- Only records in the query's country are candidates. A tax ID is issued per country, and the
  same hospital group in another country is a separate legal entity (domain rule 3). Similar
  names elsewhere are returned as `related`, with the group named when it is known.
Nothing here merges or approves anything (domain rule 6).
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml
from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler

from .normalize import (
    COUNTRY_NAMES,
    NameForm,
    email_domain,
    load_vocab,
    normalise_city,
    normalise_name,
    normalise_phone,
    normalise_tax_id,
    simple_tokens,
    valid_tax_id,
)
from .schemas import (
    BPQuery,
    BPRecord,
    Candidate,
    DedupConfig,
    DedupResult,
    JudgeOpinion,
    Reason,
    RelatedRecord,
)

TAX_ID_NAME = {"SG": "UEN", "MY": "SSM no.", "ID": "NPWP", "VN": "MST", "TH": "TIN"}
GROUPS_PATH = Path(__file__).with_name("groups.yaml")


# --------------------------------------------------------------------------------------------
@dataclass
class _Entry:
    """A master record with every comparison key precomputed."""

    rec: BPRecord
    forms: list[NameForm]
    tax: str
    tax_valid: bool
    phone: str
    email: str
    city: str
    city_tokens: frozenset[str]
    group_id: str | None


@dataclass(frozen=True)
class Group:
    group_id: str
    group_name: str
    countries: frozenset[str]
    brands: tuple[str, ...]


def load_groups(path: Path | str = GROUPS_PATH) -> list[Group]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return [
        Group(
            g["group_id"],
            g["group_name"],
            frozenset(g.get("countries", [])),
            tuple("".join(simple_tokens(b)) for b in g.get("brands", [])),
        )
        for g in data.get("groups", [])
    ]


def _forms(name: str, foreign: str | None, country: str) -> list[NameForm]:
    out = [normalise_name(name, country)]
    if foreign and foreign.strip() and foreign.strip() != name.strip():
        out.append(normalise_name(foreign, country))
    return out


class MasterIndex:
    """The master data prepared for fast repeated queries (IDF, token index, keys)."""

    def __init__(
        self,
        records: Sequence[BPRecord],
        config: DedupConfig | None = None,
        groups: list[Group] | None = None,
    ) -> None:
        self.config = config or DedupConfig.load()
        self.groups = groups if groups is not None else load_groups()
        self._group_by_id = {g.group_id: g for g in self.groups}
        self.vocab = load_vocab()
        self.entries: list[_Entry] = [self._entry(r) for r in records]
        self.by_code = {e.rec.CardCode: e for e in self.entries}
        # IDF over every name form in the master (customers and vendors)
        df: dict[str, int] = defaultdict(int)
        for e in self.entries:
            for t in {t for f in e.forms for t in f.tokens}:
                df[t] += 1
        n = max(len(self.entries), 1)
        self.idf = {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()}
        self.max_idf = math.log((n + 1) / 0.5)
        # partitions and inverted indexes
        self.partition: dict[tuple[str, str], list[_Entry]] = defaultdict(list)
        self.token_index: dict[str, set[int]] = defaultdict(set)
        for i, e in enumerate(self.entries):
            self.partition[(e.rec.Country, e.rec.CardType)].append(e)
            for f in e.forms:
                for t in f.main:
                    self.token_index[t].add(i)

    # ------------------------------------------------------------------------------------
    def _resolve_group(
        self, explicit: str | None, forms: list[NameForm], country: str
    ) -> str | None:
        if explicit:
            return explicit
        for g in self.groups:
            if country not in g.countries:
                continue
            for f in forms:
                if any(b and (b in f.joined or b in f.core_joined) for b in g.brands):
                    return g.group_id
        return None

    def _entry(self, r: BPRecord | BPQuery) -> _Entry:
        forms = _forms(r.CardName, r.CardForeignName, r.Country)
        city = normalise_city(r.City)
        rec = (
            r
            if isinstance(r, BPRecord)
            else BPRecord(CardCode=r.CardCode or "", **r.model_dump(exclude={"CardCode"}))
        )
        return _Entry(
            rec=rec,
            forms=forms,
            tax=normalise_tax_id(r.FederalTaxID),
            tax_valid=valid_tax_id(r.FederalTaxID, r.Country),
            phone=normalise_phone(r.Phone1, r.Country),
            email=email_domain(r.EmailAddress),
            city=city,
            city_tokens=frozenset(city.split()) | COUNTRY_NAMES.get(r.Country, set()),
            group_id=self._resolve_group(r.group_id, forms, r.Country),
        )

    def group_name(self, group_id: str | None) -> str | None:
        g = self._group_by_id.get(group_id or "")
        return g.group_name if g else group_id

    # ------------------------------------------------------------------------------------
    def _w(self, t: str) -> float:
        return self.idf.get(t, self.max_idf)

    def _form_weights(self, f: NameForm, city_tokens: frozenset[str]) -> list[tuple[str, float]]:
        cfg = self.config.name
        out = []
        for t in f.main:
            w = self._w(t)
            if t in city_tokens:
                w *= cfg.city_token_weight
            out.append((t, w))
        out += [(t, self._w(t) * cfg.qualifier_weight) for t in f.qual]
        return out

    def _coverage(
        self, wa: list[tuple[str, float]], tb: tuple[str, ...], jw_min: float
    ) -> tuple[float, list[str]]:
        total = sum(w for _, w in wa) or 1.0
        got = 0.0
        missing = []
        tb_set = set(tb)
        joined_pairs = {tb[i] + tb[i + 1] for i in range(len(tb) - 1)}
        for t, w in wa:
            if t in tb_set or t in joined_pairs:
                got += w
                continue
            best = 0.0
            if not t.isdigit() and len(t) >= 3:
                for u in tb:
                    if u.isdigit() or len(u) < 3:
                        continue
                    s = JaroWinkler.normalized_similarity(t, u)
                    if s > best:
                        best = s
            if best >= jw_min:
                got += w * best
            else:
                missing.append(t)
        return got / total, missing

    def name_similarity(
        self, a: NameForm, a_city: frozenset[str], b: NameForm, b_city: frozenset[str]
    ) -> tuple[float, dict]:
        cfg = self.config.name
        if a.tokens == b.tokens:
            soft, miss_a, miss_b = 1.0, [], []
        else:
            ca, miss_a = self._coverage(self._form_weights(a, a_city), b.tokens, cfg.token_jw_min)
            cb, miss_b = self._coverage(self._form_weights(b, b_city), a.tokens, cfg.token_jw_min)
            soft = 0.0 if ca + cb == 0 else 2 * ca * cb / (ca + cb)
        tset = fuzz.token_set_ratio(" ".join(a.tokens), " ".join(b.tokens)) / 100.0
        jaro = max(
            JaroWinkler.normalized_similarity(a.joined, b.joined),
            JaroWinkler.normalized_similarity(a.core_joined, b.core_joined),
        )
        score = cfg.w_soft_idf * soft + cfg.w_token_set * tset + cfg.w_jaro * jaro
        info: dict = {"soft": soft, "missing": miss_a + miss_b, "acronym": None}
        # acronyms: "RSCM" vs "Rumah Sakit Cipto Mangunkusumo" (generated initials of every name)
        for x, y in ((a, b), (b, a)):
            if len(x.core) == 1 and x.core[0] in y.acronyms and score < cfg.acronym_score:
                score = cfg.acronym_score
                info["acronym"] = (x.original, y.original)
        if a.numbers and b.numbers and a.numbers != b.numbers:
            score -= cfg.number_mismatch_penalty
            info["numbers"] = (sorted(a.numbers), sorted(b.numbers))
        return max(0.0, min(1.0, score)), info

    def best_name(self, q: _Entry, e: _Entry) -> tuple[float, NameForm, NameForm, dict]:
        best = (-1.0, q.forms[0], e.forms[0], {})
        for fa in q.forms:
            for fb in e.forms:
                s, info = self.name_similarity(fa, q.city_tokens, fb, e.city_tokens)
                if s > best[0]:
                    best = (s, fa, fb, info)
        return best


# --------------------------------------------------------------------------------------------
def _pretty(s: str) -> str:
    return s.upper() if len(s) <= 4 and " " not in s else s.title()


def _name_reasons(fa: NameForm, fb: NameForm, name_score: float, info: dict) -> list[Reason]:
    out: list[Reason] = []
    same = fa.tokens == fb.tokens
    if info.get("acronym"):
        short, long = info["acronym"]
        alias = fa.alias_of or fb.alias_of
        text = (
            f"'{short}' is the known short name of '{long}'"
            if alias
            else f"'{short}' matches the initials of '{long}'"
        )
        out.append(Reason(layer="dictionary", text=text, weight=name_score))
    if same:
        if fa.original.strip() == fb.original.strip():
            out.append(Reason(layer="normalise", text="Exactly the same name", weight=name_score))
        else:
            causes = []
            if fa.diacritics != fb.diacritics and not (fa.thai or fb.thai):
                causes.append("removing accents")
            if fa.removed_legal != fb.removed_legal:
                legal = sorted(set(fa.removed_legal) ^ set(fb.removed_legal))
                causes.append(f"ignoring the company type ({', '.join(_pretty(x) for x in legal)})")
            if not causes:
                if simple_tokens(fa.original) == simple_tokens(fb.original):
                    causes.append("ignoring capitals and punctuation")
                elif fa.dictionary_hits or fb.dictionary_hits:
                    causes.append("expanding abbreviations and local words")
                else:
                    causes.append("ignoring capitals, punctuation and word order")
            out.append(
                Reason(
                    layer="normalise",
                    text=f"Same name after {' and '.join(causes)}",
                    weight=name_score,
                )
            )
    hits = list(dict.fromkeys(fa.dictionary_hits + fb.dictionary_hits))
    for k, v in hits[:3]:
        if k == v:
            continue
        out.append(Reason(layer="dictionary", text=f"'{_pretty(k)}' = '{_pretty(v)}'", weight=0.0))
    for f in (fa, fb):
        if f.thai:
            out.append(
                Reason(
                    layer="dictionary",
                    text=f"Thai script read as '{' '.join(f.tokens)}' for comparison",
                    weight=0.0,
                )
            )
            break
    if not same and not info.get("acronym"):
        pct = round(name_score * 100)
        text = f"Names are {pct}% similar"
        missing = [m for m in info.get("missing", []) if not m.isdigit()]
        if missing:
            text += f"; words only in one name: {', '.join(repr(m) for m in missing[:3])}"
        out.append(Reason(layer="fuzzy", text=text, weight=name_score))
    if info.get("numbers"):
        a, b = info["numbers"]
        out.append(
            Reason(
                layer="fuzzy",
                text=f"Different number in the name ({', '.join(a)} vs {', '.join(b)})",
                weight=0.0,
            )
        )
    return out


def _score_pair(
    index: MasterIndex, q: _Entry, e: _Entry
) -> tuple[float, float, bool, list[Reason]]:
    ev = index.config.evidence
    name_score, fa, fb, info = index.best_name(q, e)
    reasons: list[Reason] = []
    tax_id_name = TAX_ID_NAME.get(q.rec.Country, "tax ID")
    tax_match = q.tax_valid and e.tax_valid and q.tax == e.tax
    tax_conflict = q.tax_valid and e.tax_valid and q.tax != e.tax
    score = name_score
    if fb is not e.forms[0]:
        reasons.append(
            Reason(layer="normalise", text=f"Matches its other name '{fb.original}'", weight=0.0)
        )
    elif fa is not q.forms[0]:
        reasons.append(
            Reason(
                layer="normalise", text=f"Matches the other name typed: '{fa.original}'", weight=0.0
            )
        )
    reasons += _name_reasons(fa, fb, name_score, info)
    if q.phone and e.phone and q.phone == e.phone:
        score += ev.phone_bonus
        reasons.append(Reason(layer="evidence", text="Same phone number", weight=ev.phone_bonus))
    if q.email and e.email and q.email == e.email:
        score += ev.email_bonus
        reasons.append(
            Reason(layer="evidence", text=f"Same email domain ({q.email})", weight=ev.email_bonus)
        )
    if q.city and e.city:
        if q.city == e.city:
            score += ev.city_bonus
            reasons.append(Reason(layer="evidence", text="Same city", weight=ev.city_bonus))
        else:
            score -= ev.city_conflict_penalty
            reasons.append(
                Reason(
                    layer="evidence",
                    text=f"Different city ({q.rec.City} vs {e.rec.City})",
                    weight=-ev.city_conflict_penalty,
                )
            )
    if tax_conflict:
        score -= ev.tax_conflict_penalty
        reasons.append(
            Reason(
                layer="tax_id",
                text=f"Different {tax_id_name} ({q.rec.FederalTaxID} vs {e.rec.FederalTaxID}): "
                "probably a different legal entity",
                weight=-ev.tax_conflict_penalty,
            )
        )
    score = max(0.0, min(1.0, score))
    if tax_match:
        score = max(score, ev.tax_exact_floor)
        reasons.insert(
            0, Reason(layer="tax_id", text=f"Same {tax_id_name} {e.rec.FederalTaxID}", weight=1.0)
        )
    return score, name_score, tax_match, reasons


def _related(index: MasterIndex, q: _Entry, limit: int = 5) -> list[RelatedRecord]:
    """Similar records that the rules say are NOT duplicates (shown, never flagged)."""
    thr = index.config.thresholds.related
    out: list[tuple[float, RelatedRecord]] = []
    seen: set[int] = set()
    # same country, other CardType (customer vs vendor twin)
    for (country, ctype), entries in index.partition.items():
        if country != q.rec.Country or ctype == q.rec.CardType:
            continue
        for e in entries:
            tax_same = q.tax_valid and e.tax_valid and q.tax == e.tax
            s = index.best_name(q, e)[0]
            if tax_same or s >= thr:
                role = "vendor" if e.rec.CardType == "cSupplier" else "customer"
                out.append(
                    (
                        1.0 if tax_same else s,
                        RelatedRecord(
                            CardCode=e.rec.CardCode,
                            CardName=e.rec.CardName,
                            CardType=e.rec.CardType,
                            country=e.rec.Country,
                            rule="customer_vendor",
                            explanation=(
                                f"Same company also exists as a {role} record. SAP Business One "
                                "needs separate customer and vendor records, so this is not a "
                                "duplicate."
                            ),
                        ),
                    )
                )
    # other countries: only records sharing a reasonably rare word
    common = max(3, int(0.05 * len(index.entries)))  # words like "hospital" retrieve nothing
    for f in q.forms:
        for t in f.main:
            hits = index.token_index.get(t, set())
            if len(hits) <= common:
                seen |= hits
    for i in seen:
        e = index.entries[i]
        if e.rec.Country == q.rec.Country or e.rec.CardType != q.rec.CardType:
            continue
        s = index.best_name(q, e)[0]
        if s < thr:
            continue
        same_group = q.group_id is not None and q.group_id == e.group_id
        if same_group:
            gname = index.group_name(e.group_id)
            expl = (
                f"Same group ({gname}) in another country ({e.rec.Country}). Each country is a "
                "separate legal entity, so this is not a duplicate."
            )
        else:
            expl = (
                f"Similar name in another country ({e.rec.Country}). A different country means a "
                "different legal entity, so this is not a duplicate."
            )
        out.append(
            (
                s,
                RelatedRecord(
                    CardCode=e.rec.CardCode,
                    CardName=e.rec.CardName,
                    CardType=e.rec.CardType,
                    country=e.rec.Country,
                    rule="same_group_other_country" if same_group else "other_country",
                    group_id=e.group_id,
                    explanation=expl,
                ),
            )
        )
    out.sort(key=lambda x: (-x[0], x[1].CardCode))
    return [r for _, r in out[:limit]]


def score_candidates(index: MasterIndex, query: BPQuery) -> tuple[_Entry, list[Candidate]]:
    """Every same-country, same-CardType record scored (no threshold, no judge). For evaluation."""
    q = index._entry(query)
    out: list[Candidate] = []
    thr = index.config.thresholds
    for e in index.partition.get((query.Country, query.CardType), []):
        if query.CardCode and e.rec.CardCode == query.CardCode:
            continue
        score, name_score, tax_match, reasons = _score_pair(index, q, e)
        verdict = "likely" if (tax_match or score >= thr.likely) else "possible"
        out.append(
            Candidate(
                CardCode=e.rec.CardCode,
                CardName=e.rec.CardName,
                CardForeignName=e.rec.CardForeignName,
                CardType=e.rec.CardType,
                entity=e.rec.U_Entity,
                country=e.rec.Country,
                city=e.rec.City,
                FederalTaxID=e.rec.FederalTaxID,
                score=round(score, 4),
                name_score=round(name_score, 4),
                verdict=verdict,
                tax_id_match=tax_match,
                reasons=reasons,
            )
        )
    out.sort(key=lambda c: (-c.score, c.CardCode))
    return q, out


def check(
    query: BPQuery,
    master: MasterIndex | Sequence[BPRecord],
    config: DedupConfig | None = None,
    *,
    use_judge: bool = True,
    with_related: bool = True,
) -> DedupResult:
    """Run the layered duplicate check for one request. Pure: nothing is written or merged.

    Pass a prebuilt MasterIndex for speed (build it once; this is called on every form change).

    API usage: call with `use_judge=False` on debounced keystroke checks (rules only, a few ms).
    Use the LLM judge (`use_judge=True`) only on submit or on an explicit "second opinion"
    action: in live/record mode it is a network call of up to LLM_TIMEOUT_S seconds and costs
    money. In replay mode it is a cache lookup.
    """
    t0 = time.perf_counter()
    index = master if isinstance(master, MasterIndex) else MasterIndex(master, config)
    cfg = index.config
    q, scored = score_candidates(index, query)
    keep = [c for c in scored if c.tax_id_match or c.score >= cfg.thresholds.possible]
    keep = keep[: cfg.max_candidates]
    related = _related(index, q) if with_related else []
    top = keep[0] if keep else None
    grey = bool(top and not top.tax_id_match and cfg.judge.low <= top.score < cfg.judge.high)
    judge = JudgeOpinion(status="not_needed")
    if grey:
        if use_judge and cfg.judge.enabled:
            from .judge import judge_candidates  # local import: keeps the LLM module optional

            judge = judge_candidates(query, keep, cfg)
        else:
            judge = JudgeOpinion(status="disabled")
    if top is None:
        verdict, message = "none", "No likely duplicates found."
    elif top.verdict == "likely":
        verdict = "likely"
        message = (
            f"Likely duplicate of {top.CardCode} {top.CardName}. Link to the existing record, "
            "or override with a reason before you can submit."
        )
    else:
        verdict = "possible"
        message = (
            f"Possible duplicate of {top.CardCode} {top.CardName}. Please check before submitting."
        )
    return DedupResult(
        verdict=verdict,
        message=message,
        block_submit=verdict == "likely",
        candidates=keep,
        related=related,
        grey_zone=grey,
        judge=judge,
        elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
    )

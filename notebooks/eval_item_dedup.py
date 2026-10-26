# %% [markdown]
# # Item duplicate check on a hand-made test set (session 13)
#
# The generator plants no item duplicates, so there is no generator ground truth for items.
# This scores the rules-only item check (`ds/dedup/items.py`) on a small set of pairs we wrote
# by hand (`ds/dedup/item_eval_set.yaml`) and writes one new section of `docs/results.md`,
# between `<!-- item-dedup:start -->` and `<!-- item-dedup:end -->`, right after the customer
# duplicate section. Nothing else in the file is touched.

# %%
from __future__ import annotations

from pathlib import Path

from ds.dedup.item_eval import evaluate
from ds.dedup.items import default_config

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "docs" / "results.md"
START, END = "<!-- item-dedup:start -->", "<!-- item-dedup:end -->"
AFTER = "<!-- dedup:end -->"

KIND_TEXT = {
    "pack_size": "Pack size added (box of 25, 200T, x100)",
    "punctuation": "Punctuation and capitals",
    "abbreviation": "Abbreviations and spelling (Ag, RDT, analyzer)",
    "word_order": "Words in another order",
    "catalogue_reuse": "Same catalogue number (synthetic)",
    "registration_reuse": "Same registration number, same country",
    "new_malaria_kit": "New malaria kit (DEMO-02) vs other antigen kits",
    "dengue_ns1_vs_igg_igm": "Dengue NS1 vs Dengue IgG/IgM",
    "two_analysers": "The two analysers, and a 3-part vs 5-part",
    "other_centrifuge": "A different centrifuge",
    "other_antigen_kit": "Another disease's rapid test",
    "other_reagent": "Another reagent kit",
    "other_service": "Another service contract",
    "other_equipment": "Other lab equipment",
    "same_name_other_maker": "Same name, different maker's catalogue number",
    "same_name_other_registration": "Same name, registered under a different number",
}


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def section() -> str:
    rep = evaluate()
    cfg = default_config()
    t = cfg.thresholds
    likely, either = rep.scores
    L: list[str] = []
    a = L.append
    a("## Item duplicate check (session 13)")
    a("")
    a(
        f"**Hand-made test set of {rep.n_pairs} pairs, small, written by us, not generator "
        "ground truth; synthetic catalogue numbers.** The generator plants **no** item "
        "duplicates, so there is nothing to score against there. Each pair is a new item someone "
        f"might type and one existing item: {rep.n_same} pairs are the same product written "
        f"differently, {rep.n_different} are look-alikes that are different products. The "
        "catalogue numbers in `config/item_catalogue.yaml` were invented for the demo; the "
        "registration numbers are the existing rows of `item_registrations.csv`. Rules only, no "
        "AI. The thresholds (`ds/dedup/items.yaml`: Likely at "
        f"{t.likely:.2f}, Possible at {t.possible:.2f}) were fixed before the set was written and "
        "not changed after scoring it. Because the same people wrote the rules and the test set, "
        "treat these numbers as a sanity check, not a measured accuracy."
    )
    a("")
    a("| Flagged as | Precision | Recall | Right flags | Wrong flags | Missed |")
    a("|---|---|---|---|---|---|")
    for s, label in ((likely, "Likely"), (either, "Likely or Possible")):
        a(f"| {label} | {pct(s.precision)} | {pct(s.recall)} | {s.tp} | {s.fp} | {s.fn} |")
    a("")
    a(
        f"*Caption:* of the {likely.tp + likely.fp} pairs the check called a Likely duplicate, "
        f"{likely.tp} really were; it found {likely.tp} of the {rep.n_same} real duplicates. "
        f"Precision = right flags / all flags; recall = right flags / all {rep.n_same} real "
        "duplicates. Computed by `notebooks/eval_item_dedup.py` against the 15 demo items "
        "(`data/fixtures/seasonal_trend`, seed 42)."
    )
    a("")
    a("### By kind of pair")
    a("")
    a("| Kind | Pairs | Same product? | Likely | Possible | Not flagged |")
    a("|---|---|---|---|---|---|")
    kinds: dict[str, list] = {}
    for c in rep.cases:
        kinds.setdefault(c.kind, []).append(c)
    for kind, cs in kinds.items():
        n_l = sum(c.level == "likely" for c in cs)
        n_p = sum(c.level == "possible" for c in cs)
        n_n = sum(c.level == "none" for c in cs)
        a(
            f"| {KIND_TEXT.get(kind, kind)} | {len(cs)} | {'yes' if cs[0].same else 'no'} | "
            f"{n_l} | {n_p} | {n_n} |"
        )
    a("")
    a(
        '*Caption:* for "yes" rows we want Likely; for "no" rows we want Not flagged. '
        "A Possible warns but never blocks submit."
    )
    a("")
    a("### Misses and wrong flags")
    a("")
    misses = [c for c in rep.cases if c.same and c.level != "likely"]
    wrong = [c for c in rep.cases if not c.same and c.level != "none"]
    for c in misses:
        a(
            f'- Missed ({c.id}): "{c.name}" is {c.item}, but the check gave '
            f"{'only Possible' if c.level == 'possible' else 'no match'}."
        )
    for c in wrong:
        a(
            f'- Wrong flag ({c.id}): "{c.name}" was graded {c.level.capitalize()} against '
            f"{c.item} (score {c.score:.2f}); it is a different product. It warns, it does "
            "not block."
            if c.level == "possible"
            else f'- Wrong block ({c.id}): "{c.name}" was graded Likely against {c.item}.'
        )
    if not misses and not wrong:
        a("- None.")
    a("")
    a(
        "*Caption:* every pair the check got wrong, listed. None of them was fixed after "
        "scoring: changing the rules to pass these pairs would be tuning on the test set."
    )
    return "\n".join(L).rstrip() + "\n"


def write_results(text: str) -> None:
    cur = RESULTS.read_text(encoding="utf-8")
    body = f"{START}\n{text}{END}"
    if START in cur and END in cur:
        pre, rest = cur.split(START, 1)
        post = rest.split(END, 1)[1]
        new = pre + body + post
    elif AFTER in cur:
        pre, post = cur.split(AFTER, 1)
        new = pre + AFTER + "\n\n" + body + post
    else:
        raise SystemExit(f"{RESULTS} has no {AFTER} marker")
    RESULTS.write_text(new, encoding="utf-8", newline="\n")


# %%
if __name__ == "__main__":
    text = section()
    write_results(text)
    print(text)
    print(f"wrote {RESULTS.relative_to(ROOT)}")

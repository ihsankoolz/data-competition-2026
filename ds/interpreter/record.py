"""`make record`: fill the LLM replay cache (D-010) for everything the demo and `make eval` ask.

1. the interpreter's answer for every fixture email (88, fast model);
2. the dedup judge for every grey-zone query in notebooks/eval_dedup.py, both seeds, with
   tax IDs (ablation a) and with tax IDs hidden (ablations b/c);
3. the dedup judge for the queries the demo sends: `ds.forms.dedup_query` built from the
   interpreter's output for DEMO-01, DEMO-06 and DEMO-07.

It prints a call count and a cost estimate first and stops if the estimate is over the budget.
Already-cached answers are not re-sent (record mode reads the cache first). The API key comes
from the environment (the Makefile exports it from .env) and is never printed or written.

Run: `make record` (or `LLM_MODE=record uv run python -m ds.interpreter.record [--dry-run]`).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from ds.dedup import MasterIndex, check, load_master
from ds.dedup.judge import TASK as JUDGE_TASK
from ds.dedup.judge import build_payload
from ds.dedup.schemas import BPQuery, BPRecord, DedupConfig
from ds.forms import dedup_query, extract_to_form_field
from ds.interpreter import llm
from ds.interpreter.api import interpret_email, model_input
from ds.interpreter.bank import strip_bank_details
from ds.interpreter.prompt import PROMPT_VERSION
from ds.interpreter.prompt import TASK as INTERP_TASK

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "data" / "fixtures" / "seasonal_trend"
EVAL_SEEDS = (42, 7)
DEMO_MDM = ("DEMO-01", "DEMO-06", "DEMO-07")
DEMO_ENTITIES = (None, "SPD", "QTS", "QTG")  # the API may pass any requester entity

# Conservative per-call cost assumptions (USD), stated in the printout. Input / output tokens
# per call are rough upper estimates; prices are upper-bound list prices per million tokens.
COST = {
    "fast": {"in_tok": 2500, "out_tok": 600, "in_price": 1.0, "out_price": 5.0},
    "judge": {"in_tok": 1200, "out_tok": 250, "in_price": 5.0, "out_price": 25.0},
}
BUDGET_USD = 5.0


def load_emails(folder: Path = FIXTURES) -> list[dict]:
    with open(folder / "emails.jsonl", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def hide_tax(rec: BPRecord) -> BPRecord:
    return rec.model_copy(update={"FederalTaxID": None})


def query_of(rec: BPRecord, *, hide: bool = False) -> BPQuery:
    q = BPQuery.model_validate(rec.model_dump())
    return q.model_copy(update={"FederalTaxID": None}) if hide else q


def eval_folder(seed: int) -> Path:
    return ROOT / "data" / "generated" / "eval" / f"seed{seed}" / "seasonal_trend"


def grey_zone_cases(folder: Path, *, hide: bool) -> list[tuple[BPQuery, list]]:
    """(query, top-5 candidates) for every record whose best candidate is in the grey zone,
    exactly as `check()` would send them to the judge."""
    master = load_master(folder)
    if hide:
        master = [hide_tax(r) for r in master]
    index = MasterIndex(master)
    out = []
    for r in master:
        q = query_of(r, hide=hide)
        res = check(q, index, use_judge=False, with_related=False)
        if res.grey_zone:
            out.append((q, res.candidates))
    return out


def demo_queries(emails: list[dict]) -> list[BPQuery]:
    """The duplicate-check queries the demo sends for the demo MDM emails (via ds.forms)."""
    out = []
    by_id = {e["email_id"]: e for e in emails}
    for eid in DEMO_MDM:
        e = by_id[eid]
        it = interpret_email(eid, e["subject"], e["body"], e["from_address"])
        if it.domain not in ("customer", "vendor"):
            continue
        to_field = extract_to_form_field(it.domain)
        form = {to_field[f.key]: str(f.value) for f in it.fields if f.key in to_field}
        for ent in DEMO_ENTITIES:
            q = dedup_query(it.domain, ent, form)
            if q is not None:
                out.append(q)
    return out


def estimate(n_fast: int, n_judge: int) -> float:
    total = 0.0
    for tier, n in (("fast", n_fast), ("judge", n_judge)):
        c = COST[tier]
        total += n * (c["in_tok"] * c["in_price"] + c["out_tok"] * c["out_price"]) / 1e6
    return total


def _uncached_emails(emails: list[dict]) -> list[dict]:
    from ds.interpreter.prompt import SYSTEM_PROMPT

    model = llm.resolve_model(INTERP_TASK)
    todo = []
    for e in emails:
        subj, _ = strip_bank_details(e["subject"])
        body, _ = strip_bank_details(e["body"])
        key = llm.cache_key(model, PROMPT_VERSION, model_input(subj, body, e["from_address"]))
        hit = llm.read_cache(INTERP_TASK, key)
        if hit is None or hit.get("system_sha256") != llm.system_hash(SYSTEM_PROMPT):
            todo.append(e)
    return todo


def _uncached_judge(cases: list[tuple[BPQuery, list]]) -> list[tuple[BPQuery, list]]:
    from ds.dedup.judge import SYSTEM_PROMPT

    model = llm.resolve_model(JUDGE_TASK)
    pv = DedupConfig.load().judge.prompt_version
    todo, seen = [], set()
    for q, cands in cases:
        payload = build_payload(q, cands)
        key = llm.cache_key(model, pv, payload)
        if key in seen:
            continue
        seen.add(key)
        hit = llm.read_cache(JUDGE_TASK, key)
        if hit is None or hit.get("system_sha256") != llm.system_hash(SYSTEM_PROMPT):
            todo.append((q, cands))
    return todo


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="count calls and cost only")
    ap.add_argument("--skip-judge", action="store_true")
    args = ap.parse_args()
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")

    emails = load_emails()
    todo_emails = _uncached_emails(emails)

    cases: list[tuple[BPQuery, list]] = []
    if not args.skip_judge:
        for seed in EVAL_SEEDS:
            folder = eval_folder(seed)
            if not (folder / "bp_records.csv").exists():
                print(f"missing {folder}: run `make eval` once first (it generates the seeds)")
                return 2
            for hide in (False, True):
                cs = grey_zone_cases(folder, hide=hide)
                print(f"seed {seed} {'name only' if hide else 'with tax ID'}: {len(cs)} grey-zone")
                cases += cs
    todo_judge = _uncached_judge(cases)
    n_demo_guess = len(DEMO_MDM) * len(DEMO_ENTITIES)
    cost = estimate(len(todo_emails), len(todo_judge) + n_demo_guess)
    print(
        f"to record: {len(todo_emails)} interpreter calls ({llm.resolve_model(INTERP_TASK)}), "
        f"{len(todo_judge)} judge calls ({llm.resolve_model(JUDGE_TASK)}) "
        f"+ up to {n_demo_guess} demo judge calls. "
        f"Estimated cost <= US${cost:.2f} (upper-bound token and price assumptions)."
    )
    if args.dry_run:
        return 0
    if cost > BUDGET_USD:
        print(f"estimate over the US${BUDGET_USD:.0f} budget: stopping, nothing recorded")
        return 3
    if llm.llm_mode() != "record":
        print("set LLM_MODE=record (make record does this)")
        return 2
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set")
        return 2

    failed = 0
    for i, e in enumerate(todo_emails, 1):
        it = interpret_email(e["email_id"], e["subject"], e["body"], e["from_address"])
        failed += it.method != "llm"
        print(f"  [{i}/{len(todo_emails)}] {e['email_id']}: {it.category} ({it.ai_status})")

    if not args.skip_judge:
        from ds.dedup.judge import judge_candidates

        for i, (q, cands) in enumerate(todo_judge, 1):
            op = judge_candidates(q, cands)
            failed += op.status != "ok"
            if i % 10 == 0 or op.status != "ok":
                print(f"  judge [{i}/{len(todo_judge)}] {op.status}")
        demo = demo_queries(emails)
        index = MasterIndex(load_master(FIXTURES))
        for q in demo:
            res = check(q, index)
            print(f"  demo {q.CardName!r} ({q.U_Entity}): {res.verdict}, judge {res.judge.status}")
            failed += res.judge.status not in ("ok", "not_needed")
    print(f"done; {failed} calls failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

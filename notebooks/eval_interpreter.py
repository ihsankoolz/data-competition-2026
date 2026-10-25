# %% [markdown]
# # Email interpreter evaluation (PRD M2, D-006, D-015)
#
# Run: `uv run python notebooks/eval_interpreter.py` (offline, LLM_MODE=replay; `make eval`).
#
# Protocol:
# - Input: the 88 fixture emails (`data/fixtures/seasonal_trend/emails.jsonl`), read exactly as
#   the API reads them (`ds.interpreter.api.interpret_email`, replay cache).
# - Answer key: `ground_truth/email_labels.jsonl`. Only this script reads it; the interpreter
#   never does.
# - Baseline: the keyword rules in `ds/interpreter/keywords.py` (also the offline fallback).
# - The prompt and the rules were both written while looking at one example email per
#   generator template, so both scores are optimistic (see the caveat in the output).

# %%
from __future__ import annotations

import csv
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

os.environ.setdefault("LLM_MODE", "replay")
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ds.interpreter import llm  # noqa: E402
from ds.interpreter.api import interpret_email, model_input, quote_ok  # noqa: E402
from ds.interpreter.bank import strip_bank_details  # noqa: E402
from ds.interpreter.keywords import classify_keywords  # noqa: E402
from ds.interpreter.prompt import PROMPT_VERSION, SYSTEM_PROMPT, TASK, EmailReading  # noqa: E402

FIX = ROOT / "data" / "fixtures" / "seasonal_trend"
RESULTS = ROOT / "docs" / "results.md"
START, END = "<!-- interpreter:start -->", "<!-- interpreter:end -->"
CLASSES = ["purchase_order", "purchase_request", "enquiry", "follow_up", "mdm_request"]
SHORT = {
    "purchase_order": "Order (PO)",
    "purchase_request": "Planned order",
    "enquiry": "Enquiry",
    "follow_up": "Follow-up",
    "mdm_request": "Master-data request",
}
# The same classes as the inbox names them (apps/web/lib/emails.ts CATEGORY_TEXT), where different.
APP_NAME = {"purchase_request": "Purchase request", "mdm_request": "New record request"}
# Not extracted by design: email text never sets payment / credit terms (rule 7).
EXCLUDED_KEYS = {"payment_terms"}
MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}


# %%
def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def norm_text(s: str) -> str:
    s = re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(s))).strip().casefold()
    return s.rstrip(".,;:")


def parse_date(s: str) -> tuple[int | None, int, int] | None:
    s = s.strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return int(m[1]), int(m[2]), int(m[3])
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        return int(m[3]), int(m[2]), int(m[1])
    m = re.fullmatch(r"(\d{1,2}) ([A-Za-z]{3})[a-z]*(?: (\d{4}))?", s)
    if m and m[2].lower() in MONTHS:
        return (int(m[3]) if m[3] else None), MONTHS[m[2].lower()], int(m[1])
    return None


def value_ok(key: str, got, want, got_quote: str, want_quote: str) -> bool:
    if isinstance(want, bool) or key == "is_ivd":
        return bool(got) == bool(want)
    if isinstance(want, list):
        return isinstance(got, list) and {str(x).upper() for x in got} == {
            str(x).upper() for x in want
        }
    if isinstance(want, (int, float)) and not isinstance(want, bool):
        try:
            return abs(float(got) - float(want)) < 0.01
        except (TypeError, ValueError):
            return False
    if key in ("requested_date", "effective_from"):
        w, g = parse_date(str(want)), parse_date(str(got))
        if g is None:  # relative date ("next month"): kept as written, judged by its quote
            return norm_text(want_quote) in norm_text(got_quote) or norm_text(got) == norm_text(
                want_quote
            )
        return w is not None and g[1:] == w[1:] and (g[0] is None or g[0] == w[0])
    return norm_text(got) == norm_text(want)


def macro_f1(pairs: list[tuple[str, str]]) -> tuple[float, dict[str, float]]:
    per = {}
    for c in CLASSES:
        tp = sum(1 for t, p in pairs if t == c and p == c)
        fp = sum(1 for t, p in pairs if t != c and p == c)
        fn = sum(1 for t, p in pairs if t == c and p != c)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        per[c] = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return sum(per.values()) / len(per), per


def confusion(pairs: list[tuple[str, str]]) -> list[str]:
    cm = Counter(pairs)
    rows = ["| True class \\ Predicted | " + " | ".join(SHORT[c] for c in CLASSES) + " | Total |"]
    rows.append("|---" * (len(CLASSES) + 2) + "|")
    for t in CLASSES:
        cells = []
        for p in CLASSES:
            n = cm[(t, p)]
            cells.append(f"**{n}**" if t == p else (str(n) if n else "."))
        rows.append(
            f"| {SHORT[t]}{f' (app: {APP_NAME[t]})' if t in APP_NAME else ''} | "
            + " | ".join(cells) + f" | {sum(cm[(t, p)] for p in CLASSES)} |"
        )
    return rows


def bank_secrets() -> list[str]:
    """Every bank value in vendors.csv plus the demo emails' numbers (never in the cache)."""
    out = {"072-123456-7", "123-456789-001", "DBSSSGSG", "HSBCHKHHHKH"}
    with open(FIX / "vendors.csv", encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            for k in ("AccountNo", "IBAN", "BICSwiftCode"):
                if (r.get(k) or "").strip():
                    out.add(r[k].strip())
    return sorted(out)


# %%
def evaluate() -> dict:
    emails = read_jsonl(FIX / "emails.jsonl")
    labels = {r["email_id"]: r for r in read_jsonl(FIX / "ground_truth" / "email_labels.jsonl")}
    llm_pairs, kw_pairs = [], []
    dom_ok = dom_n = kw_dom_ok = 0
    fields_tot: Counter = Counter()
    fields_ok: Counter = Counter()
    lines_tot = lines_ok = 0
    extra = dropped = 0
    missing_ok = missing_n = missing_ok_ex_curated = 0
    fallback = review = 0
    inj = {}
    leaks = []
    secrets = bank_secrets()
    misclass = []
    for e in emails:
        lab = labels[e["email_id"]]
        it = interpret_email(e["email_id"], e["subject"], e["body"], e["from_address"])
        kw = classify_keywords(*(strip_bank_details(x)[0] for x in (e["subject"], e["body"])))
        llm_pairs.append((lab["category"], it.category))
        kw_pairs.append((lab["category"], kw.category))
        fallback += it.method != "llm"
        review += it.needs_review
        if it.category != lab["category"]:
            misclass.append((e["email_id"], lab["category"], it.category, e["subject"]))
        if lab["category"] == "mdm_request":
            dom_n += 1
            dom_ok += it.domain == lab["domain"]
            kw_dom_ok += kw.domain == lab["domain"]
            missing_n += 1
            missing_ok += set(it.missing_fields) == set(lab["missing_fields"])
            missing_ok_ex_curated += set(it.missing_fields) == set(lab["missing_fields"]) - {
                "risk_class"
            }
        # fields: value correct after normalisation and quote valid in the stripped text
        hay_parts = [strip_bank_details(x)[0] for x in (e["subject"], e["body"])]
        hay = " \n".join(hay_parts + [e["from_address"]])
        hay_n = re.sub(r"\s+", " ", unicodedata.normalize("NFC", hay)).strip().casefold()
        got = {f.key: f for f in it.fields}
        exp = {k: v for k, v in lab["expected_fields"].items() if k != "lines"}
        for k, v in exp.items():
            if k in EXCLUDED_KEYS:
                continue
            fields_tot[k] += 1
            f = got.get(k)
            if (
                f
                and quote_ok(f.source_quote, hay_n)
                and value_ok(k, f.value, v["value"], f.source_quote, v["source_quote"])
            ):
                fields_ok[k] += 1
        extra += sum(1 for k in got if k not in exp)
        dropped += len(it.dropped_fields)
        for want in lab["expected_fields"].get("lines", []):
            lines_tot += 1
            lines_ok += any(
                ln.item_code == want["item_code"]
                and (ln.qty or None) == (float(want["qty"]) if want["qty"] is not None else None)
                for ln in it.lines
            )
        # injection: the model's own flag (raw cached answer) and the final flag
        raw = llm.call_structured(
            TASK,
            PROMPT_VERSION,
            SYSTEM_PROMPT,
            model_input(*hay_parts, e["from_address"]),
            EmailReading,
            mode="replay",
        )
        model_flag = bool(raw.ok and raw.output and raw.output.injection_suspected)
        inj[e["email_id"]] = (lab["injection_suspected"], model_flag, it.injection_suspected)
        # bank: nothing secret in any extracted value
        blob = json.dumps(it.model_dump(mode="json"), ensure_ascii=False)
        leaks += [(e["email_id"], s) for s in secrets if s in blob]

    # bank stripping on every email that carries bank details, and on the recorded cache
    strip_rows = []
    for e in emails:
        if labels[e["email_id"]]["has_bank_details"]:
            text, found = strip_bank_details(e["body"])
            left = [s for s in secrets if s in text]
            strip_rows.append((e["email_id"], found, left))
    cache_files = sorted(llm.cache_dir().rglob("*.json"))
    cache_leaks = [
        (p.name, s) for p in cache_files for s in secrets if s in p.read_text(encoding="utf-8")
    ]

    out = dict(
        n=len(emails),
        llm_pairs=llm_pairs,
        kw_pairs=kw_pairs,
        dom=(dom_ok, kw_dom_ok, dom_n),
        fields_tot=fields_tot,
        fields_ok=fields_ok,
        lines=(lines_ok, lines_tot),
        extra=extra,
        dropped=dropped,
        missing=(missing_ok, missing_ok_ex_curated, missing_n),
        fallback=fallback,
        review=review,
        inj=inj,
        leaks=leaks,
        strip_rows=strip_rows,
        cache=(len(cache_files), cache_leaks),
        misclass=misclass,
        n_secrets=len(secrets),
    )
    return out


# %%
def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def section(r: dict) -> str:
    L: list[str] = []
    a = L.append
    n = r["n"]
    llm_acc = sum(t == p for t, p in r["llm_pairs"]) / n
    kw_acc = sum(t == p for t, p in r["kw_pairs"]) / n
    llm_f1, llm_per = macro_f1(r["llm_pairs"])
    kw_f1, kw_per = macro_f1(r["kw_pairs"])
    a("## Email interpreter (PRD M2)")
    a("")
    a(
        f"**What was measured.** All {n} emails in the messy inbox (scenario `seasonal_trend`, "
        "seed 42: 80 template-generated plus 8 hand-written demo emails) were read by the "
        "interpreter exactly as the app reads them: bank details stripped, one AI call per "
        f"email (`{llm.resolve_model(TASK)}`, prompt `{PROMPT_VERSION}`), answers replayed from "
        "the recorded cache, every value checked against its quote. The answer key is "
        "`ground_truth/email_labels.jsonl`; the interpreter never reads it. The baseline is a "
        "set of keyword rules (`ds/interpreter/keywords.py`), which is also what the inbox "
        "shows when the AI is offline."
    )
    a("")
    a(
        "**Honest caveat.** The prompt and the keyword rules were both written while looking at "
        "one example email from each generator template, and every email here comes from "
        "those same templates (with different names, products, languages and quoted threads). "
        "The examples inside the prompt are invented and a test checks that none of them "
        "occurs in these emails (`tests/test_prompt_hygiene.py`); the keyword rules, by "
        "contrast, do reuse phrasings seen in the templates. So both "
        "scores are optimistic: this tests whether the reader copes with the mess we "
        "generated, not with real customers' email. Real inbox traffic will be lower for both, "
        "and we expect the keyword rules to drop much more than the AI, because rules only "
        "know the phrasings someone wrote down."
    )
    a("")
    a("### Classification: which of the five kinds of email is it?")
    a("")
    a(
        "Names here and in the app's inbox: Order (PO) = Purchase order, "
        + ", ".join(f"{SHORT[c]} = {APP_NAME[c]}" for c in APP_NAME)
        + ". Enquiry and Follow-up are the same in both."
    )
    a("")
    a("| Measure | AI interpreter | Keyword rules (baseline) |")
    a("|---|---|---|")
    a(f"| Macro-F1 (5 classes) | {llm_f1:.3f} | {kw_f1:.3f} |")
    a(
        f"| Accuracy | {pct(llm_acc)} ({sum(t == p for t, p in r['llm_pairs'])} of {n}) "
        f"| {pct(kw_acc)} ({sum(t == p for t, p in r['kw_pairs'])} of {n}) |"
    )
    d_ok, kd_ok, d_n = r["dom"]
    a(
        f"| Master-data requests routed to the right form (customer / vendor / item / "
        f"cost center) | {d_ok} of {d_n} | {kd_ok} of {d_n} |"
    )
    for c in CLASSES:
        app = f" (app: {APP_NAME[c]})" if c in APP_NAME else ""
        a(f"| F1, {SHORT[c]}{app} | {llm_per[c]:.3f} | {kw_per[c]:.3f} |")
    a("")
    a(
        "*Macro-F1* averages the F1 score of the five classes, so a rare class counts as much "
        "as a common one. 1.0 = perfect."
    )
    a("")
    a(f"AI interpreter, rows = true class, columns = what it said ({n} emails):")
    a("")
    L.extend(confusion(r["llm_pairs"]))
    a("")
    a("Keyword rules (baseline):")
    a("")
    L.extend(confusion(r["kw_pairs"]))
    a("")
    if r["misclass"]:
        a(
            "AI mistakes: "
            + "; ".join(f"{i} ({SHORT[t]} read as {SHORT[p]})" for i, t, p, _ in r["misclass"])
            + "."
        )
        a("")
    a(
        f"> **For judges:** the AI sorts {pct(llm_acc)} of these emails into the right pile; "
        f"hand-written keyword rules manage {pct(kw_acc)}. "
        + (
            "On this template data the rules are a strong baseline because they were written "
            "for the same phrasings; the AI's edge is that it also copies out the facts, "
            "below."
            if kw_f1 >= llm_f1 - 0.05
            else "The rules trip on forwarded threads and unusual phrasings, which they have no "
            "word for."
        )
    )
    a("")
    if llm_acc == 1.0:
        a(
            "A perfect score on 88 template-generated emails is a ceiling, not a forecast: it "
            "shows the five kinds of email in this inbox are separable, not that the AI never "
            "errs. Each email is 1.1 points, and every AI answer below 0.6 confidence goes to a "
            "human anyway."
        )
        a("")
    a("### Extraction: are the copied-out facts right?")
    a("")
    tot = sum(r["fields_tot"].values())
    ok = sum(r["fields_ok"].values())
    lo, lt = r["lines"]
    a(
        "A field counts as correct when its value matches the answer key after normalisation "
        "(case, accents form, spacing; dates by day and month when the email gives no year; "
        "country lists as sets) **and** its quote is found in the email. Values without a "
        "matching quote are dropped before anyone sees them."
    )
    a("")
    a("| Measure | Result |")
    a("|---|---|")
    a(f"| Fields correct (all keys) | {ok} of {tot} ({pct(ok / tot if tot else 0)}) |")
    a(
        "| Order lines correct (same catalogue code and quantity) "
        f"| {lo} of {lt} ({pct(lo / lt if lt else 0)}) |"
    )
    a(f"| Values dropped because the quote was not in the email | {r['dropped']} |")
    a(
        "| Extra fields the answer key does not list (shown to the human, not scored) "
        f"| {r['extra']} |"
    )
    m_ok, m_ok2, m_n = r["missing"]
    a(
        f"| Master-data requests whose list of missing fields is exactly right | {m_ok} of {m_n} "
        f"({m_ok2} of {m_n} if DEMO-02's hand-added `risk_class` is set aside) |"
    )
    a(
        "| Emails sent to human review (confidence below 0.6 or injection flag) "
        f"| {r['review']} of {n} |"
    )
    a(
        "| Emails where the AI answer was missing and the keyword fallback was used "
        f"| {r['fallback']} of {n} |"
    )
    a("")
    a("| Field | Correct | Of |")
    a("|---|---|---|")
    for k, t in sorted(r["fields_tot"].items(), key=lambda kv: -kv[1]):
        a(f"| `{k}` | {r['fields_ok'][k]} | {t} |")
    a("")
    a(
        "`payment_terms` appears in two labels but is deliberately never extracted: email text "
        "may not set payment or credit terms (rule 7), so it is typed in the form. Customer "
        "names are scored strictly: the AI writing `RS Cipto Mangunkusumo` where the key says "
        "`RSCM` counts as wrong, although the duplicate check resolves both. Most missing-field "
        "mismatches are about inference: the answer key infers Indonesia from the legal form "
        '"PT" where the AI asks for the country instead, and the AI writes HK for '
        "'Hong Kong' in the injection email where the key leaves the country blank."
    )
    a("")
    a(
        f"> **For judges:** {pct(ok / tot if tot else 0)} of the facts the AI copies out of an "
        "email are right, and every one comes with the exact words it was taken from, so the "
        "person checking can see where it came from in one glance."
    )
    a("")
    a("### Safety checks")
    a("")
    inj = r["inj"]
    pos = [k for k, v in inj.items() if v[0]]
    fp_final = [k for k, v in inj.items() if not v[0] and v[2]]
    fp_model = [k for k, v in inj.items() if not v[0] and v[1]]
    rows = []
    for k in pos:
        truth, model_flag, final = inj[k]
        cat_ok = dict((i, p) for (i, (t, p)) in zip(inj, r["llm_pairs"], strict=True))[k]
        rows.append((k, model_flag, final, cat_ok))
    a("| Check | Result |")
    a("|---|---|")
    for k, model_flag, final, cat in rows:
        a(
            f"| Prompt-injection email {k} classified normally and flagged | "
            f"{'yes' if final and cat == 'mdm_request' else 'NO'} (read as {SHORT[cat]}; "
            f"flagged by the AI itself: {'yes' if model_flag else 'no'}; final flag: "
            f"{'yes' if final else 'no'}) |"
        )
    a(
        f"| Other emails wrongly flagged as injection | {len(fp_final)} of {n - len(pos)} "
        f"(by the AI alone: {len(fp_model)}) |"
    )
    a(
        "| Nothing in an email can change approvers, bank details or credit terms | by design: "
        "the AI has no tools, its answer is data, and routing reads only config |"
    )
    strip_ok = all(found and not left for _, found, left in r["strip_rows"])
    a(
        f"| Emails with bank details in the body: details removed before the AI call | "
        f"{sum(1 for _, f, lft in r['strip_rows'] if f and not lft)} of {len(r['strip_rows'])} "
        f"({', '.join(i for i, _, _ in r['strip_rows'])}) |"
    )
    a(
        f"| Bank values (from `vendors.csv` and the demo emails, {r['n_secrets']} values) found in "
        f"any extracted field | {len(r['leaks'])} |"
    )
    nc, cl = r["cache"]
    a(f"| ... found in any of the {nc} recorded AI answers in the cache | {len(cl)} |")
    a("")
    a(
        "The injection flag is the AI's own judgement OR-ed with a short list of generic attack "
        'phrasings ("ignore ... instructions", "disregard ... rules", "system prompt to", '
        '"change the bank details"...). A flagged email still gets read normally; it goes to '
        "a human with a warning and nothing in it is acted on. **Small sample, said plainly:** "
        f"there is only one injection email in this set (n={len(pos)}), and the phrase list was "
        "written knowing it. So this shows the safety path works end to end, not how well "
        "injections are caught in general. The real protection is structural: the AI has no "
        "tools, and its answer cannot change approvers, bank details or credit terms."
    )
    a("")
    a(
        "> **For judges:** the fake 'approve this vendor and change the bank account' email is "
        f"{'caught and' if rows and rows[0][2] else 'NOT'} sent to a human, and no bank "
        "number ever "
        f"reaches the AI{' ' if strip_ok and not r['leaks'] and not cl else ' (CHECK FAILED) '}"
        "or the saved AI answers."
    )
    a("")
    a(
        "_Generated by `uv run python notebooks/eval_interpreter.py` from the replay cache "
        "(`data/fixtures/llm_cache/interpreter/`). Synthetic data._"
    )
    return "\n".join(L)


def write_results(text: str) -> None:
    body = f"{START}\n{text}\n{END}"
    cur = RESULTS.read_text(encoding="utf-8") if RESULTS.exists() else "# Evaluation results\n"
    if START in cur and END in cur:
        pre, rest = cur.split(START, 1)
        post = rest.split(END, 1)[1]
        new = pre + body + post
    else:
        new = cur.rstrip() + "\n\n" + body + "\n"
    RESULTS.write_text(new, encoding="utf-8", newline="\n")


# %%
if __name__ == "__main__":
    res = evaluate()
    f1, _ = macro_f1(res["llm_pairs"])
    kf1, _ = macro_f1(res["kw_pairs"])
    tot, ok = sum(res["fields_tot"].values()), sum(res["fields_ok"].values())
    print(f"macro-F1 AI {f1:.3f} vs keywords {kf1:.3f}; fields {ok}/{tot}; lines {res['lines']}")
    print(f"fallback {res['fallback']}, misclassified {res['misclass']}")
    print(f"missing {res['missing']}, dropped {res['dropped']}, extra {res['extra']}")
    for k, t in res["fields_tot"].items():
        print(f"   {k:24} {res['fields_ok'][k]}/{t}")
    write_results(section(res))
    print(f"wrote {RESULTS.relative_to(ROOT)}")

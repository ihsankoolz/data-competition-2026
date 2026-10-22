# %% [markdown]
# # Held-out "unseen emails" test (D-018 item 1)
#
# Run: `uv run python notebooks/eval_holdout.py` (offline, LLM_MODE=replay; `make eval`).
#
# Protocol, fixed before the interpreter read a single held-out email:
# - Frozen interpreter: prompt `interpreter_v2`, its text hash, output schema, keyword rules and
#   required-fields config are pinned by `tests/test_prompt_frozen.py`.
# - Emails: 24 written by a different model (`claude-sonnet-5-5`) from
#   `ds/interpreter/holdout/style_brief.md`, which never saw the generator's templates
#   (`ds/interpreter/holdout/generate.py`). Labels are that model's intent, computed missing
#   fields per `config/required_fields.yaml`, committed in e2ff0fe before the interpreter ran.
# - Scoring is the same as `notebooks/eval_interpreter.py` (same value normalisation and quote
#   check). One rule decided up front: order lines are scored only where the interpreter's
#   contract carries lines (orders, planned orders, enquiries); lines a label lists on a
#   follow-up are counted separately and not scored, exactly as on the tuned set.
# - Writes only between `<!-- holdout:start -->` and `<!-- holdout:end -->` in docs/results.md.

# %%
from __future__ import annotations

import importlib.util
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

from ds.interpreter.api import interpret_email, quote_ok  # noqa: E402
from ds.interpreter.bank import strip_bank_details  # noqa: E402
from ds.interpreter.keywords import classify_keywords  # noqa: E402
from ds.interpreter.prompt import PROMPT_VERSION  # noqa: E402

_spec = importlib.util.spec_from_file_location("eval_interpreter", ROOT / "notebooks" /
                                               "eval_interpreter.py")  # fmt: skip
ei = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ei)  # type: ignore[union-attr]

EMAILS = ROOT / "data" / "fixtures" / "holdout_emails.jsonl"
LABELS = ROOT / "data" / "fixtures" / "holdout_labels.jsonl"
RESULTS = ROOT / "docs" / "results.md"
START, END = "<!-- holdout:start -->", "<!-- holdout:end -->"
PRE_RUN_COMMIT = "e2ff0fe"
LINE_CATEGORIES = {"purchase_order", "purchase_request", "enquiry"}
# Set to False only when Ihsan has spot-checked the labels and said so.
LABELS_PENDING_SPOT_CHECK = True


# %%
def language_group(lang: str) -> str:
    """The writer's free-text language tag, grouped into the brief's six styles."""
    s = lang.lower()
    if "thai" in s:
        return "Thai-English"
    if "viet" in s:
        return "Vietnamese without diacritics" if "no diacritic" in s else "Vietnamese"
    if "malay" in s:
        return "Malay / Malay-English"
    if "indones" in s:
        return "Bahasa Indonesia"
    return "English"


def evaluate_holdout() -> dict:
    emails = ei.read_jsonl(EMAILS)
    labels = {r["email_id"]: r for r in ei.read_jsonl(LABELS)}
    llm_pairs, kw_pairs = [], []
    fields_tot: Counter = Counter()
    fields_ok: Counter = Counter()
    lines_tot = lines_ok = lines_unscored = 0
    dom_ok = kw_dom_ok = dom_n = missing_ok = 0
    fallback = review = injection = 0
    misclass, field_errors, missing_diff = [], [], []
    for e in emails:
        lab = labels[e["email_id"]]
        it = interpret_email(e["email_id"], e["subject"], e["body"], e["from_address"])
        kw = classify_keywords(*(strip_bank_details(x)[0] for x in (e["subject"], e["body"])))
        llm_pairs.append((lab["category"], it.category))
        kw_pairs.append((lab["category"], kw.category))
        fallback += it.method != "llm"
        review += it.needs_review
        injection += it.injection_suspected
        if it.category != lab["category"]:
            misclass.append((e["email_id"], lab["category"], it.category))
        if lab["category"] == "mdm_request":
            dom_n += 1
            dom_ok += it.domain == lab["domain"]
            kw_dom_ok += kw.domain == lab["domain"]
            same = set(it.missing_fields) == set(lab["missing_fields"])
            missing_ok += same
            if not same:
                missing_diff.append((e["email_id"], lab["missing_fields"], it.missing_fields))
        hay = " \n".join([strip_bank_details(x)[0] for x in (e["subject"], e["body"])]
                         + [e["from_address"]])  # fmt: skip
        hay_n = re.sub(r"\s+", " ", unicodedata.normalize("NFC", hay)).strip().casefold()
        got = {f.key: f for f in it.fields}
        for k, v in lab["expected_fields"].items():
            if k == "lines" or k in ei.EXCLUDED_KEYS:
                continue
            fields_tot[k] += 1
            f = got.get(k)
            ok = bool(
                f
                and quote_ok(f.source_quote, hay_n)
                and ei.value_ok(k, f.value, v["value"], f.source_quote, v["source_quote"])
            )
            fields_ok[k] += ok
            if not ok:
                field_errors.append((e["email_id"], k, v["value"], f.value if f else None))
        for want in lab["expected_fields"].get("lines", []):
            if lab["category"] not in LINE_CATEGORIES:
                lines_unscored += 1
                continue
            lines_tot += 1
            wq = float(want["qty"]) if want["qty"] is not None else None
            lines_ok += any(
                ln.item_code == want["item_code"] and (ln.qty or None) == wq for ln in it.lines
            )
    return dict(
        n=len(emails),
        llm_pairs=llm_pairs,
        kw_pairs=kw_pairs,
        fields=(sum(fields_ok.values()), sum(fields_tot.values())),
        fields_ok=fields_ok,
        fields_tot=fields_tot,
        lines=(lines_ok, lines_tot, lines_unscored),
        dom=(dom_ok, kw_dom_ok, dom_n),
        missing=(missing_ok, dom_n),
        fallback=fallback,
        review=review,
        injection=injection,
        misclass=misclass,
        field_errors=field_errors,
        missing_diff=missing_diff,
        languages=Counter(language_group(labels[e["email_id"]]["language"]) for e in emails),
        classes=Counter(lab["category"] for lab in labels.values()),
    )


def tuned_summary() -> dict:
    r = ei.evaluate()
    ok, tot = sum(r["fields_ok"].values()), sum(r["fields_tot"].values())
    return dict(
        n=r["n"],
        llm_pairs=r["llm_pairs"],
        kw_pairs=r["kw_pairs"],
        fields=(ok, tot),
        lines=(*r["lines"], 0),
        dom=r["dom"],
        missing=(r["missing"][0], r["missing"][2]),
        fallback=r["fallback"],
        review=r["review"],
    )


# %%
def acc(pairs: list[tuple[str, str]]) -> tuple[int, int]:
    return sum(t == p for t, p in pairs), len(pairs)


def frac(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}% ({a} of {b})" if b else "n/a"


def section(t: dict, h: dict) -> str:
    L: list[str] = []
    a = L.append
    tf1, _ = ei.macro_f1(t["llm_pairs"])
    hf1, hper = ei.macro_f1(h["llm_pairs"])
    tkf1, _ = ei.macro_f1(t["kw_pairs"])
    hkf1, _ = ei.macro_f1(h["kw_pairs"])
    a("## Email interpreter on unseen emails (D-018)")
    a("")
    if LABELS_PENDING_SPOT_CHECK:
        a("> **Labels pending human spot-check.** The numbers below may move once the answer "
          "key has been checked by a person.")  # fmt: skip
        a("")
    a(
        "**What was measured.** The same frozen interpreter (prompt "
        f"`{PROMPT_VERSION}`, `claude-haiku-5-5`, replayed) read {h['n']} emails it had never "
        "seen, written by a different model (`claude-sonnet-5-5`) from a short style brief "
        "(`ds/interpreter/holdout/style_brief.md`) that was written without looking at our "
        "email templates. The brief asks for varied tone, six language styles, forwarded "
        "threads with quoted history, missing fields and order-vs-plan close calls, with "
        "invented hospitals and labs. The writer also wrote the intended answer for each "
        "email; missing fields were then computed from its listed fields with the same "
        "required-fields config the app uses. The emails and answers were committed "
        f"(`{PRE_RUN_COMMIT}`) before the interpreter read them, and a test pins the prompt "
        "so it cannot be tuned afterwards (`tests/test_prompt_frozen.py`). Scoring rules are "
        "the same as for the tuned set above."
    )
    a("")
    a("| Measure | Tuned set (88 template emails) | Unseen emails "
      f"(n={h['n']}, written by a different model from a style brief) |")  # fmt: skip
    a("|---|---|---|")
    a(f"| Macro-F1, AI interpreter (5 classes) | {tf1:.3f} | {hf1:.3f} |")
    a(f"| Accuracy, AI interpreter | {frac(*acc(t['llm_pairs']))} | {frac(*acc(h['llm_pairs']))} |")
    a(f"| Macro-F1, keyword rules (baseline) | {tkf1:.3f} | {hkf1:.3f} |")
    a(f"| Accuracy, keyword rules | {frac(*acc(t['kw_pairs']))} | {frac(*acc(h['kw_pairs']))} |")
    a(f"| Fields copied out correctly (value and quote) | {frac(*t['fields'])} | "
      f"{frac(*h['fields'])} |")  # fmt: skip
    a(f"| Order lines correct (catalogue code and quantity) | {frac(*t['lines'][:2])} | "
      f"{frac(*h['lines'][:2])} |")  # fmt: skip
    a(f"| Master-data requests routed to the right form | {frac(t['dom'][0], t['dom'][2])} | "
      f"{frac(h['dom'][0], h['dom'][2])} |")  # fmt: skip
    a(f"| Master-data requests whose list of missing fields is exactly right | "
      f"{frac(*t['missing'])} | {frac(*h['missing'])} |")  # fmt: skip
    a(f"| AI answer missing, keyword fallback used | {t['fallback']} | {h['fallback']} |")
    a("")
    a("*Macro-F1* averages the F1 score of the five kinds of email, so a rare kind counts as "
      "much as a common one (1.0 = perfect). *Accuracy* is the share sorted into the right "
      "pile. A field counts as correct only if its value matches the answer key and its quote "
      "is really in the email.")  # fmt: skip
    a("")
    cls = ", ".join(f"{ei.SHORT[c]} {h['classes'][c]}" for c in ei.CLASSES)
    langs = ", ".join(f"{k} {v}" for k, v in sorted(h["languages"].items()))
    a(f"Unseen set make-up: {cls}. Languages as labelled by the writer: {langs}.")
    a("")
    a("AI interpreter on the unseen emails, rows = true class, columns = what it said:")
    a("")
    L.extend(ei.confusion(h["llm_pairs"]))
    a("")
    if h["misclass"]:
        wrong = [f"{i} ({ei.SHORT[t_]} read as {ei.SHORT[p]})" for i, t_, p in h["misclass"]]
        a("Emails sorted into the wrong pile: " + "; ".join(wrong) + ".")
    else:
        a("Every unseen email was sorted into the right pile.")
    a("")
    if h["field_errors"]:
        by_key = Counter(k for _, k, _, _ in h["field_errors"])
        a("Fields the AI got wrong, by field: " + ", ".join(
            f"`{k}` {n}" for k, n in by_key.most_common()) + ". `purpose` is free text, so "
          "a different but sensible wording counts as wrong; relative dates ('next quarter') "
          "are wrong when the AI leaves them out or picks another date phrase.")  # fmt: skip
        a("")
    if h["lines"][2]:
        a(f"{h['lines'][2]} order lines that the answer key lists on follow-up emails are not "
          "scored: the interpreter returns lines only for orders, planned orders and "
          "enquiries (decided before the run).")  # fmt: skip
        a("")
    a("**Caveats, said plainly.**")
    a("")
    a(f"- **Small sample.** {h['n']} emails, about 5 per kind: one email moves accuracy by "
      f"{100 / h['n']:.1f} points, and a per-class F1 rests on 4 or 5 emails.")  # fmt: skip
    a("- **The answer key is the writing model's intent**, not an independent human label. "
      "It is being spot-checked by a person; where the writer's label is debatable we list "
      "it and do not change it after seeing the interpreter's answers.")  # fmt: skip
    a("- **Different writer, still synthetic.** A different model wrote these from a brief, "
      "so they test phrasing and layouts our templates never produced. They are still "
      "AI-written emails, cleaner than a real inbox (no attachments to read, no typos from "
      "a phone keyboard at 2 am, no image-only POs).")  # fmt: skip
    a("- Customer names are scored strictly as written, as on the tuned set.")
    a("")
    a(
        f"> **For judges:** on {h['n']} emails written by a different AI from a style brief "
        f"(not from our templates), the reader sorts {frac(*acc(h['llm_pairs']))} correctly "
        f"against {frac(*acc(t['llm_pairs']))} on the emails we tuned it on, and the keyword "
        f"rules drop to {frac(*acc(h['kw_pairs']))}. The emails and answers were locked in "
        "before the reader saw them."
    )
    a("")
    a("_Generated by `uv run python notebooks/eval_holdout.py` from the replay cache. "
      "Synthetic data; every name, ID and address is invented._")  # fmt: skip
    return "\n".join(L)


def write_results(text: str) -> None:
    cur = RESULTS.read_text(encoding="utf-8")
    if START not in cur or END not in cur:
        raise SystemExit(f"markers {START} / {END} missing in {RESULTS}")
    pre, rest = cur.split(START, 1)
    post = rest.split(END, 1)[1]
    RESULTS.write_text(pre + f"{START}\n{text}\n{END}" + post, encoding="utf-8", newline="\n")


# %%
if __name__ == "__main__":
    h = evaluate_holdout()
    t = tuned_summary()
    f1, _ = ei.macro_f1(h["llm_pairs"])
    kf1, _ = ei.macro_f1(h["kw_pairs"])
    print(f"holdout: macro-F1 AI {f1:.3f} vs keywords {kf1:.3f}; acc {acc(h['llm_pairs'])}, "
          f"kw {acc(h['kw_pairs'])}; fields {h['fields']}; lines {h['lines']}; "
          f"missing {h['missing']}; dom {h['dom']}; fallback {h['fallback']}")  # fmt: skip
    print("misclassified:", h["misclass"])
    print("keyword misclassified:", [(i + 1, t_, p) for i, (t_, p) in
                                     enumerate(h["kw_pairs"]) if t_ != p])  # fmt: skip
    for row in h["field_errors"]:
        print("  field miss:", row)
    for row in h["missing_diff"]:
        print("  missing diff:", row)
    write_results(section(t, h))
    print(f"wrote {RESULTS.relative_to(ROOT)}")

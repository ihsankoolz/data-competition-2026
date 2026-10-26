# ruff: noqa: F811  (fixtures imported from test_workflow_api are used by name)
"""Item duplicate check (session 13): normaliser, each layer, DEMO-02 stays a no-match, the
hand-made evaluation is reproducible, and the check never links anything on its own (rule 6).

The examples in the unit tests below were written before `ds/dedup/item_eval_set.yaml` and are
deliberately different from its pairs, so the thresholds are not fitted to the evaluation set.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ds.dedup.item_eval import evaluate, load_cases
from ds.dedup.items import (
    ItemIndex,
    ItemQuery,
    ItemRegistrationRef,
    check_item,
    load_catalogue,
    name_similarity,
    name_tokens,
    normalise_code,
    normalise_item_name,
    normalise_reg_no,
    records_from_fixtures,
    strip_pack_size,
)
from tests.test_workflow_api import H, client, new_request  # noqa: F401

OWNS_APP_DB = True  # the module-scoped `client` builds its own database
FIXTURES = Path("data/fixtures/seasonal_trend")
MALARIA = "Malaria Pf/Pan Antigen Rapid Test Kit"


@pytest.fixture(scope="module")
def index() -> ItemIndex:
    return ItemIndex(records_from_fixtures(FIXTURES))


def check(index, name="", **kw):
    regs = [ItemRegistrationRef(**r) for r in kw.pop("registrations", [])]
    return check_item(ItemQuery(ItemName=name, registrations=regs, **kw), index)


# ---------------------------------------------------------------- normaliser


@pytest.mark.parametrize(
    "raw",
    [
        "Dengue NS1 kit, box of 25",
        "Dengue NS1 kit (25 tests)",
        "Dengue NS1 kit x25",
        "Dengue NS1 kit 25T",
        "Dengue NS1 kit 25 tests/kit",
        "Dengue NS1 kit 2 x 50 ml",
    ],
)
def test_pack_sizes_and_units_are_removed(raw):
    assert normalise_item_name(raw) == normalise_item_name("Dengue NS1 kit")


def test_tokens_expand_abbreviations_and_ignore_case_punctuation_and_order():
    assert name_tokens("Rapid Dengue NS-1 Ag Test Kit") == [
        "rapid", "dengue", "ns1", "antigen", "test", "kit",
    ]  # fmt: skip
    assert normalise_item_name("HAEMATOLOGY ANALYZER, 5-PART") == normalise_item_name(
        "5-part Hematology Analyser"
    )
    assert "pack" not in strip_pack_size("box of 25")


def test_codes_and_registration_numbers_ignore_spacing_and_ref():
    assert normalise_code("REF 51-DNS1-25") == normalise_code("51dns1 25") == "51DNS125"
    assert normalise_code("a-den-ns1") == "ADENNS1"
    assert normalise_reg_no("24170581ĐKLH/BYT-HTTB") == "24170581DKLHBYTHTTB"


def test_catalogue_file_is_labelled_synthetic_and_covers_the_15_items():
    text = Path("config/item_catalogue.yaml").read_text(encoding="utf-8")
    assert text.startswith("# SYNTHETIC DATA.")
    assert "synthetic: true" in text
    assert len(load_catalogue()) == 15


# ---------------------------------------------------------------- name layer


def test_near_copy_of_an_existing_kit_is_likely_with_reasons(index):
    r = check(index, "Rapid Dengue NS1 Antigen Test Kit, 25 tests")
    assert r.verdict == "likely" and r.block_submit
    top = r.candidates[0]
    assert top.ItemCode == "A-DEN-NS1" and top.verdict == "likely"
    assert any(x.layer == "name" for x in top.reasons)


def test_generic_words_alone_never_match(index):
    for name in ("Rapid Test Kit", "Reagent", "Analyser", "Test Kit 25 tests"):
        assert check(index, name).verdict == "none", name


@pytest.mark.parametrize(
    "name", [MALARIA, "Typhoid IgM Rapid Test Kit", "Chikungunya Antigen Rapid Test"]
)
def test_kits_that_share_only_generic_words_do_not_match(index, name):
    assert check(index, name).verdict == "none"


def test_dengue_ns1_and_dengue_igg_igm_are_not_the_same_kit(index):
    ns1 = name_similarity("Dengue NS1 Antigen Kit", "Dengue IgG/IgM Rapid Test Kit").score
    assert ns1 < 0.60


def test_different_model_numbers_lower_the_score(index):
    same = name_similarity("Haematology Analyser 5-part", "5-part Haematology Analyser")
    other = name_similarity("Haematology Analyser 3-part", "5-part Haematology Analyser")
    assert same.score == 1.0
    assert other.numbers_differ and other.score < 0.60


# ---------------------------------------------------------------- catalogue and registration layers


def test_same_catalogue_number_is_likely_even_with_a_vague_name(index):
    r = check(index, "Biosafety hood", manufacturer_catalogue_no="bs2 1200")
    assert r.verdict == "likely" and r.candidates[0].ItemCode == "B-BSC-II"
    assert r.candidates[0].catalogue_match
    assert "synthetic" in r.candidates[0].reasons[0].text


def test_typing_an_existing_item_code_as_catalogue_number_is_likely(index):
    r = check(index, "Microscope", manufacturer_catalogue_no="b-mic-bin")
    assert r.candidates[0].ItemCode == "B-MIC-BIN" and r.candidates[0].verdict == "likely"


def test_same_registration_in_the_same_country_is_likely(index):
    r = check(index, "Glyco kit", registrations=[{"country": "ID", "reg_no": "AKL 24491005139"}])
    top = r.candidates[0]
    assert top.ItemCode == "A-HBA-1C" and top.verdict == "likely" and top.registration_match
    assert "can't belong to two products" in top.reasons[0].text


def test_same_registration_number_in_another_country_is_not_a_match(index):
    # A-HBA-1C's Indonesian number typed as a Thai registration: no rule fires.
    r = check(index, "Glyco kit", registrations=[{"country": "TH", "reg_no": "AKL 24491005139"}])
    assert r.verdict == "none"


def test_different_catalogue_number_counts_against_a_name_match(index):
    plain = check(index, "Binocular Laboratory Microscope").candidates[0].score
    other = check(index, "Binocular Laboratory Microscope", manufacturer_catalogue_no="ZZ-1")
    assert other.candidates[0].score < plain


def test_the_item_a_request_published_is_never_its_own_match(index):
    r = check(index, "Binocular Laboratory Microscope", exclude_item_codes=["B-MIC-BIN"])
    assert all(c.ItemCode != "B-MIC-BIN" for c in r.candidates)


# ---------------------------------------------------------------- evaluation is reproducible


def test_hand_made_eval_numbers_are_reproducible_and_match_results_md():
    cases = load_cases()
    assert len(cases) == 50 and len({c.id for c in cases}) == 50
    a, b = evaluate(), evaluate()
    assert a == b
    likely, either = a.scores
    assert (likely.tp, likely.fp, likely.fn) == (31, 0, 2)
    assert (either.tp, either.fp, either.fn) == (31, 3, 2)
    text = Path("docs/results.md").read_text(encoding="utf-8")
    section = text.split("<!-- item-dedup:start -->", 1)[1].split("<!-- item-dedup:end -->")[0]
    assert re.search(r"\| Likely \| 100\.0% \| 93\.9% \| 31 \| 0 \| 2 \|", section)
    assert "Hand-made test set of 50 pairs, small, written by us, not generator" in section
    assert "synthetic catalogue numbers" in section


def test_demo02_malaria_kit_is_a_hard_negative_in_the_eval_set():
    by_id = {c.id: c for c in evaluate().cases}
    assert by_id["N01"].name == MALARIA and by_id["N01"].level == "none"
    assert by_id["N02"].level == "none"


# ---------------------------------------------------------------- API: DEMO-02 and rule 6


def test_demo02_prefilled_fields_give_no_match(client):
    r = client.post("/requests/from-email/DEMO-02", headers=H("amy"))
    assert r.status_code in (200, 201), r.text
    d = r.json()
    assert d["fields"]["ItemName"] == MALARIA
    assert "manufacturer_catalogue_no" not in d["fields"]  # never prefilled from email
    assert d["item_match"] == "none"
    c = client.post(
        "/dedup/check-item",
        headers=H("amy"),
        json={"fields": d["fields"], "request_id": d["req_id"]},
    )
    assert c.status_code == 200, c.text
    assert c.json()["verdict"] == "none" and c.json()["candidates"] == []
    assert "No existing item matched" in c.json()["message"]
    assert "decide_duplicate" in d["allowed_actions"]


def test_check_never_links_and_a_likely_item_waits_for_a_person(client):
    fields = {"ItemName": "Dengue NS1 Ag Rapid Test Kit (25T)", "U_IVD": "tNO",
              "selling_countries": ["SG"]}  # fmt: skip
    d = new_request(client, "amy", "item", "SPD", "SG", fields)
    rid = d["req_id"]
    assert d["item_match"] == "likely"
    r = client.post(
        "/dedup/check-item", headers=H("amy"), json={"fields": fields, "request_id": rid}
    ).json()
    assert r["verdict"] == "likely" and r["candidates"][0]["ItemCode"] == "A-DEN-NS1"
    # Rule 6: the check only advises. Nothing was linked, nothing changed state.
    d = client.get(f"/requests/{rid}", headers=H("amy")).json()
    assert d["state"] == "DRAFT" and d["linked_card_code"] is None and d["dedup_decision"] is None
    s = client.post(f"/requests/{rid}/submit", headers=H("amy"))
    assert s.status_code == 409 and "A-DEN-NS1" in s.json()["detail"]
    # "Not the same" needs a reason.
    bad = client.post(
        f"/requests/{rid}/dedup-decision",
        headers=H("amy"),
        json={"action": "not_duplicate", "reason": "no"},
    )
    assert bad.status_code == 422
    # The person chooses the existing item: the request is linked and needs no approval.
    ok = client.post(
        f"/requests/{rid}/dedup-decision",
        headers=H("amy"),
        json={"action": "link_to_existing", "card_code": "A-DEN-NS1"},
    )
    assert ok.status_code == 200, ok.text
    d = ok.json()
    assert d["state"] == "LINKED_TO_EXISTING" and d["linked_card_code"] == "A-DEN-NS1"
    assert d["linked_card_name"] == "Rapid Dengue NS1 Ag Test Kit"
    audit = [e["summary"] for e in client.get(f"/requests/{rid}/audit", headers=H("amy")).json()]
    assert any("chose the existing item A-DEN-NS1" in s for s in audit)
    assert any("Item duplicate check run by" in s for s in audit)


def test_not_the_same_with_a_reason_lets_a_likely_item_through(client):
    fields = {"ItemName": "Binocular Lab Microscope", "U_IVD": "tNO", "selling_countries": ["SG"]}
    d = new_request(client, "amy", "item", "SPD", "SG", fields)
    rid = d["req_id"]
    assert client.post(f"/requests/{rid}/submit", headers=H("amy")).status_code == 409
    r = client.post(
        f"/requests/{rid}/dedup-decision",
        headers=H("amy"),
        json={"action": "not_duplicate", "reason": "A different maker's teaching microscope"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["dedup_decision"]["action"] == "not_duplicate"
    s = client.post(f"/requests/{rid}/submit", headers=H("amy"))
    assert s.status_code == 200 and s.json()["state"] == "IN_APPROVAL"


def test_linking_to_an_unknown_item_is_refused(client):
    d = new_request(client, "amy", "item", "SPD", "SG", {"ItemName": "Some new kit"})
    r = client.post(
        f"/requests/{d['req_id']}/dedup-decision",
        headers=H("amy"),
        json={"action": "link_to_existing", "card_code": "NOPE-1"},
    )
    assert r.status_code == 422

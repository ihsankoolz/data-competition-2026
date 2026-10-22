"""Duplicate check (D-005): one test per layer and per hard rule, plus the demo anchors.

Builds its own master: a freshly generated dataset in a tmp dir (never data/generated/), and
small handmade masters for the rules.
"""

from __future__ import annotations

import json
import statistics
import time

import pytest

from ds.dedup import BPQuery, BPRecord, MasterIndex, check, load_master, matcher
from ds.dedup.judge import (
    JUDGE_FIELDS,
    SYSTEM_PROMPT,
    TASK,
    JudgeOutput,
    build_payload,
    judge_record,
)
from ds.dedup.normalize import normalise_name, normalise_phone, valid_tax_id
from ds.generator.core import generate
from ds.interpreter import llm


@pytest.fixture(scope="module")
def gen_index(tmp_path_factory) -> MasterIndex:
    folder = generate("seasonal_trend", 42, tmp_path_factory.mktemp("dedup_gen"))
    return MasterIndex(load_master(folder))


@pytest.fixture(autouse=True)
def _replay_empty_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_MODE", "replay")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "llm_cache"))


def rec(code: str, name: str, country: str, **kw) -> BPRecord:
    return BPRecord(CardCode=code, CardName=name, Country=country, **kw)


def texts(c) -> str:
    return " | ".join(r.text for r in c.reasons)


# ---------------------------------------------------------------- demo anchors (generated)
def test_demo01_cho_ray_matches_spd_record_by_mst_and_accents(gen_index):
    q = BPQuery(
        CardName="Benh vien Cho Ray", Country="VN", FederalTaxID="0301234567", CardType="cCustomer"
    )
    res = check(q, gen_index)
    top = res.candidates[0]
    assert top.CardName == "Bệnh viện Chợ Rẫy"
    assert top.entity == "SPD"
    assert top.verdict == "likely" and res.verdict == "likely" and res.block_submit
    assert "Same MST 0301234567" in texts(top)
    assert "accents" in texts(top)


def test_nuh_acronym_matches_full_legal_name(gen_index):
    res = check(BPQuery(CardName="NUH", Country="SG"), gen_index)
    names = {c.CardName: c for c in res.candidates}
    full = names["National University Hospital (S) Pte Ltd"]
    assert full.verdict == "likely"
    assert "NUH" in texts(full)


@pytest.mark.parametrize("typed", ["RSCM", "RS Cipto Mangunkusumo"])
def test_rscm_and_rs_match_rumah_sakit(gen_index, typed):
    res = check(BPQuery(CardName=typed, Country="ID"), gen_index)
    names = {c.CardName: c for c in res.candidates}
    assert names["Rumah Sakit Cipto Mangunkusumo"].verdict == "likely"


def test_thai_script_siriraj_finds_english_name(gen_index):
    res = check(BPQuery(CardName="โรงพยาบาลศิริราช", Country="TH"), gen_index)
    names = {c.CardName: c for c in res.candidates}
    assert "Siriraj Hospital" in names
    assert names["Siriraj Hospital"].score >= 0.70


def test_latency_under_50ms_on_generated_master(gen_index):
    qs = [
        BPQuery(CardName=e.rec.CardName, Country=e.rec.Country, City=e.rec.City)
        for e in gen_index.entries[:60]
    ]
    times = []
    for q in qs:
        t = time.perf_counter()
        check(q, gen_index)
        times.append((time.perf_counter() - t) * 1000)
    assert statistics.median(times) < 50


# ---------------------------------------------------------------- layers (handmade)
def test_layer1_same_tax_id_is_likely_even_with_different_script():
    master = [rec("C1", "โรงพยาบาลศิริราช", "TH", FederalTaxID="0105460515817")]
    res = check(
        BPQuery(CardName="Siriraj Hosp", Country="TH", FederalTaxID="0105-460-515-817"), master
    )
    assert res.candidates[0].tax_id_match and res.verdict == "likely"


def test_layer1_same_tax_id_in_another_country_is_not_a_match():
    master = [rec("C1", "Acme Diagnostics Pte Ltd", "SG", FederalTaxID="201912345K")]
    res = check(
        BPQuery(CardName="Acme Diagnostics Sdn Bhd", Country="MY", FederalTaxID="201912345K"),
        master,
    )
    assert res.candidates == []


def test_layer2_suffix_and_punctuation():
    a = normalise_name("BioLab Pte Ltd", "SG")
    b = normalise_name("BIOLAB PTE. LTD.", "SG")
    assert a.main == b.main == ("biolab",)
    res = check(
        BPQuery(CardName="BIOLAB PTE. LTD.", Country="SG"), [rec("C1", "BioLab Pte Ltd", "SG")]
    )
    assert res.verdict == "likely" and "punctuation" in texts(res.candidates[0])


def test_layer2_vietnamese_legal_prefix_and_diacritics():
    a = normalise_name("Công ty TNHH Xét nghiệm Y khoa Nam Việt", "VN")
    b = normalise_name("Cong ty TNHH Xet nghiem Y khoa Nam Viet", "VN")
    assert a.main == b.main
    assert "tnhh" not in a.main


def test_layer2_thai_legal_words_removed():
    f = normalise_name("บริษัท ห้องปฏิบัติการศุภมิตร สาทรจำกัด", "TH")
    assert f.main[0] == "laboratory"
    assert not any("chamkad" in t or "chmakad" in t for t in f.main)


def test_layer3_dictionary_rumah_sakit_and_benh_vien():
    assert (
        normalise_name("RS Hermina", "ID").main == normalise_name("Rumah Sakit Hermina", "ID").main
    )
    assert normalise_name("Bệnh viện Từ Dũ", "VN").main == ("hospital", "tu", "du")
    assert set(normalise_name("Tu Du Hospital", "VN").main) == {"hospital", "tu", "du"}


def test_layer4_typo_scores_possible_or_better():
    master = [rec("C1", "Tembusu Diagnostics Sdn Bhd", "MY", City="Kuala Lumpur")]
    res = check(
        BPQuery(CardName="Temnusu Diagnostics Sdn Bhd", Country="MY", City="K. Lumpur"), master
    )
    assert res.candidates and res.candidates[0].score >= 0.70


def test_layer5_phone_normalisation():
    assert normalise_phone("+65 6896 2404", "SG") == normalise_phone("68962404", "SG")
    assert normalise_phone("(021) 7220-1287", "ID") == normalise_phone("+62 21 7220 1287", "ID")


def test_malformed_tax_id_is_ignored():
    assert not valid_tax_id("TBC", "TH")
    assert valid_tax_id("01.234.567.8-901.000", "ID")


def test_unrelated_names_not_returned():
    master = [rec("C1", "Tan Tock Seng Hospital Pte Ltd", "SG")]
    assert check(BPQuery(CardName="Zenith Lab Services", Country="SG"), master).verdict == "none"


# ---------------------------------------------------------------- hard rules
def test_customer_vendor_pair_never_returned():
    master = [
        rec("C1", "BioMed Lab Supplies Pte Ltd", "SG", FederalTaxID="201811111A"),
        rec(
            "V1",
            "BioMed Lab Supplies Pte Ltd",
            "SG",
            FederalTaxID="201811111A",
            CardType="cSupplier",
        ),
    ]
    for ctype, other in (("cCustomer", "V1"), ("cSupplier", "C1")):
        q = BPQuery(
            CardName="BioMed Lab Supplies Pte Ltd",
            Country="SG",
            FederalTaxID="201811111A",
            CardType=ctype,
        )
        res = check(q, master)
        assert all(c.CardType == ctype for c in res.candidates)
        assert other not in {c.CardCode for c in res.candidates}
        assert [r.rule for r in res.related] == ["customer_vendor"]


def test_sentosa_sg_vs_kl_not_flagged_but_shown_as_group_member():
    master = [
        rec(
            "C1",
            "Sentosa Specialist Hospital Kuala Lumpur Sdn Bhd",
            "MY",
            FederalTaxID="198601851728",
        ),
    ]
    res = check(BPQuery(CardName="Sentosa Specialist Hospital", Country="SG"), master)
    assert res.candidates == [] and res.verdict == "none"
    assert res.related and res.related[0].rule == "same_group_other_country"
    assert res.related[0].group_id == "GRP01"


def test_explicit_group_id_on_record_is_used():
    master = [rec("C1", "Lotus Clinic Hanoi", "VN", group_id="GRP99")]
    res = check(BPQuery(CardName="Lotus Clinic", Country="TH", group_id="GRP99"), master)
    assert res.candidates == []
    assert res.related and res.related[0].group_id == "GRP99"


@pytest.mark.parametrize(
    "tax_a,tax_b", [("199700001A", "200800002B"), (None, None)], ids=["both-tax-ids", "no-tax-ids"]
)
def test_mount_elizabeth_vs_novena_not_likely(tax_a, tax_b):
    master = [rec("C1", "Mount Elizabeth Hospital Pte Ltd", "SG", FederalTaxID=tax_a)]
    res = check(
        BPQuery(CardName="Mount Elizabeth Novena Hospital", Country="SG", FederalTaxID=tax_b),
        master,
    )
    assert res.verdict != "likely"
    assert not res.block_submit


def test_number_mismatch_blocks_likely():
    master = [rec("C1", "Phyathai 2 Hospital", "TH")]
    res = check(BPQuery(CardName="Phyathai 1 Hospital", Country="TH"), master)
    assert res.verdict != "likely"


def test_nothing_is_merged_result_is_advice_only():
    master = [rec("C1", "BioLab Pte Ltd", "SG")]
    before = [m.model_dump() for m in master]
    check(BPQuery(CardName="BioLab Pte Ltd", Country="SG"), master)
    assert [m.model_dump() for m in master] == before


# ---------------------------------------------------------------- grey zone + LLM judge
def _grey_master() -> list[BPRecord]:
    return [rec("C1", "Laboratorium Klinik Husada Amanah", "ID", City="Palembang")]


def _grey_query() -> BPQuery:
    return BPQuery(CardName="Klinik Husada Amanah", Country="ID")


def test_grey_zone_with_empty_cache_is_offline_and_stays_possible():
    res = check(_grey_query(), _grey_master())
    assert res.grey_zone
    assert res.judge.status == "offline"
    assert res.verdict == "possible" and not res.block_submit


def test_grey_zone_replay_hit_gives_second_opinion_but_does_not_change_verdict():
    master, q = _grey_master(), _grey_query()
    first = check(q, master)
    payload = build_payload(q, first.candidates)
    model = llm.resolve_model(TASK)
    key = llm.cache_key(model, "dedup_judge_v1", payload)
    answer = JudgeOutput(selected_card_code="C1", reasons=["Same lab name in Indonesian"])
    llm.write_cache(
        TASK, key, llm.make_entry(TASK, model, "dedup_judge_v1", SYSTEM_PROMPT, payload, answer)
    )
    res = check(q, master)
    assert res.judge.status == "ok" and res.judge.selected_card_code == "C1"
    assert res.verdict == "possible"  # the AI never decides (domain rule 6)


# ---------------------------------------------------------------- QA additions
def test_same_group_identical_name_other_country_blank_tax_is_related_not_candidate():
    master = [rec("C1", "Sentosa Specialist Hospital", "MY")]  # no tax ID on either side
    res = check(BPQuery(CardName="Sentosa Specialist Hospital", Country="SG"), master)
    assert res.candidates == [] and res.verdict == "none" and not res.block_submit
    assert [(r.CardCode, r.rule, r.group_id) for r in res.related] == [
        ("C1", "same_group_other_country", "GRP01")
    ]


def test_tax_id_match_with_very_different_name_is_likely_and_says_why():
    master = [rec("C1", "Công ty TNHH Xét nghiệm Y khoa Nam Việt", "VN", FederalTaxID="0312571586")]
    res = check(
        BPQuery(CardName="Zenith Holdings", Country="VN", FederalTaxID="0312571586"), master
    )
    top = res.candidates[0]
    assert top.tax_id_match and top.verdict == "likely" and res.block_submit
    assert top.name_score < 0.5
    assert top.reasons[0].text == "Same MST 0312571586"
    assert "similar" in texts(top)  # the low name similarity is shown too


@pytest.mark.parametrize(
    "score,verdict,grey",
    [
        (0.92, "likely", False),
        (0.9199, "possible", True),
        (0.70, "possible", True),
        (0.6999, "none", False),
    ],
)
def test_threshold_boundaries(monkeypatch, score, verdict, grey):
    def fixed(index, q, e):
        return score, score, False, []

    monkeypatch.setattr(matcher, "_score_pair", fixed)
    res = check(
        BPQuery(CardName="Anything", Country="SG"), [rec("C1", "Other", "SG")], use_judge=False
    )
    assert res.verdict == verdict
    assert res.grey_zone is grey
    assert res.block_submit is (verdict == "likely")


def test_judge_payload_never_contains_bank_fields():
    record = {
        "CardName": "Isotek Biotech GmbH",
        "Country": "DE",
        "City": "Hamburg",
        "FederalTaxID": "DE082858183",
        "EmailAddress": "ar@isotek.de.example",
        "BankCode": "58064300",
        "AccountNo": "3041434261",
        "AccountName": "Isotek Biotech GmbH",
        "BICSwiftCode": "JHUJDEGOXXX",
        "IBAN": "DE15580643003041434261",
        "BankCountry": "DE",
        "Phone1": "+49 87 2206596",
    }
    projected = judge_record(record)
    assert tuple(projected) == JUDGE_FIELDS
    payload = build_payload(record, [])
    for secret in ("58064300", "3041434261", "JHUJDEGOXXX", "DE15580643003041434261", "2206596"):
        assert secret not in payload
    assert json.loads(payload)["new_record"]["email_domain"] == "isotek.de.example"

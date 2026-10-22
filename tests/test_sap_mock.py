import pytest
from fastapi.testclient import TestClient

from services.sap_mock.main import SESSION_TIMEOUT_MINUTES, create_app

BASE = "/b1s/v2"
LOGIN = {"CompanyDB": "LIVES_DEMO", "UserName": "mdm_integration", "Password": "demo"}


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance_minutes(self, minutes: float) -> None:
        self.t += minutes * 60


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def client(clock):
    """Logged-in client with a fresh in-memory store."""
    c = TestClient(create_app(clock=clock))
    assert c.post(f"{BASE}/Login", json=LOGIN).status_code == 200
    return c


@pytest.fixture
def anon(clock):
    return TestClient(create_app(clock=clock))


def assert_b1_error(resp, status, code, contains=""):
    assert resp.status_code == status, resp.text
    err = resp.json()["error"]
    assert err["code"] == code
    assert err["message"]["lang"] == "en-us"
    assert contains in err["message"]["value"]
    return err


BP = {
    "CardCode": "C00123",
    "CardName": "Bệnh viện Chợ Rẫy",
    "CardType": "cCustomer",
    "FederalTaxID": "0301234567",
    "Frozen": "tYES",
    "U_Entity": "SPD",
}
ITEM = {
    "ItemCode": "PRODA-001",
    "ItemName": "Product A",
    "ItemType": "itItems",
    "SalesItem": "tYES",
    "U_IVD": "tNO",
    "Frozen": "tNO",
}
PC = {
    "CenterCode": "CC-SG01",
    "CenterName": "SG Sales",
    "EffectiveFrom": "2026-10-05",
    "InWhichDimension": 1,
    "Active": "tYES",
}
CASES = [
    ("BusinessPartners", "CardCode", BP, {"Frozen": "tNO"}),
    ("Items", "ItemCode", ITEM, {"Frozen": "tYES"}),
    ("ProfitCenters", "CenterCode", PC, {"Active": "tNO"}),
]


# ---- login / session ----


def test_login_sets_both_cookies(anon):
    r = anon.post(f"{BASE}/Login", json=LOGIN)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"SessionId", "Version", "SessionTimeout"}
    assert body["SessionTimeout"] == 30
    assert anon.cookies.get("B1SESSION") == body["SessionId"]
    assert anon.cookies.get("ROUTEID")


def test_login_bad_credentials(anon):
    r = anon.post(f"{BASE}/Login", json={**LOGIN, "Password": "wrong"})
    assert_b1_error(r, 401, -304)
    assert "B1SESSION" not in anon.cookies


def test_login_missing_field(anon):
    r = anon.post(f"{BASE}/Login", json={"UserName": "x"})
    assert_b1_error(r, 400, -10, "CompanyDB")


def test_no_cookies_is_401(anon):
    assert_b1_error(anon.get(f"{BASE}/BusinessPartners"), 401, 301)
    assert_b1_error(anon.post(f"{BASE}/BusinessPartners", json=BP), 401, 301)


def test_needs_both_cookies(client):
    sid = client.cookies.get("B1SESSION")
    url = f"{BASE}/BusinessPartners"

    client.cookies.clear()
    client.cookies.set("B1SESSION", sid)  # ROUTEID missing
    assert_b1_error(client.get(url), 401, 301)

    client.cookies.clear()
    client.cookies.set("ROUTEID", ".node1")  # B1SESSION missing
    assert_b1_error(client.get(url), 401, 301)

    client.cookies.set("B1SESSION", "unknown-session")
    assert_b1_error(client.get(url), 401, 301)

    client.cookies.set("B1SESSION", sid)  # both valid again
    assert client.get(url).status_code == 200


def test_idle_timeout_expires_session(client, clock):
    clock.advance_minutes(SESSION_TIMEOUT_MINUTES + 1)
    assert_b1_error(client.get(f"{BASE}/BusinessPartners"), 401, 301)


def test_activity_refreshes_session(client, clock):
    for _ in range(3):
        clock.advance_minutes(20)  # 60 min in total, but never idle for 30
        assert client.get(f"{BASE}/BusinessPartners").status_code == 200


def test_logout_ends_session(client):
    assert client.post(f"{BASE}/Logout").status_code == 204
    assert_b1_error(client.get(f"{BASE}/BusinessPartners"), 401, 301)


# ---- CRUD round trips ----


@pytest.mark.parametrize(("name", "key", "payload", "patch"), CASES)
def test_post_get_patch_round_trip(client, name, key, payload, patch):
    r = client.post(f"{BASE}/{name}", json=payload)
    assert r.status_code == 201
    assert r.json() == payload

    code = payload[key]
    r = client.get(f"{BASE}/{name}('{code}')")
    assert r.status_code == 200
    assert r.json() == payload  # read-back matches what was sent

    r = client.patch(f"{BASE}/{name}('{code}')", json=patch)
    assert r.status_code == 204
    assert r.content == b""

    after = client.get(f"{BASE}/{name}('{code}')").json()
    assert after == {**payload, **patch}

    listing = client.get(f"{BASE}/{name}").json()
    assert listing == {"value": [after]}


@pytest.mark.parametrize(("name", "key", "payload", "patch"), CASES)
def test_duplicate_key_rejected(client, name, key, payload, patch):
    assert client.post(f"{BASE}/{name}", json=payload).status_code == 201
    r = client.post(f"{BASE}/{name}", json=payload)
    assert_b1_error(r, 400, -5002, "This entry already exists in the following tables")


@pytest.mark.parametrize(("name", "key", "payload", "patch"), CASES)
def test_not_found_shape(client, name, key, payload, patch):
    assert_b1_error(client.get(f"{BASE}/{name}('NOPE')"), 404, -2028)
    assert_b1_error(client.patch(f"{BASE}/{name}('NOPE')", json=patch), 404, -2028)


def test_patch_key_is_immutable(client):
    client.post(f"{BASE}/BusinessPartners", json=BP)
    r = client.patch(f"{BASE}/BusinessPartners('C00123')", json={"CardCode": "C99999"})
    assert_b1_error(r, 400, -10, "read-only")
    assert client.get(f"{BASE}/BusinessPartners('C00123')").status_code == 200


def test_patch_validates(client):
    client.post(f"{BASE}/BusinessPartners", json=BP)
    r = client.patch(f"{BASE}/BusinessPartners('C00123')", json={"Frozen": "tyes"})
    assert_b1_error(r, 400, -10, "Frozen")
    assert client.get(f"{BASE}/BusinessPartners('C00123')").json()["Frozen"] == "tYES"


def test_nested_addresses_and_bank_accounts(client):
    bp = {
        **BP,
        "BPAddresses": [
            {"AddressName": "HQ", "AddressType": "bo_BillTo", "City": "HCMC", "Country": "VN"}
        ],
        "BPBankAccounts": [{"BankCode": "VCB", "AccountNo": "999", "IBAN": "X", "Country": "VN"}],
    }
    assert client.post(f"{BASE}/BusinessPartners", json=bp).status_code == 201
    assert client.get(f"{BASE}/BusinessPartners('C00123')").json() == bp


# ---- validation ----


@pytest.mark.parametrize(
    ("name", "payload", "bad", "needle"),
    [
        ("BusinessPartners", BP, {"Frozen": "yes"}, "Frozen"),
        ("BusinessPartners", BP, {"Frozen": "tyes"}, "Frozen"),  # case-sensitive
        ("BusinessPartners", BP, {"CardType": "cvendor"}, "CardType"),
        ("BusinessPartners", BP, {"CardCode": "C" * 16}, "CardCode"),
        ("BusinessPartners", BP, {"CardName": "N" * 101}, "CardName"),
        ("BusinessPartners", BP, {"FederalTaxID": "9" * 33}, "FederalTaxID"),
        ("BusinessPartners", BP, {"U_Entity": "XYZ"}, "U_Entity"),
        ("BusinessPartners", BP, {"Bogus": 1}, "Bogus"),
        ("BusinessPartners", BP, {"GroupCode": "100"}, "GroupCode"),  # no string->int coercion
        (
            "BusinessPartners",
            BP,
            {"BPAddresses": [{"AddressName": "HQ", "AddressType": "bo_Other"}]},
            "AddressType",
        ),
        ("Items", ITEM, {"ItemCode": "I" * 21}, "ItemCode"),
        ("Items", ITEM, {"PurchaseItem": "TRUE"}, "PurchaseItem"),
        ("Items", ITEM, {"ItemType": "itLabor"}, "ItemType"),
        ("ProfitCenters", PC, {"CenterCode": "123456789"}, "CenterCode"),
        ("ProfitCenters", PC, {"CenterName": "N" * 31}, "CenterName"),
        ("ProfitCenters", PC, {"EffectiveFrom": "not-a-date"}, "EffectiveFrom"),
        ("ProfitCenters", PC, {"Active": "Y"}, "Active"),
    ],
)
def test_validation_errors_in_b1_shape(client, name, payload, bad, needle):
    r = client.post(f"{BASE}/{name}", json={**payload, **bad})
    assert_b1_error(r, 400, -10, needle)


def test_missing_required_field(client):
    r = client.post(f"{BASE}/BusinessPartners", json={"CardName": "No code"})
    assert_b1_error(r, 400, -10, "CardCode")


def test_malformed_json_is_b1_error(client):
    r = client.post(
        f"{BASE}/BusinessPartners",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )
    assert_b1_error(r, 400, -10)


def test_validation_error_does_not_echo_bank_values(client):
    secret = "SECRET-ACCOUNT-9876543210"
    bp = {**BP, "BPBankAccounts": [{"AccountNo": secret, "Country": "VNM"}]}
    r = client.post(f"{BASE}/BusinessPartners", json=bp)
    assert_b1_error(r, 400, -10, "Country")
    assert secret not in r.text


def test_bad_query_param_uses_b1_shape(client):
    r = client.get(f"{BASE}/BusinessPartners", params={"$top": "abc"})
    assert_b1_error(r, 400, -10)


# ---- $filter / $top / $select ----


@pytest.fixture
def loaded(client):
    rows = [
        {"CardCode": "C1", "CardName": "Cho Ray Hospital", "FederalTaxID": "0301234567"},
        {"CardCode": "C2", "CardName": "Siriraj Hospital", "FederalTaxID": "0105556123456"},
        {"CardCode": "C3", "CardName": "Tan Tock Seng", "FederalTaxID": "201912345K"},
    ]
    for row in rows:
        assert client.post(f"{BASE}/BusinessPartners", json=row).status_code == 201
    return client


def codes(resp):
    assert resp.status_code == 200, resp.text
    return [r["CardCode"] for r in resp.json()["value"]]


def test_filter_eq(loaded):
    r = loaded.get(f"{BASE}/BusinessPartners", params={"$filter": "FederalTaxID eq '0301234567'"})
    assert codes(r) == ["C1"]
    r = loaded.get(f"{BASE}/BusinessPartners", params={"$filter": "CardCode eq 'C3'"})
    assert codes(r) == ["C3"]
    r = loaded.get(f"{BASE}/BusinessPartners", params={"$filter": "CardName eq 'cho ray hospital'"})
    assert codes(r) == []  # eq is exact


def test_filter_contains(loaded):
    r = loaded.get(f"{BASE}/BusinessPartners", params={"$filter": "contains(CardName,'hospital')"})
    assert codes(r) == ["C1", "C2"]
    r = loaded.get(f"{BASE}/BusinessPartners", params={"$filter": "contains(FederalTaxID, '0105')"})
    assert codes(r) == ["C2"]


def test_filter_and_top_select(loaded):
    flt = "contains(CardName,'Hospital') and contains(FederalTaxID,'01')"
    assert codes(loaded.get(f"{BASE}/BusinessPartners", params={"$filter": flt})) == ["C1", "C2"]
    r = loaded.get(f"{BASE}/BusinessPartners", params={"$top": "1", "$select": "CardCode,CardName"})
    assert r.json()["value"] == [{"CardCode": "C1", "CardName": "Cho Ray Hospital"}]


def test_filter_invalid(loaded):
    r = loaded.get(f"{BASE}/BusinessPartners", params={"$filter": "CardName gt 'a'"})
    assert_b1_error(r, 400, -10, "$filter")
    r = loaded.get(f"{BASE}/BusinessPartners", params={"$filter": "Nope eq 'a'"})
    assert_b1_error(r, 400, -10, "Nope")


def test_unknown_route_is_b1_shape(client):
    r = client.get(f"{BASE}/Nothing")
    assert r.status_code == 404
    assert "error" in r.json()

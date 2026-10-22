"""The analytics endpoints against the real ds functions and the committed precomputed results
(no monkeypatching), so a path or shape mismatch between the API and ds shows up here."""

# ruff: noqa: F811  (the `client` fixture from test_workflow_api is used by name)
import pytest

from tests.test_workflow_api import client  # noqa: F401  (seeded API on a temp database)

OWNS_APP_DB = True  # the `client` fixture seeds its own temp database (see tests/conftest.py)
HEADERS = {"X-Acting-User": "priya"}


@pytest.mark.parametrize(
    "url",
    [
        "/analytics/regional?view=before",
        "/analytics/regional?view=after&country=VN",
        "/analytics/merge-impact",
        "/analytics/forecast",
        "/analytics/ops-impact",
    ],
)
def test_endpoint_serves_real_numbers(client, url: str) -> None:
    r = client.get(url, headers=HEADERS)
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("scenario", ["seasonal_trend", "flat_noisy", "intermittent"])
@pytest.mark.parametrize("data", ["clean", "dirty"])
def test_every_precomputed_forecast_run_is_served(client, scenario: str, data: str) -> None:
    r = client.get(f"/analytics/forecast/{scenario}?data={data}", headers=HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["scenario"] == scenario and r.json()["data"] == data


def test_summary_lists_all_six_runs(client) -> None:
    runs = client.get("/analytics/forecast", headers=HEADERS).json()["runs"]
    assert {(x["scenario"], x["data"]) for x in runs} == {
        (s, d) for s in ("seasonal_trend", "flat_noisy", "intermittent") for d in ("clean", "dirty")
    }


def test_after_merge_has_fewer_customers_and_lost_alerts(client) -> None:
    m = client.get("/analytics/merge-impact", headers=HEADERS).json()
    assert m["customers_after"] < m["customers_before"]
    assert m["lost_after"] < m["lost_before"]

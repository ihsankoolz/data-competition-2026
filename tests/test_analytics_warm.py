"""The regional view is computed once at API start, so the first demo visit is fast."""

from services.api.routers import analytics


def test_warm_fills_the_regional_cache():
    from ds.analytics import regional

    regional._load.cache_clear()
    analytics.warm()
    assert regional._load.cache_info().currsize >= 1


def test_warm_never_raises_when_the_data_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("ANALYTICS_DATA_DIR", str(tmp_path / "missing"))
    analytics.warm()  # logged, not raised: the endpoints still answer 503 on demand

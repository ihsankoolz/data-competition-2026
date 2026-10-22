"""Safety net: no test may touch the developer's real `data/app.db`.

Every test starts with APP_DB_PATH pointing at a file that does not exist, so code that looks for
"the default database" (the clock's save, the SLA sweep) finds nothing unless the test makes one.
A module that builds its own app database (module-scoped, set `OWNS_APP_DB = True`) opts out.
"""

import pytest

from services.api.db.session import dispose_default


@pytest.fixture(autouse=True)
def _isolated_default_db(request, tmp_path_factory, monkeypatch):
    if getattr(request.module, "OWNS_APP_DB", False):
        yield
        return
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path_factory.mktemp("nodb") / "none.db"))
    dispose_default()
    yield
    dispose_default()

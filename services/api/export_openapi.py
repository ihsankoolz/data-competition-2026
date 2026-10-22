"""Write the API's OpenAPI spec to a file for openapi-typescript (no server needed)."""

import json
import sys
from pathlib import Path

from services.api.main import app

out = Path(sys.argv[1] if len(sys.argv) > 1 else "apps/web/lib/api/openapi.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
print(f"wrote {out}")

"""Prints the OpenAPI document the web client is generated from (no server needed).
Run: uv run python -m apps.api.openapi > apps/web/openapi.json"""

import json
import os

os.environ.setdefault("SESSION_SECRET", "openapi-export-only")

from apps.api.main import app

print(json.dumps(app.openapi(), indent=1, sort_keys=True))

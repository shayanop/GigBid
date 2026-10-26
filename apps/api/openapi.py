"""Prints the OpenAPI document the web client is generated from (no server needed).
Run: uv run python -m apps.api.openapi > apps/web/openapi.json"""

import json
import os

from apps.api.main import create_app

os.environ.setdefault("SESSION_SECRET", "openapi-export-only")  # only the schema is read

print(json.dumps(create_app().openapi(), indent=1, sort_keys=True))

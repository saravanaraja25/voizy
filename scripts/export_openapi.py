"""Write the API's OpenAPI schema to a file (no server or database needed).

uv run python scripts/export_openapi.py apps/dashboard/openapi.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from voizy_api.app import create_app


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
    out.write_text(json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

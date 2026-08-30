"""Fail when the checked-in OpenAPI document is not generated from the app."""

from __future__ import annotations

import json
from pathlib import Path

from app.main import app


def main() -> int:
    tracked = Path(__file__).resolve().parents[1] / "openapi.json"
    current = json.loads(tracked.read_text(encoding="utf-8"))
    if current != app.openapi():
        print("OpenAPI contract is stale; run: make openapi")
        return 1
    print("OpenAPI contract is current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

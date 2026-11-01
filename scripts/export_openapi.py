"""Write the OpenAPI document of the actual application to docs/openapi/openapi-v1.json.

    python -m scripts.export_openapi           # write
    python -m scripts.export_openapi --check   # exit 1 if the checked-in file is stale

Generated from the routes, never hand-edited; `tests/unit/test_openapi_export.py` fails when the
export and the application disagree.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "docs/openapi/openapi-v1.json"


def render() -> str:
    from app.core.config import get_settings
    from app.main import create_app

    settings = get_settings().model_copy(update={"api_docs_enabled": True})
    import app.main as main

    original = main.get_settings
    main.get_settings = lambda: settings
    try:
        spec = create_app().openapi()
    finally:
        main.get_settings = original
    return json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.export_openapi")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    text = render()
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        print("up to date" if current == text else "stale: run python -m scripts.export_openapi")
        return 0 if current == text else 1
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(text, encoding="utf-8")
    print(f"wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

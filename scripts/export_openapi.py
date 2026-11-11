"""Write the live OpenAPI schema to docs/openapi.json (needs the requirements installed).  python -m scripts.export_openapi"""
import json
from pathlib import Path

from backend.main import create_app

if __name__ == "__main__":
    out = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"
    out.write_text(json.dumps(create_app().openapi(), indent=2), encoding="utf-8")
    print("wrote", out)

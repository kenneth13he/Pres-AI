"""Write spec/contracts.schema.json from spec/contracts.py.

Why: the frontend has no Python; its mock fixtures are checked against this
file in `make check` so a contract change breaks loudly on both sides.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spec.contracts import SCHEMA_MODELS  # noqa: E402

OUT = ROOT / "spec" / "contracts.schema.json"


def build() -> dict:
    defs: dict = {}
    for model in SCHEMA_MODELS:
        schema = model.model_json_schema(ref_template="#/$defs/{model}")
        defs.update(schema.pop("$defs", {}))
        defs[model.__name__] = schema
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$defs": defs}


def main(check: bool = False) -> int:
    text = json.dumps(build(), indent=2, sort_keys=True) + "\n"
    if check:
        if not OUT.exists() or OUT.read_text() != text:
            print(f"{OUT} is stale: run `make schema`", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(check="--check" in sys.argv))

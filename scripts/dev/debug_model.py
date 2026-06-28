#!/usr/bin/env python3
"""Extrai e exibe o schema bruto de um arquivo .pbit para debug."""

import json
import sys
import zipfile
from pathlib import Path

DEFAULT_PBIT = Path(__file__).parent.parent / "data" / "BI OCEANPACT - ILSCARGO.pbit"


def extract_schema(pbit_path: str | Path) -> None:
    with zipfile.ZipFile(pbit_path, "r") as zf:
        raw = zf.read("DataModelSchema")
        for enc in ("utf-16-le", "utf-8", "utf-16", "latin-1"):
            try:
                text = raw.decode(enc)
                if text.startswith("\ufeff"):
                    text = text[1:]
                schema = json.loads(text)
                tables = schema.get("model", {}).get("tables", [])
                for t in tables:
                    tname = t.get("name", "?")
                    parts = t.get("partitions", [])
                    for p in parts:
                        src = p.get("source", {})
                        expr = src.get("expression")
                        if expr:
                            print(f"=== TABLE: {tname} ===")
                            if isinstance(expr, list):
                                for line in expr[:8]:
                                    print(line)
                            else:
                                print(str(expr)[:400])
                            print()
                break
            except Exception:
                continue


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PBIT
    extract_schema(path)

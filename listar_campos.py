#!/usr/bin/env py
"""Lista todos os campos extraídos das faturas, agrupados por categoria."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from services.extrator import listar_campos_disponiveis

if __name__ == "__main__":
    campos = listar_campos_disponiveis()
    total = sum(len(v) for v in campos.values())
    print(f"Total de campos: {total}\n")
    for grupo, nomes in campos.items():
        print(f"## {grupo} ({len(nomes)})")
        for nome in nomes:
            print(f"  - {nome}")
        print()
    print(json.dumps(campos, indent=2, ensure_ascii=False))

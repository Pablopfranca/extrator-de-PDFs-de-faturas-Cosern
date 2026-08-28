#!/usr/bin/env py
"""
Ingestão de PDF(s) → CSV.

Uso:
    py ingest.py fatura.pdf
    py ingest.py fatura1.pdf fatura2.pdf
    py ingest.py --csv data/minhas_faturas.csv fatura.pdf
    py ingest.py --overwrite fatura.pdf
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.csv_store import DEFAULT_CSV_PATH, extrair_e_salvar_csv


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extrai faturas de PDF(s) e salva em CSV.",
    )
    parser.add_argument(
        "pdfs",
        nargs="+",
        type=Path,
        help="Caminho(s) para arquivo(s) PDF.",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV_PATH,
        help=f"Arquivo CSV de destino (padrão: {DEFAULT_CSV_PATH}).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Recria o CSV com as faturas desta execução (não faz append).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Log detalhado (DEBUG).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s | %(name)s | %(message)s",
    )

    modo = "overwrite" if args.overwrite else "append"
    total_extraidas = 0
    total_gravadas = 0

    for pdf in args.pdfs:
        if not pdf.is_file():
            logging.error("Arquivo não encontrado: %s", pdf)
            return 1

        resumo = extrair_e_salvar_csv(pdf, caminho=args.csv, modo=modo)
        total_extraidas += resumo["faturas_extraidas"]
        total_gravadas += resumo["faturas_gravadas"]

        print(
            f"{pdf.name}: {resumo['faturas_extraidas']} extraída(s), "
            f"{resumo['faturas_gravadas']} gravada(s)"
        )

        # Após overwrite no primeiro PDF, demais entram em append
        if modo == "overwrite":
            modo = "append"

    print(f"\nCSV: {args.csv.resolve()}")
    print(f"Total: {total_extraidas} extraída(s), {total_gravadas} gravada(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env py
"""
Ingestão de PDF(s) de fatura → JSON (padrão) e/ou CSV.

O JSON sai no formato do Módulo 1 (API Cosern), um arquivo por instalação,
para que o Módulo 2 leia as duas origens com o mesmo parser.

Uso:
    py ingest.py fatura.pdf
    py ingest.py fatura1.pdf fatura2.pdf
    py ingest.py --pasta data
    py ingest.py --formato csv fatura.pdf
    py ingest.py --formato ambos fatura.pdf
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
from models.json_store import DEFAULT_JSON_DIR, extrair_e_salvar_json

logger = logging.getLogger("modulo1b.ingest")


def _coletar_pdfs(caminhos: list[Path], pasta: Path | None) -> list[Path]:
    encontrados: list[Path] = []

    if pasta is not None:
        if not pasta.is_dir():
            raise NotADirectoryError(f"Pasta não encontrada: {pasta}")
        encontrados.extend(sorted(p for p in pasta.rglob("*.pdf") if p.is_file()))

    for caminho in caminhos:
        if caminho.is_dir():
            encontrados.extend(sorted(p for p in caminho.rglob("*.pdf") if p.is_file()))
        else:
            encontrados.append(caminho)

    vistos: set[Path] = set()
    unicos: list[Path] = []
    for pdf in encontrados:
        resolvido = pdf.resolve()
        if resolvido in vistos:
            continue
        vistos.add(resolvido)
        unicos.append(pdf)
    return unicos


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extrai faturas de PDF(s) e salva em JSON (padrão) e/ou CSV.",
    )
    parser.add_argument(
        "pdfs",
        nargs="*",
        type=Path,
        default=[],
        help="Arquivo(s) PDF ou pasta(s).",
    )
    parser.add_argument(
        "--pasta",
        type=Path,
        default=None,
        help="Pasta varrida recursivamente em busca de PDFs.",
    )
    parser.add_argument(
        "--formato",
        choices=("json", "csv", "ambos"),
        default="json",
        help="Destino da extração (padrão: json).",
    )
    parser.add_argument(
        "--json-dir",
        type=Path,
        default=DEFAULT_JSON_DIR,
        help=f"Pasta dos JSON por instalação (padrão: {DEFAULT_JSON_DIR}).",
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
        help="Recria a saída desta execução em vez de acumular.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Log detalhado (DEBUG).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s | %(name)s | %(message)s",
    )

    if not args.pdfs and args.pasta is None:
        logger.error("Informe ao menos um PDF ou use --pasta.")
        return 1

    try:
        pdfs = _coletar_pdfs(list(args.pdfs), args.pasta)
    except NotADirectoryError as erro:
        logger.error("%s", erro)
        return 1

    if not pdfs:
        logger.error("Nenhum PDF encontrado.")
        return 1

    faltantes = [p for p in pdfs if not p.is_file()]
    if faltantes:
        for pdf in faltantes:
            logger.error("Arquivo não encontrado: %s", pdf)
        return 1

    gera_json = args.formato in {"json", "ambos"}
    gera_csv = args.formato in {"csv", "ambos"}

    modo_json = "overwrite" if args.overwrite else "merge"
    modo_csv = "overwrite" if args.overwrite else "append"

    total_extraidas = 0
    total_csv = 0
    ultimo_json: dict | None = None

    for pdf in pdfs:
        if gera_json:
            resumo = extrair_e_salvar_json(pdf, pasta=args.json_dir, modo=modo_json)
            ultimo_json = resumo
            total_extraidas += resumo["faturas_extraidas"]
            print(
                f"{pdf.name}: {resumo['faturas_extraidas']} fatura(s) em "
                f"{resumo['instalacoes']} instalacao(oes)"
            )
            # Só o primeiro PDF pode recriar a pasta; os demais acumulam.
            modo_json = "merge"

        if gera_csv:
            resumo_csv = extrair_e_salvar_csv(pdf, caminho=args.csv, modo=modo_csv)
            total_csv += resumo_csv["faturas_gravadas"]
            if not gera_json:
                total_extraidas += resumo_csv["faturas_extraidas"]
                print(
                    f"{pdf.name}: {resumo_csv['faturas_extraidas']} extraída(s), "
                    f"{resumo_csv['faturas_gravadas']} gravada(s)"
                )
            modo_csv = "append"

    print()
    print(f"PDFs processados: {len(pdfs)}")
    print(f"Faturas extraídas: {total_extraidas}")
    if gera_json and ultimo_json:
        print(f"JSON: {ultimo_json['pasta']}")
        print(f"  competências no disco: {ultimo_json['competencias_no_disco']}")
    if gera_csv:
        print(f"CSV: {Path(args.csv).resolve()} ({total_csv} gravada(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

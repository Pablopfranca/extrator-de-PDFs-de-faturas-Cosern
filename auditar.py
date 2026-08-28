#!/usr/bin/env py
"""
Auditoria em lote de PDFs — detecta conteúdo não mapeado no extrator.

Foco: linhas de item, grandezas de medidor, rótulos e termos peculiares
presentes no PDF mas ainda sem campo correspondente no sistema.

Uso:
    py auditar.py fatura.pdf
    py auditar.py --pasta "W:\\Contas\\2026"
    py auditar.py --pasta "W:\\Contas" --copiar-falhas --somente-problemas
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.auditor import (
    DEFAULT_FALHAS_DIR,
    DEFAULT_RELATORIO,
    auditar_pasta,
    auditar_pdf,
    copiar_pdfs_com_falha,
    resumir_auditoria,
    salvar_relatorio,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audita PDFs de fatura e detecta conteúdo presente no documento "
            "mas ainda não mapeado pelo extrator."
        ),
    )
    parser.add_argument(
        "pdfs",
        nargs="*",
        type=Path,
        help="PDF(s) individuais (use --pasta para varrer diretório).",
    )
    parser.add_argument(
        "--pasta",
        type=Path,
        help="Pasta com PDFs (busca recursiva por *.pdf).",
    )
    parser.add_argument(
        "--relatorio",
        type=Path,
        default=DEFAULT_RELATORIO,
        help=f"CSV de saída (padrão: {DEFAULT_RELATORIO}).",
    )
    parser.add_argument(
        "--copiar-falhas",
        action="store_true",
        help=f"Copia PDFs problemáticos para {DEFAULT_FALHAS_DIR}.",
    )
    parser.add_argument(
        "--destino-falhas",
        type=Path,
        default=DEFAULT_FALHAS_DIR,
        help="Pasta destino dos PDFs com falha.",
    )
    parser.add_argument(
        "--somente-problemas",
        action="store_true",
        help="Relatório inclui apenas faturas com conteúdo não mapeado.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Log detalhado.",
    )
    args = parser.parse_args()

    if not args.pasta and not args.pdfs:
        parser.error("Informe PDF(s) ou --pasta.")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s | %(name)s | %(message)s",
    )

    linhas = []
    pasta_origem = args.pasta.resolve() if args.pasta else None

    if args.pasta:
        linhas.extend(auditar_pasta(args.pasta))

    for pdf in args.pdfs:
        if not pdf.is_file():
            logging.error("Arquivo não encontrado: %s", pdf)
            return 1
        linhas.extend(auditar_pdf(pdf))

    relatorio = salvar_relatorio(
        linhas,
        caminho=args.relatorio,
        apenas_problemas=args.somente_problemas,
    )

    copiados: list[Path] = []
    if args.copiar_falhas:
        copiados = copiar_pdfs_com_falha(
            linhas,
            pasta_origem=pasta_origem,
            destino=args.destino_falhas,
        )

    resumo = resumir_auditoria(linhas)

    print(f"\nRelatório: {relatorio}")
    print(f"Faturas auditadas: {resumo['faturas_auditadas']}")
    print(f"Com conteúdo não mapeado: {resumo['faturas_com_conteudo_nao_mapeado']}")
    print(f"PDFs que requerem atenção: {resumo['pdfs_com_atencao']}")

    if copiados:
        print(f"\nPDFs copiados para {args.destino_falhas.resolve()}:")
        for caminho in copiados:
            print(f"  - {caminho.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

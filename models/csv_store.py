"""
Módulo 2 — Persistência em CSV das faturas extraídas.

Suporta colunas fixas + colunas dinâmicas (itens novos descobertos),
com expansão automática do cabeçalho quando novas colunas são registradas.
"""

from __future__ import annotations

import csv
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from services.colunas_dinamicas import colunas_csv_completas
from services.extrator import PdfSource, extrair_faturas
from services.fuso_horario import agora_fortaleza

logger = logging.getLogger(__name__)

ModoPersistencia = Literal["append", "overwrite"]

DEFAULT_CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "faturas.csv"

CHAVE_UNICA = ("codigo_instalacao", "mes_referencia")

# Campos numéricos longos que o Excel converte para notação científica ao abrir CSV
_CAMPOS_TEXTO_EXCEL = frozenset(
    {"chave_acesso", "numero_uc", "codigo_instalacao", "codigo_cliente", "doc_pagamento"}
)


def _formatar_celula_excel(coluna: str, valor: str) -> str:
    if not valor or coluna not in _CAMPOS_TEXTO_EXCEL:
        return valor
    if not re.fullmatch(r"\d+", valor):
        return valor
    return f'="{valor}"'


def _garantir_diretorio(caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)


def _chave_fatura(registro: dict[str, Any]) -> tuple[str, str]:
    return (
        str(registro.get("codigo_instalacao", "")).strip(),
        str(registro.get("mes_referencia", "")).strip(),
    )


def _normalizar_registro(
    fatura: dict[str, Any],
    colunas: tuple[str, ...],
    data_ingestao: datetime | None = None,
) -> dict[str, str]:
    momento = data_ingestao or agora_fortaleza()
    registro = {
        **fatura,
        "data_ingestao": momento.isoformat(timespec="seconds"),
    }
    return {
        coluna: _formatar_celula_excel(coluna, str(registro.get(coluna, "")))
        for coluna in colunas
    }


def _expandir_csv_se_necessario(arquivo: Path, colunas: tuple[str, ...]) -> None:
    """Reescreve o CSV quando o registro ganhou colunas dinâmicas novas."""
    if not arquivo.is_file():
        return

    with arquivo.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        existentes = tuple(reader.fieldnames or ())
        linhas = [dict(linha) for linha in reader]

    if existentes == colunas:
        return

    faltantes = [c for c in colunas if c not in existentes]
    if not faltantes:
        return

    logger.info(
        "Expandindo CSV com %d coluna(s) nova(s): %s",
        len(faltantes),
        ", ".join(faltantes),
    )

    with arquivo.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=colunas, extrasaction="ignore")
        writer.writeheader()
        for linha in linhas:
            writer.writerow({coluna: linha.get(coluna, "") for coluna in colunas})


def carregar_faturas_csv(caminho: Path | str = DEFAULT_CSV_PATH) -> list[dict[str, str]]:
    arquivo = Path(caminho)
    if not arquivo.is_file():
        return []

    with arquivo.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(linha) for linha in reader]


def _carregar_chaves_existentes(arquivo: Path) -> set[tuple[str, str]]:
    if not arquivo.is_file():
        return set()
    return {_chave_fatura(linha) for linha in carregar_faturas_csv(arquivo)}


def salvar_faturas_csv(
    faturas: list[dict[str, Any]],
    caminho: Path | str = DEFAULT_CSV_PATH,
    modo: ModoPersistencia = "append",
) -> int:
    arquivo = Path(caminho)
    _garantir_diretorio(arquivo)

    if not faturas:
        logger.info("Nenhuma fatura para persistir em %s", arquivo)
        return 0

    colunas = colunas_csv_completas()
    _expandir_csv_se_necessario(arquivo, colunas)
    data_ingestao = agora_fortaleza()

    if modo == "overwrite":
        linhas = [_normalizar_registro(f, colunas, data_ingestao) for f in faturas]
        chaves_vistas: set[tuple[str, str]] = set()
        linhas_unicas: list[dict[str, str]] = []
        for linha in linhas:
            chave = _chave_fatura(linha)
            if chave in chaves_vistas:
                continue
            chaves_vistas.add(chave)
            linhas_unicas.append(linha)

        with arquivo.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=colunas, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(linhas_unicas)

        logger.info(
            "CSV recriado — %d fatura(s) gravada(s) em %s",
            len(linhas_unicas),
            arquivo,
        )
        return len(linhas_unicas)

    chaves_existentes = _carregar_chaves_existentes(arquivo)
    novas_linhas: list[dict[str, str]] = []

    for fatura in faturas:
        chave = _chave_fatura(fatura)
        if chave in chaves_existentes:
            logger.debug(
                "Fatura duplicada ignorada — instalação=%s, referência=%s",
                chave[0],
                chave[1],
            )
            continue
        novas_linhas.append(_normalizar_registro(fatura, colunas, data_ingestao))
        chaves_existentes.add(chave)

    if not novas_linhas:
        logger.info("Nenhuma fatura nova para adicionar em %s", arquivo)
        return 0

    arquivo_existe = arquivo.is_file()
    with arquivo.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=colunas, extrasaction="ignore")
        if not arquivo_existe:
            writer.writeheader()
        writer.writerows(novas_linhas)

    logger.info(
        "CSV atualizado — %d fatura(s) nova(s) adicionada(s) em %s",
        len(novas_linhas),
        arquivo,
    )
    return len(novas_linhas)


def extrair_e_salvar_csv(
    fonte: PdfSource,
    caminho: Path | str = DEFAULT_CSV_PATH,
    modo: ModoPersistencia = "append",
) -> dict[str, Any]:
    faturas = extrair_faturas(fonte)
    gravadas = salvar_faturas_csv(faturas, caminho=caminho, modo=modo)

    resumo = {
        "arquivo_origem": str(fonte) if isinstance(fonte, (str, Path)) else "<stream>",
        "caminho_csv": str(Path(caminho).resolve()),
        "faturas_extraidas": len(faturas),
        "faturas_gravadas": gravadas,
        "faturas_ignoradas_duplicata": len(faturas) - gravadas
        if modo == "append"
        else len(faturas) - gravadas,
    }
    logger.info("Ingestão concluída: %s", resumo)
    return resumo

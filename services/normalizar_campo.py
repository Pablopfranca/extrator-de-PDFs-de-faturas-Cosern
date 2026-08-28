"""
Normalização de descrições de itens de fatura para nomes de coluna.

Multas, juros e encargos de mora costumam trazer o número da NF/nota de
origem após o rótulo; removemos esse sufixo para não criar uma coluna por
fatura, mas preservamos o número para auditoria.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CAMPOS_COM_NUMERO_NOTA = re.compile(
    r"\b(multa|juros|mora|acres|acrésc|atualiz|corre[cç][ãa]o)\b",
    re.IGNORECASE,
)

# Número de nota ao final: "Multa 1234567890", "Juros NF 123456789012", "Multa-NF 123456789"
_RE_MULTA_JUROS_COM_NF = re.compile(
    r"^(Multa|Juros)(?:-NF)?\s+(?:NF\s*)?(\d{5,})\s*$",
    re.IGNORECASE,
)

_RE_SUFIXO_NUMERO_NOTA = re.compile(
    r"\s+(?:"
    r"(?:NF|N[°º]?\s*F\.?|Nota(?:\s+Fiscal)?)\s*)?"
    r"(\d{5,})"
    r"\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DescricaoItem:
    descricao_bruta: str
    descricao: str
    numero_nota_fiscal: str | None


def descricao_pode_ter_nota_fiscal(descricao: str) -> bool:
    return bool(_CAMPOS_COM_NUMERO_NOTA.search(descricao))


def extrair_numero_nota_fiscal(descricao: str) -> str | None:
    """Extrai o número de NF/nota do sufixo da descrição (multas, juros, etc.)."""
    desc = re.sub(r"\s+", " ", descricao.strip())
    match_mj = _RE_MULTA_JUROS_COM_NF.match(desc)
    if match_mj:
        return match_mj.group(2)

    if not descricao_pode_ter_nota_fiscal(desc):
        return None

    match = _RE_SUFIXO_NUMERO_NOTA.search(desc)
    if not match:
        return None
    return match.group(1)


def normalizar_descricao_item(descricao: str) -> str:
    """
    Retorna descrição canônica para coluna dinâmica e deduplicação.

    Em multas/juros/mora, remove sufixos numéricos de nota fiscal.
    Demais itens mantêm o texto original (apenas espaços colapsados).
    """
    desc = re.sub(r"\s+", " ", descricao.strip())
    if not desc:
        return desc

    if re.fullmatch(r"(?i)multa-nf", desc):
        return "Multa"
    if re.fullmatch(r"(?i)juros-nf", desc):
        return "Juros"

    match_mj = _RE_MULTA_JUROS_COM_NF.match(desc)
    if match_mj:
        return match_mj.group(1)

    if not descricao_pode_ter_nota_fiscal(desc):
        return desc

    anterior = None
    while anterior != desc:
        anterior = desc
        desc = _RE_SUFIXO_NUMERO_NOTA.sub("", desc).strip()

    return desc


def parsear_descricao_item(descricao: str) -> DescricaoItem:
    """Separa descrição bruta, canônica e número de NF para auditoria."""
    bruta = re.sub(r"\s+", " ", descricao.strip())
    return DescricaoItem(
        descricao_bruta=bruta,
        descricao=normalizar_descricao_item(bruta),
        numero_nota_fiscal=extrair_numero_nota_fiscal(bruta),
    )

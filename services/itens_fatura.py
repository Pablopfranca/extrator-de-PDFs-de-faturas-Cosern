"""
Inventário de linhas em ITENS DA FATURA (entre o cabeçalho da tabela e TOTAL).

Usado pelo extrator (captura automática de itens novos) e pela auditoria.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from services.catalogo_fatura import item_deve_ignorar, item_e_conhecido
from services.normalizar_campo import normalizar_descricao_item, parsear_descricao_item
from services.numeros import parse_numero_brasileiro

_RE_BLOCO_ITENS = re.compile(
    r"ITENS DA FATURA(.*?)(?:CONSUMO FATURADO|TOTAL A PAGAR|$)",
    re.IGNORECASE | re.DOTALL,
)

_RE_ITEM_COM_UNIDADE = re.compile(
    r"^(?P<desc>.+?)\s+(?P<unidade>kW|kWh|kVAr|kVARh)\s+"
    r"(?P<quant>[\d.,]+)\s+(?:[\d.,]+\s+)?(?P<valor>[\d.,]+-?)",
    re.IGNORECASE,
)

_RE_ITEM_ENCARGO = re.compile(
    r"^(?P<desc>(?:Ilum\.|Acr[eé]s\.|TRIBF)[^\n]{3,80}?)\s+(?P<valor>[\d.,]+-?)",
    re.IGNORECASE,
)

# Cobranças sem unidade explícita (ex.: multas, devoluções) antes do TOTAL
_RE_ITEM_VALOR_FINAL = re.compile(
    r"^(?P<desc>[A-ZÁÉÍÓÚÃÕÂÊÎÔÛ][A-Za-zÁÉÍÓÚÃÕÂÊÎÔÛ0-9\s.\-()%]{2,80}?)"
    r"\s+(?P<valor>\d{1,3}(?:\.\d{3})*,\d{2}-?)\s*$",
)


@dataclass
class LinhaItem:
    descricao: str
    unidade: str
    quantidade: float | None
    valor: float | None
    linha_bruta: str
    descricao_bruta: str = ""
    numero_nota_fiscal: str | None = None


def _extrair_bloco_itens(texto: str) -> str:
    match = _RE_BLOCO_ITENS.search(texto)
    return match.group(1) if match else ""


def _normalizar_descricao(desc: str) -> str:
    return normalizar_descricao_item(desc)


def _montar_item(
    descricao_bruta: str,
    unidade: str,
    quantidade: float | None,
    valor: float | None,
    linha_bruta: str,
) -> LinhaItem:
    parsed = parsear_descricao_item(descricao_bruta)
    return LinhaItem(
        descricao=parsed.descricao,
        unidade=unidade,
        quantidade=quantidade,
        valor=valor,
        linha_bruta=linha_bruta,
        descricao_bruta=parsed.descricao_bruta,
        numero_nota_fiscal=parsed.numero_nota_fiscal,
    )


def listar_linhas_itens(texto: str) -> list[LinhaItem]:
    """Lista todas as linhas de cobrança reconhecíveis antes do TOTAL."""
    bloco = _extrair_bloco_itens(texto)
    if not bloco:
        return []

    itens: list[LinhaItem] = []
    vistos: set[str] = set()

    for linha in bloco.split("\n"):
        linha = linha.strip()
        if not linha or item_deve_ignorar(linha):
            continue

        chave = linha.lower()
        if chave in vistos:
            continue

        match = _RE_ITEM_COM_UNIDADE.match(linha)
        if match:
            vistos.add(chave)
            itens.append(
                _montar_item(
                    match.group("desc"),
                    match.group("unidade"),
                    parse_numero_brasileiro(match.group("quant")),
                    parse_numero_brasileiro(match.group("valor")),
                    linha,
                )
            )
            continue

        match_encargo = _RE_ITEM_ENCARGO.match(linha)
        if match_encargo:
            vistos.add(chave)
            itens.append(
                _montar_item(
                    match_encargo.group("desc"),
                    "",
                    None,
                    parse_numero_brasileiro(match_encargo.group("valor")),
                    linha,
                )
            )
            continue

        match_simples = _RE_ITEM_VALOR_FINAL.match(linha)
        if match_simples:
            parsed = parsear_descricao_item(match_simples.group("desc"))
            if item_e_conhecido(parsed.descricao):
                continue
            vistos.add(chave)
            itens.append(
                LinhaItem(
                    descricao=parsed.descricao,
                    unidade="",
                    quantidade=None,
                    valor=parse_numero_brasileiro(match_simples.group("valor")),
                    linha_bruta=linha,
                    descricao_bruta=parsed.descricao_bruta,
                    numero_nota_fiscal=parsed.numero_nota_fiscal,
                )
            )

    return itens


def extrair_itens_nao_catalogados(texto: str) -> list[dict[str, str | float | None]]:
    """
    Retorna itens presentes no PDF mas fora do catálogo mapeado do extrator.
    """
    descobertos: list[dict[str, str | float | None]] = []
    vistos: set[str] = set()

    for item in listar_linhas_itens(texto):
        if item_e_conhecido(item.descricao):
            continue
        chave = item.descricao.lower()
        if chave in vistos:
            continue
        vistos.add(chave)
        descobertos.append(
            {
                "descricao": item.descricao,
                "descricao_bruta": item.descricao_bruta or item.descricao,
                "unidade": item.unidade,
                "quantidade": item.quantidade,
                "valor": item.valor,
                "numero_nota_fiscal": item.numero_nota_fiscal or "",
            }
        )

    return descobertos

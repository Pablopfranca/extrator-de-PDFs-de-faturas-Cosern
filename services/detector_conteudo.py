"""
Detecção de conteúdo presente no PDF mas ainda não mapeado pelo extrator.

Estratégia híbrida:
1. Inventariar linhas de ITENS DA FATURA e linhas de MEDIDOR.
2. Comparar com catálogo de padrões conhecidos.
3. Buscar termos de peculiaridade tarifária/local.
4. Conferir soma dos itens vs. total declarado na fatura.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from services.catalogo_fatura import (
    buscar_palavras_peculiares,
    grandeza_e_conhecida,
    item_e_conhecido,
    rotulo_e_conhecido,
)
from services.itens_fatura import LinhaItem, listar_linhas_itens
from services.numeros import parse_numero_brasileiro

_RE_LINHA_MEDIDOR = re.compile(
    r"^(\d{8,12})\s+(.+?)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s*$",
    re.MULTILINE,
)

_RE_ROTULO = re.compile(
    r"(?:^|\n)([A-ZÁÉÍÓÚÃÕÂÊÎÔÛ][A-ZÁÉÍÓÚÃÕÂÊÎÔÛ0-9\s./\-]{2,40}?)\s*:",
    re.MULTILINE,
)

_PECULIAR_JA_MAPEADO = re.compile(
    r"reativa\s+excedente|ultrapassagem|compens",
    re.IGNORECASE,
)


@dataclass
class ResultadoDeteccao:
    itens_nao_mapeados: list[str] = field(default_factory=list)
    medidor_nao_mapeado: list[str] = field(default_factory=list)
    rotulos_nao_mapeados: list[str] = field(default_factory=list)
    palavras_peculiares: list[str] = field(default_factory=list)
    divergencia_total_itens: float | None = None
    soma_itens_detectados: float | None = None

    @property
    def tem_conteudo_nao_mapeado(self) -> bool:
        if self.itens_nao_mapeados or self.medidor_nao_mapeado or self.rotulos_nao_mapeados:
            return True
        if self.palavras_peculiares:
            return True
        if self.divergencia_total_itens is not None and abs(self.divergencia_total_itens) > 1.0:
            return True
        return False

    def resumo_motivos(self) -> str:
        partes: list[str] = []
        if self.itens_nao_mapeados:
            partes.append(f"itens({len(self.itens_nao_mapeados)})")
        if self.medidor_nao_mapeado:
            partes.append(f"medidor({len(self.medidor_nao_mapeado)})")
        if self.rotulos_nao_mapeados:
            partes.append(f"rotulos({len(self.rotulos_nao_mapeados)})")
        if self.palavras_peculiares:
            partes.append(f"peculiar({len(self.palavras_peculiares)})")
        if self.divergencia_total_itens is not None and abs(self.divergencia_total_itens) > 1.0:
            partes.append(f"divergencia_total(R${self.divergencia_total_itens:.2f})")
        return "; ".join(partes) if partes else "ok"


def _normalizar_descricao(desc: str) -> str:
    return re.sub(r"\s+", " ", desc.strip())


def listar_grandezas_medidor(texto: str) -> list[str]:
    grandezas: list[str] = []
    for match in _RE_LINHA_MEDIDOR.finditer(texto):
        tipo = _normalizar_descricao(match.group(2))
        if tipo and tipo not in grandezas:
            grandezas.append(tipo)
    return grandezas


def listar_rotulos_desconhecidos(texto: str) -> list[str]:
    rotulos: list[str] = []
    for match in _RE_ROTULO.finditer(texto):
        rotulo = match.group(1).strip()
        if len(rotulo) < 3:
            continue
        if rotulo_e_conhecido(rotulo):
            continue
        if rotulo not in rotulos:
            rotulos.append(rotulo)
    return rotulos


def _filtrar_peculiares_relevantes(texto: str, fatura: dict[str, Any]) -> list[str]:
    candidatos = buscar_palavras_peculiares(texto)
    if not candidatos:
        return []

    texto_lower = texto.lower()
    relevantes: list[str] = []

    for termo in candidatos:
        termo_lower = termo.lower()
        if termo_lower in {"reativa excedente", "ultrapassagem"}:
            if _PECULIAR_JA_MAPEADO.search(texto) and (
                fatura.get("consumo_reat_excedente_kvarh")
                or fatura.get("demanda_ultrapassagem_kw")
                or fatura.get("demanda_ultrapassagem_np_kw")
            ):
                continue
        if "compens" in termo_lower:
            if "compens" not in texto_lower:
                continue
        relevantes.append(termo)

    return relevantes


def detectar_conteudo_nao_mapeado(
    texto: str,
    fatura: dict[str, Any] | None = None,
) -> ResultadoDeteccao:
    """Analisa texto bruto da página e retorna conteúdo potencialmente não mapeado."""
    fatura = fatura or {}
    resultado = ResultadoDeteccao()

    for item in listar_linhas_itens(texto):
        if not item_e_conhecido(item.descricao):
            rotulo = f"{item.descricao} ({item.unidade})".strip()
            if rotulo not in resultado.itens_nao_mapeados:
                resultado.itens_nao_mapeados.append(rotulo)

    for grandeza in listar_grandezas_medidor(texto):
        if not grandeza_e_conhecida(grandeza):
            if grandeza not in resultado.medidor_nao_mapeado:
                resultado.medidor_nao_mapeado.append(grandeza)

    for rotulo in listar_rotulos_desconhecidos(texto):
        if rotulo not in resultado.rotulos_nao_mapeados:
            resultado.rotulos_nao_mapeados.append(rotulo)

    resultado.palavras_peculiares = _filtrar_peculiares_relevantes(texto, fatura)

    linhas = listar_linhas_itens(texto)
    soma = round(sum(item.valor or 0 for item in linhas), 2)
    if linhas:
        resultado.soma_itens_detectados = soma
        total_declarado = parse_numero_brasileiro(str(fatura.get("total_itens_fatura", "")))
        if total_declarado is not None:
            resultado.divergencia_total_itens = round(soma - total_declarado, 2)

    return resultado

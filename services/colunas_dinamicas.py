"""
Registro persistente de colunas dinâmicas para itens de fatura não catalogados.

Cada descrição nova vira coluna(s) no CSV. Descrições já vistas reutilizam
as mesmas colunas — sem duplicar campos.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.campos_fatura import COLUNAS_FATURA
from services.normalizar_campo import descricao_pode_ter_nota_fiscal, normalizar_descricao_item
from services.numeros import valor_ou_vazio

logger = logging.getLogger(__name__)

DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "registro_colunas.json"
)

_SUFIXO_QTD = "_qtd"
_SUFIXO_NF = "_NF"

# Chaves legadas que devem reutilizar o mesmo registro canônico
_ALIASES_CHAVE: dict[str, str] = {
    "multa-nf": "multa",
    "juros-nf": "juros",
}


@dataclass(frozen=True)
class ColunasItem:
    descricao: str
    chave: str
    coluna_valor: str
    coluna_qtd: str | None
    coluna_nota_fiscal: str | None
    unidade: str


def _chave_descricao(descricao: str) -> str:
    """Chave interna para deduplicação (case-insensitive)."""
    return re.sub(r"\s+", " ", descricao.strip().lower())


def _nome_coluna(descricao: str) -> str:
    """
    Nome de coluna espelhando o texto da fatura; apenas espaços viram ``_``.
    Preserva maiúsculas, acentos, pontos e demais caracteres do PDF.
    """
    nome = re.sub(r"\s+", "_", descricao.strip())
    return nome or "desconhecido"


def _colunas_reservadas() -> set[str]:
    return {c.lower() for c in (*COLUNAS_FATURA, "data_ingestao")}


def _colunas_em_uso(itens: dict[str, dict[str, str]]) -> set[str]:
    em_uso: set[str] = set()
    for reg in itens.values():
        em_uso.add(reg["coluna_valor"].lower())
        if reg.get("coluna_qtd"):
            em_uso.add(reg["coluna_qtd"].lower())
        if reg.get("coluna_nota_fiscal"):
            em_uso.add(reg["coluna_nota_fiscal"].lower())
    return em_uso


class RegistroColunasDinamicas:
    """Catálogo de colunas dinâmicas com persistência em JSON."""

    def __init__(self, caminho: Path | str = DEFAULT_REGISTRY_PATH) -> None:
        self.caminho = Path(caminho)
        self._itens: dict[str, dict[str, str]] = {}
        self._carregar()

    def _carregar(self) -> None:
        if not self.caminho.is_file():
            self._itens = {}
            return
        try:
            dados = json.loads(self.caminho.read_text(encoding="utf-8"))
            self._itens = dados.get("itens", {})
        except (json.JSONDecodeError, OSError):
            logger.exception("Falha ao carregar registro de colunas: %s", self.caminho)
            self._itens = {}

    def _salvar(self) -> None:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "itens": self._itens}
        self.caminho.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _gerar_nome_coluna_unico(
        self,
        descricao: str,
        com_qtd: bool,
        com_nota_fiscal: bool,
    ) -> tuple[str, str | None, str | None]:
        """Gera nomes das colunas de valor, quantidade e NF de referência."""
        base = _nome_coluna(descricao)
        reservadas = _colunas_reservadas()
        existentes = _colunas_em_uso(self._itens)

        candidato_base = base
        n = 2
        while True:
            col_valor = candidato_base
            col_qtd = f"{candidato_base}{_SUFIXO_QTD}" if com_qtd else None
            col_nf = f"{candidato_base}{_SUFIXO_NF}" if com_nota_fiscal else None

            valor_ok = col_valor.lower() not in reservadas and col_valor.lower() not in existentes
            qtd_ok = (
                not com_qtd
                or (
                    col_qtd is not None
                    and col_qtd.lower() not in reservadas
                    and col_qtd.lower() not in existentes
                )
            )
            nf_ok = (
                not com_nota_fiscal
                or (
                    col_nf is not None
                    and col_nf.lower() not in reservadas
                    and col_nf.lower() not in existentes
                )
            )

            if valor_ok and qtd_ok and nf_ok:
                return col_valor, col_qtd, col_nf

            candidato_base = f"{base}_{n}"
            n += 1

    def registrar_item(self, descricao: str, unidade: str = "") -> ColunasItem:
        """Retorna colunas para a descrição; cria registro se for item novo."""
        descricao = normalizar_descricao_item(descricao)
        chave = _chave_descricao(descricao)
        chave = _ALIASES_CHAVE.get(chave, chave)

        if chave in self._itens:
            reg = self._itens[chave]
            return ColunasItem(
                descricao=reg["descricao"],
                chave=chave,
                coluna_valor=reg["coluna_valor"],
                coluna_qtd=reg.get("coluna_qtd") or None,
                coluna_nota_fiscal=reg.get("coluna_nota_fiscal") or None,
                unidade=reg.get("unidade", ""),
            )

        com_qtd = bool(unidade.strip())
        com_nf = descricao_pode_ter_nota_fiscal(descricao)
        col_valor, col_qtd, col_nf = self._gerar_nome_coluna_unico(
            descricao,
            com_qtd=com_qtd,
            com_nota_fiscal=com_nf,
        )

        registro: dict[str, str] = {
            "descricao": descricao,
            "coluna_valor": col_valor,
            "unidade": unidade,
        }
        if col_qtd:
            registro["coluna_qtd"] = col_qtd
        if col_nf:
            registro["coluna_nota_fiscal"] = col_nf

        self._itens[chave] = registro
        self._salvar()

        logger.info(
            "Nova coluna dinâmica — '%s' → %s%s%s",
            descricao,
            col_valor,
            f", {col_qtd}" if col_qtd else "",
            f", {col_nf}" if col_nf else "",
        )

        return ColunasItem(
            descricao=descricao,
            chave=chave,
            coluna_valor=col_valor,
            coluna_qtd=col_qtd,
            coluna_nota_fiscal=col_nf,
            unidade=unidade,
        )

    def listar_colunas(self) -> tuple[str, ...]:
        colunas: list[str] = []
        for reg in self._itens.values():
            colunas.append(reg["coluna_valor"])
            if reg.get("coluna_qtd"):
                colunas.append(reg["coluna_qtd"])
            if reg.get("coluna_nota_fiscal"):
                colunas.append(reg["coluna_nota_fiscal"])
        return tuple(sorted(set(colunas)))

    def listar_itens(self) -> list[dict[str, str]]:
        return [dict(reg, chave=chave) for chave, reg in sorted(self._itens.items())]


_registro_global: RegistroColunasDinamicas | None = None


def obter_registro(caminho: Path | str | None = None) -> RegistroColunasDinamicas:
    global _registro_global
    if caminho is not None:
        return RegistroColunasDinamicas(caminho)
    if _registro_global is None:
        _registro_global = RegistroColunasDinamicas()
    return _registro_global


def colunas_csv_completas() -> tuple[str, ...]:
    """Colunas fixas + dinâmicas + data_ingestao."""
    from services.campos_fatura import COLUNAS_FATURA

    dinamicas = obter_registro().listar_colunas()
    return (*COLUNAS_FATURA, *dinamicas, "data_ingestao")


def aplicar_itens_dinamicos(
    fatura: dict[str, Any],
    itens_nao_catalogados: list[dict[str, Any]],
    registro: RegistroColunasDinamicas | None = None,
) -> dict[str, Any]:
    """Registra colunas novas e preenche valores na fatura."""
    reg = registro or obter_registro()

    for item in itens_nao_catalogados:
        descricao = str(item.get("descricao", "")).strip()
        if not descricao:
            continue

        colunas = reg.registrar_item(descricao, str(item.get("unidade", "")))
        valor = item.get("valor")
        if valor is not None and valor != "":
            fatura[colunas.coluna_valor] = valor_ou_vazio(
                valor if isinstance(valor, (int, float)) else None
            )

        if colunas.coluna_qtd:
            qtd = item.get("quantidade")
            if qtd is not None and qtd != "":
                fatura[colunas.coluna_qtd] = valor_ou_vazio(
                    qtd if isinstance(qtd, (int, float)) else None
                )

        if colunas.coluna_nota_fiscal:
            nota = str(item.get("numero_nota_fiscal", "")).strip()
            if nota:
                fatura[colunas.coluna_nota_fiscal] = nota

    return fatura

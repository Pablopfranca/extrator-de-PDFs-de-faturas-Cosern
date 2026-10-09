"""
Persistência das faturas de PDF em JSON, um arquivo por instalação.

Espelha a saída do Módulo 1 (``modulo1/data/output/json/...``) para que o
Módulo 2 leia as duas origens com o mesmo parser:

    modulo1b/data/output/json/faturas_pdf/<instalacao>.json

A carga é **incremental**: um PDF novo com meses novos é fundido no arquivo
existente da instalação, sem perder competências já extraídas.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

from services.extrator import PdfSource, extrair_faturas
from services.fuso_horario import agora_fortaleza
from services.json_builder import montar_payloads

logger = logging.getLogger(__name__)

ModoPersistencia = Literal["merge", "overwrite"]

DEFAULT_JSON_DIR = (
    Path(__file__).resolve().parent.parent / "data" / "output" / "json" / "faturas_pdf"
)

_SECOES_MENSAIS = ("dadosAtiva", "dadosReativa", "dadosDemanda", "dadosMontante")


def _chave_competencia(linha: Mapping[str, Any]) -> tuple[str, str]:
    return (str(linha.get("ano") or ""), str(linha.get("mes") or ""))


def _chave_fatura(fatura: Mapping[str, Any]) -> tuple[str, str]:
    return (
        str(fatura.get("ano") or ""),
        str(fatura.get("mes") or ""),
    )


def _fundir_lista(
    existentes: Iterable[Mapping[str, Any]],
    novas: Iterable[Mapping[str, Any]],
    chave,
) -> list[dict[str, Any]]:
    """Novas competências substituem as antigas; o resto é preservado."""
    acumulado: dict[tuple[str, str], dict[str, Any]] = {}
    for linha in existentes:
        acumulado[chave(linha)] = dict(linha)
    for linha in novas:
        acumulado[chave(linha)] = dict(linha)

    return [
        acumulado[k]
        for k in sorted(acumulado, key=lambda k: (k[0], k[1].zfill(2)), reverse=True)
    ]


def _fundir_payload(
    existente: Mapping[str, Any],
    novo: Mapping[str, Any],
) -> dict[str, Any]:
    fundido = dict(novo)

    for secao in _SECOES_MENSAIS:
        fundido[secao] = _fundir_lista(
            existente.get(secao) or [],
            novo.get(secao) or [],
            _chave_competencia,
        )

    fundido["faturasPdf"] = _fundir_lista(
        existente.get("faturasPdf") or [],
        novo.get("faturasPdf") or [],
        _chave_fatura,
    )

    historico = dict(fundido.get("dadosHistorico") or {})
    historico["qtdFaturas"] = len(fundido["faturasPdf"])
    fundido["dadosHistorico"] = historico

    return fundido


def _ler_existente(arquivo: Path) -> dict[str, Any] | None:
    if not arquivo.is_file():
        return None
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.exception("JSON existente ilegível, será sobrescrito: %s", arquivo)
        return None
    return dados if isinstance(dados, dict) else None


def salvar_payloads_json(
    payloads: Mapping[str, Mapping[str, Any]],
    pasta: Path | str = DEFAULT_JSON_DIR,
    modo: ModoPersistencia = "merge",
) -> dict[str, Any]:
    destino = Path(pasta)
    destino.mkdir(parents=True, exist_ok=True)

    momento = agora_fortaleza().isoformat(timespec="seconds")
    criados = 0
    atualizados = 0
    competencias = 0

    for instalacao, payload in sorted(payloads.items()):
        arquivo = destino / f"{instalacao}.json"
        existente = _ler_existente(arquivo) if modo == "merge" else None

        final = _fundir_payload(existente, payload) if existente else dict(payload)
        final["dataIngestao"] = momento

        arquivo.write_text(
            json.dumps(final, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if existente:
            atualizados += 1
        else:
            criados += 1
        competencias += len(final.get("faturasPdf") or [])

    resumo = {
        "pasta": str(destino.resolve()),
        "instalacoes": len(payloads),
        "arquivos_criados": criados,
        "arquivos_atualizados": atualizados,
        "competencias_no_disco": competencias,
    }
    logger.info("JSON gravado: %s", resumo)
    return resumo


def extrair_e_salvar_json(
    fonte: PdfSource,
    pasta: Path | str = DEFAULT_JSON_DIR,
    modo: ModoPersistencia = "merge",
) -> dict[str, Any]:
    faturas = extrair_faturas(fonte)
    payloads = montar_payloads(faturas)
    resumo = salvar_payloads_json(payloads, pasta=pasta, modo=modo)

    resumo.update(
        {
            "arquivo_origem": str(fonte) if isinstance(fonte, (str, Path)) else "<stream>",
            "faturas_extraidas": len(faturas),
        }
    )
    logger.info("Ingestão JSON concluída: %s", resumo)
    return resumo


def carregar_payload(
    instalacao: str,
    pasta: Path | str = DEFAULT_JSON_DIR,
) -> dict[str, Any] | None:
    return _ler_existente(Path(pasta) / f"{instalacao}.json")

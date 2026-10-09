"""
Converte faturas extraídas de PDF para a estrutura JSON do Módulo 1 (API Cosern).

Cada instalação vira um arquivo com as mesmas seções que o endpoint de histórico
(``dadosHistorico``, ``dadosGerais``, ``dadosAtiva``, ``dadosReativa``,
``dadosDemanda``, ``dadosMontante``) para que o Módulo 2 reaproveite o parser.

O PDF traz mais informação que a API. Nada é descartado:

* ``faturasPdf``  — todos os campos extraídos, um registro por fatura.
* Campos extras dentro das seções padrão (``medidaP``, ``faturadaP``, ``ociosaP``…)
  convivem com os nomes da API sem quebrar quem lê só o formato original.

Diferença crítica de semântica, confirmada na comparação PDF × API:

``dadosDemanda.valorP/valorFP`` da API é a demanda **faturada** (piso no
contrato). A demanda **medida** real só existe no PDF, na tabela MEDIDOR.
Aqui ``valorP``/``valorFP`` recebem a medida real e a faturada fica em
``faturadaP``/``faturadaFP``.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any, Iterable, Mapping

from services.numeros import parse_numero_brasileiro

logger = logging.getLogger(__name__)

VERSAO_LAYOUT = 1
ORIGEM = "PDF"

_RE_LIMPAR_EXCEL = re.compile(r'^="|"$')


def _texto(valor: Any) -> str:
    if valor is None:
        return ""
    return _RE_LIMPAR_EXCEL.sub("", str(valor).strip())


def _numero(valor: Any) -> float | None:
    """Aceita tanto float quanto string (BR ou ponto decimal)."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    return parse_numero_brasileiro(_texto(valor))


def _api_num(valor: Any) -> str | None:
    """Formata como a API faz: string com 7 casas decimais."""
    numero = _numero(valor)
    if numero is None:
        return None
    return f"{numero:.7f}"


def _instalacao_padronizada(codigo: str) -> str:
    """
    Instalação antiga: 10 dígitos com zero à esquerda.
    UC nova (só número da unidade): mantém todos os dígitos sem truncar.
    """
    limpo = re.sub(r"\D", "", _texto(codigo))
    if not limpo:
        return ""
    if len(limpo) <= 10:
        return limpo.zfill(10)
    return limpo


def _ano_mes(mes_referencia: Any) -> tuple[int | None, int | None]:
    texto = _texto(mes_referencia)
    match = re.fullmatch(r"(\d{1,2})/(\d{4})", texto)
    if match:
        return int(match.group(2)), int(match.group(1))
    match = re.fullmatch(r"(\d{4})/(\d{1,2})", texto)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None


def _data_iso(valor: Any) -> str | None:
    texto = _texto(valor)
    match = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", texto)
    if not match:
        return None
    return f"{match.group(3)}-{match.group(2)}-{match.group(1)}"


def _competencia(ano: int, mes: int) -> str:
    return f"{ano:04d}/{mes:02d}"


def _eh_grupo_a(fatura: Mapping[str, Any]) -> bool:
    return _texto(fatura.get("grupo")).upper() == "A"


# ---------------------------------------------------------------------------
# Seções mensais
# ---------------------------------------------------------------------------


def _bloco_base(fatura: Mapping[str, Any], ano: int, mes: int) -> dict[str, Any]:
    """Campos de identificação repetidos em toda seção mensal, como na API."""
    return {
        "numDocCalculo": _texto(fatura.get("documento_pagamento")) or None,
        "ano": str(ano),
        "mes": str(mes),
        "dataCalculo": _competencia(ano, mes),
        "diaFat": _texto(fatura.get("dias_faturados")) or None,
        "dataInicioFaixaValida": _data_iso(fatura.get("leitura_anterior")),
        "dataFimFaixaValida": _data_iso(fatura.get("leitura_atual")),
    }


def _linha_ativa(fatura: Mapping[str, Any], ano: int, mes: int) -> dict[str, Any]:
    """
    Energia ativa (kWh).

    A API publica a quantidade **faturada** (já com perda de transformação).
    No PDF isso é ``consumo_tusd_*``; a leitura crua do medidor fica em
    ``consumo_*_kwh`` e é preservada em ``medidaP``/``medidaFP``.
    """
    linha = _bloco_base(fatura, ano, mes)

    if _eh_grupo_a(fatura):
        faturado_p = fatura.get("consumo_tusd_ponta_kwh")
        faturado_fp = fatura.get("consumo_tusd_fponta_kwh")
        medido_p = fatura.get("consumo_ponta_kwh")
        medido_fp = fatura.get("consumo_fponta_kwh")
    else:
        # Sem posto horario: a API concentra o consumo unico em valorP.
        faturado_p = fatura.get("consumo_tusd_kwh") or fatura.get("consumo_unico_kwh")
        faturado_fp = 0
        medido_p = fatura.get("consumo_unico_kwh")
        medido_fp = None

    linha.update(
        {
            "valorP": _api_num(faturado_p if faturado_p not in (None, "") else medido_p),
            "valorFP": _api_num(faturado_fp if faturado_fp not in (None, "") else medido_fp),
            "consumoAtivoIntermediario": _api_num(0),
            "consumoAtivoReservado": _api_num(0),
            # Extras do PDF
            "medidaP": _api_num(medido_p),
            "medidaFP": _api_num(medido_fp),
            "tusdP": _api_num(fatura.get("consumo_tusd_ponta_kwh")),
            "tusdFP": _api_num(fatura.get("consumo_tusd_fponta_kwh")),
            "teP": _api_num(fatura.get("consumo_te_ponta_kwh")),
            "teFP": _api_num(fatura.get("consumo_te_fponta_kwh")),
        }
    )
    return linha


def _linha_reativa(fatura: Mapping[str, Any], ano: int, mes: int) -> dict[str, Any] | None:
    if _eh_grupo_a(fatura):
        valor_p = fatura.get("consumo_reat_exc_ponta_kvarh")
        valor_fp = fatura.get("consumo_reat_exc_fponta_kvarh")
    else:
        valor_p = fatura.get("consumo_reat_excedente_kvarh")
        valor_fp = 0

    if _numero(valor_p) is None and _numero(valor_fp) is None:
        return None

    linha = _bloco_base(fatura, ano, mes)
    linha.update(
        {
            "valorP": _api_num(valor_p),
            "valorFP": _api_num(valor_fp),
            "consumoReativoReservado": _api_num(0),
            "energiaReativaUnicoKwh": _api_num(fatura.get("energia_reativa_unico_kwh")),
        }
    )
    return linha


def _linha_demanda(fatura: Mapping[str, Any], ano: int, mes: int) -> dict[str, Any] | None:
    """
    Demanda (kW). Só Grupo A.

    ``valorP``/``valorFP`` = demanda **ativa cobrada** (linha Demanda Ativa da fatura).
    ``medidaP``/``medidaFP`` = leitura crua do medidor (antes de perdas, ex. 2,5%).
    ``faturadaP``/``faturadaFP`` = alias da cobrada (compatibilidade).
    """
    if not _eh_grupo_a(fatura):
        return None

    medida_p = fatura.get("demanda_medida_ponta_kw")
    medida_fp = fatura.get("demanda_medida_fponta_kw")

    azul = bool(_texto(fatura.get("demanda_contratada_np_kw")))
    if azul:
        contratada_p = fatura.get("demanda_contratada_np_kw")
        contratada_fp = fatura.get("demanda_contratada_fp_kw")
        faturada_p = fatura.get("demanda_faturada_np_kw")
        faturada_fp = fatura.get("demanda_faturada_fp_kw")
        ociosa_p = fatura.get("demanda_ultrapassagem_np_kw")
        ociosa_fp = fatura.get("demanda_ultrapassagem_fp_kw")
    else:
        # Verde: contrato único, aplicado aos dois postos
        contratada_p = contratada_fp = fatura.get("demanda_contratada_kw")
        faturada_p = None
        faturada_fp = fatura.get("demanda_faturada_kw")
        ociosa_p = None
        ociosa_fp = fatura.get("demanda_ultrapassagem_kw")

    if all(
        _numero(v) is None
        for v in (medida_p, medida_fp, contratada_p, contratada_fp, faturada_fp)
    ):
        return None

    if azul:
        cobrada_p = faturada_p if _numero(faturada_p) is not None else medida_p
        cobrada_fp = faturada_fp if _numero(faturada_fp) is not None else medida_fp
    else:
        cobrada_fp = faturada_fp if _numero(faturada_fp) is not None else medida_fp
        cobrada_p = (
            faturada_fp if _numero(faturada_fp) is not None else medida_p
        )

    linha = _bloco_base(fatura, ano, mes)
    linha.update(
        {
            "valorP": _api_num(cobrada_p),
            "valorFP": _api_num(cobrada_fp),
            "medidaP": _api_num(medida_p),
            "medidaFP": _api_num(medida_fp),
            "contratadaP": _api_num(contratada_p),
            "contratadaFP": _api_num(contratada_fp),
            # Extras do PDF
            "faturadaP": _api_num(faturada_p),
            "faturadaFP": _api_num(faturada_fp),
            "ociosaP": _api_num(ociosa_p),
            "ociosaFP": _api_num(ociosa_fp),
            "modalidade": "AZUL" if azul else "VERDE",
            "perdaTransformacaoPct": _api_num(fatura.get("perda_transformacao_pct")),
            "fatorPotenciaMedio": _api_num(fatura.get("fator_potencia_medio")),
        }
    )
    return linha


def _linha_montante(fatura: Mapping[str, Any], ano: int, mes: int) -> dict[str, Any]:
    """Valores em R$ — equivalente ao ``dadosMontante`` da API."""
    grupo_a = _eh_grupo_a(fatura)

    if grupo_a:
        ativa_fp_tu = fatura.get("consumo_tusd_fponta_valor")
        ativa_fp_te = fatura.get("consumo_te_fponta_valor")
        ativa_p_tu = fatura.get("consumo_tusd_ponta_valor")
        ativa_p_te = fatura.get("consumo_te_ponta_valor")
        reativo_p = fatura.get("consumo_reat_exc_ponta_valor")
        reativo_fp = fatura.get("consumo_reat_exc_fponta_valor")
        dem_ativ_p = fatura.get("demanda_faturada_np_valor")
        dem_ativ_fp = (
            fatura.get("demanda_faturada_fp_valor")
            or fatura.get("demanda_faturada_valor")
        )
        dem_reat_p = fatura.get("demanda_reativa_exc_np_valor")
        dem_reat_fp = (
            fatura.get("demanda_reativa_exc_fp_valor")
            or fatura.get("demanda_reativa_exc_valor")
        )
        dem_ultrap_p = fatura.get("demanda_ultrapassagem_np_valor")
        dem_ultrap_fp = (
            fatura.get("demanda_ultrapassagem_fp_valor")
            or fatura.get("demanda_ultrapassagem_valor")
        )
    else:
        # Idem dadosAtiva: no Grupo B a API usa as colunas de ponta.
        ativa_p_tu = fatura.get("consumo_tusd_valor")
        ativa_p_te = fatura.get("consumo_te_valor")
        ativa_fp_tu = ativa_fp_te = 0
        reativo_p = fatura.get("consumo_reat_excedente_valor")
        reativo_fp = 0
        dem_ativ_p = dem_ativ_fp = None
        dem_reat_p = dem_reat_fp = None
        dem_ultrap_p = dem_ultrap_fp = None

    valores_reativo = [_numero(reativo_p) or 0, _numero(reativo_fp) or 0]

    linha = _bloco_base(fatura, ano, mes)
    linha.update(
        {
            "reativoP": _api_num(reativo_p),
            "reativoFP": _api_num(reativo_fp),
            "reativoTotal": _api_num(sum(valores_reativo)),
            "demReatP": _api_num(dem_reat_p),
            "demReatFP": _api_num(dem_reat_fp),
            "demAtivP": _api_num(dem_ativ_p),
            "demAtivFP": _api_num(dem_ativ_fp),
            "demUltrapaP": _api_num(dem_ultrap_p),
            "demUltrapaFP": _api_num(dem_ultrap_fp),
            "ativaFP_TU": _api_num(ativa_fp_tu),
            "ativaFP_TE": _api_num(ativa_fp_te),
            "ativaP_TU": _api_num(ativa_p_tu),
            "ativaP_TE": _api_num(ativa_p_te),
            "reatPorcent": _api_num(0),
            "totalMontante": _api_num(fatura.get("valor_total")),
            "dataVencimento": _data_iso(fatura.get("data_vencimento")),
            "dataPagamento": None,
            # Extras do PDF
            "iluminacaoPublica": _api_num(fatura.get("iluminacao_publica_valor")),
            "acrescimoBandeira": _api_num(fatura.get("acrescimo_bandeira_valor")),
            "totalItensFatura": _api_num(fatura.get("total_itens_fatura")),
            "bandeiraTarifaria": _texto(fatura.get("bandeira_tarifaria")) or None,
        }
    )
    return linha


# ---------------------------------------------------------------------------
# Seções de cabeçalho
# ---------------------------------------------------------------------------


def _dados_historico(
    instalacao: str,
    faturas: list[Mapping[str, Any]],
    ativa: list[Mapping[str, Any]],
) -> dict[str, Any]:
    recente = faturas[0]

    consumos: list[float] = []
    for linha in ativa:
        for chave in ("valorP", "valorFP"):
            valor = _numero(linha.get(chave))
            if valor:
                consumos.append(valor)

    total_anual = sum(
        _numero(f.get("valor_total")) or 0.0 for f in faturas
    )

    return {
        "instalacao": instalacao,
        "contaContrato": None,
        "codigoUcAneel": None,
        "numParceiro": _texto(recente.get("codigo_cliente")) or None,
        "valorInstalado": _api_num(0),
        "totalAnual": f"{total_anual:.2f}",
        "maiorConsumo": _api_num(max(consumos)) if consumos else None,
        "menorConsumo": _api_num(min(consumos)) if consumos else None,
        "perfilConsumo": None,
        "modalidade": None,
        "demSugeridaPonta": None,
        "demSugeridaFP": None,
        # Extras do PDF
        "contaColetiva": _texto(recente.get("conta_coletiva")) or None,
        "codigoInstalacaoPdf": _texto(recente.get("codigo_instalacao")) or None,
        "numeroUc": _texto(recente.get("numero_uc")) or None,
        "nomeCliente": _texto(recente.get("nome_cliente")) or None,
        "numeroMedidor": _texto(recente.get("numero_medidor")) or None,
        "qtdFaturas": len(faturas),
    }


def _dados_gerais(faturas: list[Mapping[str, Any]]) -> dict[str, Any]:
    recente = faturas[0]
    classificacao = _texto(recente.get("classificacao")).upper()

    return {
        "categoria": None,
        "tipoConta": None,
        "subGrupo": classificacao or None,
        "tensao": None,
        "modalidadeUc": _texto(recente.get("modalidade_tarifaria")) or None,
        "statusUc": None,
        # Extras do PDF
        "grupo": _texto(recente.get("grupo")).upper() or None,
        "classificacaoDescricao": _texto(recente.get("classificacao_descricao")) or None,
        "tipoFornecimento": _texto(recente.get("tipo_fornecimento")) or None,
        "endereco": _texto(recente.get("endereco")) or None,
        "nomeLocal": _texto(recente.get("nome_local")) or None,
        "bairro": _texto(recente.get("bairro")) or None,
        "cep": _texto(recente.get("cep")) or None,
        "cnpjTomadorMascarado": _texto(recente.get("cnpj_tomador_mascarado")) or None,
    }


def _fatura_completa(fatura: Mapping[str, Any], ano: int | None, mes: int | None) -> dict[str, Any]:
    """Registro cru: todo campo extraído do PDF, sem descarte."""
    bruto = {chave: _texto(valor) for chave, valor in fatura.items()}
    bruto["ano"] = str(ano) if ano else ""
    bruto["mes"] = str(mes) if mes else ""
    return bruto


# ---------------------------------------------------------------------------
# Montagem
# ---------------------------------------------------------------------------


def _ordenar_por_competencia(faturas: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    def chave(fatura: Mapping[str, Any]) -> tuple[int, int]:
        ano, mes = _ano_mes(fatura.get("mes_referencia"))
        return (ano or 0, mes or 0)

    return sorted(faturas, key=chave, reverse=True)


def agrupar_por_instalacao(
    faturas: Iterable[Mapping[str, Any]],
) -> dict[str, list[Mapping[str, Any]]]:
    grupos: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for fatura in faturas:
        instalacao = _instalacao_padronizada(fatura.get("codigo_instalacao"))
        if not instalacao:
            logger.warning(
                "Fatura sem código de instalação ignorada (ref=%s, arquivo=%s).",
                _texto(fatura.get("mes_referencia")),
                _texto(fatura.get("arquivo_origem")),
            )
            continue
        grupos[instalacao].append(fatura)
    return grupos


def montar_payload(
    instalacao: str,
    faturas: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Monta o JSON de uma instalação no formato da API + dados completos do PDF."""
    ordenadas = _ordenar_por_competencia(faturas)

    ativa: list[dict[str, Any]] = []
    reativa: list[dict[str, Any]] = []
    demanda: list[dict[str, Any]] = []
    montante: list[dict[str, Any]] = []
    completas: list[dict[str, Any]] = []

    for fatura in ordenadas:
        ano, mes = _ano_mes(fatura.get("mes_referencia"))
        completas.append(_fatura_completa(fatura, ano, mes))

        if ano is None or mes is None:
            logger.warning(
                "Fatura sem mês de referência utilizável (instalação %s, arquivo %s).",
                instalacao,
                _texto(fatura.get("arquivo_origem")),
            )
            continue

        ativa.append(_linha_ativa(fatura, ano, mes))
        montante.append(_linha_montante(fatura, ano, mes))

        linha_reativa = _linha_reativa(fatura, ano, mes)
        if linha_reativa:
            reativa.append(linha_reativa)

        linha_demanda = _linha_demanda(fatura, ano, mes)
        if linha_demanda:
            demanda.append(linha_demanda)

    return {
        "origem": ORIGEM,
        "versaoLayout": VERSAO_LAYOUT,
        "dadosHistorico": _dados_historico(instalacao, ordenadas, ativa),
        "dadosGerais": _dados_gerais(ordenadas),
        "dadosAtiva": ativa,
        "dadosReativa": reativa,
        "dadosDemanda": demanda,
        "dadosMontante": montante,
        "faturasPdf": completas,
    }


def montar_payloads(
    faturas: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Um payload por instalação."""
    return {
        instalacao: montar_payload(instalacao, lista)
        for instalacao, lista in agrupar_por_instalacao(faturas).items()
    }

"""
Definição canônica de campos extraídos das faturas Neoenergia/Cosern.

Grupo A e Grupo B compartilham identificação e metadados, mas possuem
colunas de consumo/demanda distintas (sem forçar posto ponta/fora ponta no B).
"""

from __future__ import annotations

from typing import Literal, TypedDict

GrupoTarifario = Literal["A", "B"]

# ---------------------------------------------------------------------------
# Colunas CSV — ordem fixa para migração futura a SQL
# ---------------------------------------------------------------------------

COLUNAS_IDENTIFICACAO: tuple[str, ...] = (
    "codigo_instalacao",
    "codigo_cliente",
    "numero_uc",
    "nome_cliente",
    "endereco",
    "nome_local",
    "bairro",
    "cep",
    "cnpj_tomador_mascarado",
)

COLUNAS_NOTA_FISCAL: tuple[str, ...] = (
    "nota_fiscal",
    "serie_nf",
    "data_emissao",
    "protocolo_autorizacao",
    "chave_acesso",
)

COLUNAS_TARIFA: tuple[str, ...] = (
    "grupo",
    "classificacao",
    "classificacao_descricao",
    "tipo_fornecimento",
    "modalidade_tarifaria",
)

COLUNAS_FATURAMENTO: tuple[str, ...] = (
    "mes_referencia",
    "data_vencimento",
    "valor_total",
    "total_itens_fatura",
    "bandeira_tarifaria",
)

COLUNAS_LEITURA: tuple[str, ...] = (
    "leitura_anterior",
    "leitura_atual",
    "dias_faturados",
    "proxima_leitura",
)

COLUNAS_COLETIVA: tuple[str, ...] = (
    "conta_coletiva",
    "documento_pagamento",
    "numero_medidor",
)

COLUNAS_TRIBUTOS: tuple[str, ...] = (
    "pis_base",
    "pis_aliquota_pct",
    "pis_valor",
    "cofins_base",
    "cofins_aliquota_pct",
    "cofins_valor",
    "icms_base",
    "icms_aliquota_pct",
    "icms_valor",
)

# Grupo A — alta tensão / horo-sazonal Verde (demanda única)
COLUNAS_GRUPO_A: tuple[str, ...] = (
    "demanda_contratada_kw",
    "demanda_faturada_kw",
    "demanda_faturada_valor",
    "demanda_reativa_exc_kvar",
    "demanda_reativa_exc_valor",
    "demanda_ultrapassagem_kw",
    "demanda_ultrapassagem_valor",
    "demanda_medida_ponta_kw",
    "demanda_medida_fponta_kw",
    "consumo_ponta_kwh",
    "consumo_fponta_kwh",
    "consumo_tusd_ponta_kwh",
    "consumo_tusd_ponta_valor",
    "consumo_tusd_fponta_kwh",
    "consumo_tusd_fponta_valor",
    "consumo_te_ponta_kwh",
    "consumo_te_ponta_valor",
    "consumo_te_fponta_kwh",
    "consumo_te_fponta_valor",
    "consumo_reat_exc_ponta_kvarh",
    "consumo_reat_exc_ponta_valor",
    "consumo_reat_exc_fponta_kvarh",
    "consumo_reat_exc_fponta_valor",
)

# Grupo A — horo-sazonal Azul (demanda contratada NP + FP separadas)
COLUNAS_GRUPO_A_AZUL: tuple[str, ...] = (
    "demanda_contratada_np_kw",
    "demanda_contratada_fp_kw",
    "demanda_faturada_np_kw",
    "demanda_faturada_fp_kw",
    "demanda_faturada_np_valor",
    "demanda_faturada_fp_valor",
    "demanda_reativa_exc_np_kvar",
    "demanda_reativa_exc_fp_kvar",
    "demanda_reativa_exc_np_valor",
    "demanda_reativa_exc_fp_valor",
    "demanda_ultrapassagem_np_kw",
    "demanda_ultrapassagem_fp_kw",
    "demanda_ultrapassagem_np_valor",
    "demanda_ultrapassagem_fp_valor",
)

# Grupo B — baixa tensão / monômia
COLUNAS_GRUPO_B: tuple[str, ...] = (
    "consumo_unico_kwh",
    "consumo_tusd_kwh",
    "consumo_tusd_valor",
    "consumo_te_kwh",
    "consumo_te_valor",
    "consumo_te_kwh_amarela",
    "consumo_te_valor_amarela",
    "consumo_te_kwh_verde",
    "consumo_te_valor_verde",
    "consumo_reat_excedente_kvarh",
    "consumo_reat_excedente_valor",
    "energia_reativa_unico_kwh",
)

COLUNAS_INFORMACOES: tuple[str, ...] = (
    "perda_transformacao_pct",
    "fator_potencia_medio",
)

COLUNAS_ENCARGOS: tuple[str, ...] = (
    "iluminacao_publica_valor",
    "acrescimo_bandeira_valor",
    "trib_irrf_1_2_valor",
    "trib_irrf_4_8_valor",
)

COLUNAS_MEDIDOR_A: tuple[str, ...] = (
    "medidor_en_ponta_leit_ant",
    "medidor_en_ponta_leit_atual",
    "medidor_en_ponta_constante",
    "medidor_en_fponta_leit_ant",
    "medidor_en_fponta_leit_atual",
    "medidor_en_fponta_constante",
    "medidor_dem_ponta_leit_ant",
    "medidor_dem_ponta_leit_atual",
    "medidor_dem_fponta_leit_ant",
    "medidor_dem_fponta_leit_atual",
)

COLUNAS_MEDIDOR_B: tuple[str, ...] = (
    "medidor_en_leit_ant",
    "medidor_en_leit_atual",
    "medidor_en_constante",
    "medidor_reat_leit_ant",
    "medidor_reat_leit_atual",
    "medidor_reat_constante",
)

# Aliases legados (cálculo de demanda / compatibilidade)
COLUNAS_LEGADO: tuple[str, ...] = (
    "demanda_contratada",
    "demanda_ponta",
    "demanda_fponta",
    "consumo_ponta",
    "consumo_fponta",
)

COLUNAS_META: tuple[str, ...] = (
    "pagina",
    "arquivo_origem",
)

COLUNAS_FATURA: tuple[str, ...] = (
    *COLUNAS_IDENTIFICACAO,
    *COLUNAS_NOTA_FISCAL,
    *COLUNAS_TARIFA,
    *COLUNAS_FATURAMENTO,
    *COLUNAS_LEITURA,
    *COLUNAS_COLETIVA,
    *COLUNAS_TRIBUTOS,
    *COLUNAS_GRUPO_A,
    *COLUNAS_GRUPO_A_AZUL,
    *COLUNAS_GRUPO_B,
    *COLUNAS_ENCARGOS,
    *COLUNAS_MEDIDOR_A,
    *COLUNAS_MEDIDOR_B,
    *COLUNAS_INFORMACOES,
    *COLUNAS_LEGADO,
    *COLUNAS_META,
)


class FaturaExtraida(TypedDict, total=False):
    """Schema completo de uma fatura extraída."""

    codigo_instalacao: str
    codigo_cliente: str
    grupo: GrupoTarifario
    classificacao: str
    mes_referencia: str
    valor_total: float


def campos_vazios() -> dict[str, str]:
    """Retorna dict com todas as colunas inicializadas como string vazia."""
    return {coluna: "" for coluna in COLUNAS_FATURA}

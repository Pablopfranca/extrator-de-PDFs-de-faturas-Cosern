"""
Catálogo de padrões já mapeados pelo extrator Neoenergia/Cosern.

Usado pelo detector de conteúdo não mapeado: linhas/itens que não casam
com estes padrões são candidatos a campos novos ou peculiaridades locais.
"""

from __future__ import annotations

import re

# Linhas de item em ITENS DA FATURA (prefixo da descrição)
ITENS_FATURA_CONHECIDOS: tuple[str, ...] = (
    r"Demanda\s+Ativa",
    r"Demanda\s+Reativa",
    r"Demanda\s+Contratada",
    r"Dem\.?\s*Reat",
    r"Demanda\s+Ultrapas",
    r"Demanda\s+Na\s+Ponta\s+Lim",
    r"Demanda\s+Ativa-\s*Lim",
    r"Dem\.?\s*Fora\s+Ponta-Lim",
    r"Consumo-TUSD",
    r"Consumo-TE",
    r"Cons\.?\s*Reat",
    r"Acr[eé]s\.?\s*Band",
    r"Ilum\.?\s*P[uú]b",
    r"TRIBF-IRRF",
)

# Cabeçalhos/seções dentro do bloco de itens (não são cobranças)
ITENS_IGNORAR: tuple[str, ...] = (
    r"^PIS\b",
    r"^COFINS\b",
    r"^ICMS\b",
    r"^TOTAL\b",
    r"^ITENS DA FATURA",
    r"^UNID\.\s*QUANT",
    r"^COM TRIB",
    r"^BANDEIRA\s+(?:AMARELA|VERDE|VERMELHA)\s+GRANDEZAS",
    r"^BANDEIRA\s+(?:AMARELA|VERDE|VERMELHA)\s*$",
    r"^CONSUMO\s*/\s*kWh",
    r"^CONSUMO FATURADO",
)

# Grandezas na tabela MEDIDOR
GRANDEZAS_MEDIDOR_CONHECIDAS: tuple[str, ...] = (
    r"Energia Ativa Ponta",
    r"Energia Ativa Fora Ponta",
    r"Energia Ativa [ÚU]nico",
    r"Demanda Ativa Ponta",
    r"Demanda Ativa Fora Ponta",
    r"Energia Reativa [ÚU]nico",
    r"Demanda Reativa",
    r"Energia Reativa Ponta",
    r"Energia Reativa Fora Ponta",
)

# Rótulos de cabeçalho já tratados pelo extrator
ROTULOS_CABECALHO_CONHECIDOS: tuple[str, ...] = (
    r"ENDERE[ÇC]O",
    r"NOME DO CLIENTE",
    r"C[ÓO]DIGO DO CLIENTE",
    r"C[ÓO]DIGO DA INSTALA[ÇC][ÃA]O",
    r"CLASSIFICA[ÇC][ÃA]O",
    r"TIPO DE FORNECIMENTO",
    r"PODER PUBLICO",
    r"REF\s*:\s*M[EÊ]S/ANO",
    r"^REF$",
    r"NOTA FISCAL",
    r"DATA DE EMISS[ÃA]O",
    r"LEITURA ANTERIOR",
    r"LEITURA ATUAL",
    r"PR[ÓO]XIMA LEITURA",
    r"N[°º]?\s*DE\s*DIAS",
    r"DATAS DE LEITURAS",
    r"Conta Contrato Coletiva",
    r"Doc\.\s*Pgto",
    r"MEDIDOR",
    r"GRANDEZAS",
    r"POSTOS HOR[ÁA]RIOS",
    r"RESERVADO AO FISCO",
    r"ITENS DA FATURA",
    r"CONSUMO\s*/\s*kWh",
    r"CONSUMO FATURADO",
    r"Protocolo de autoriza",
    r"chave de acesso",
    r"Consulte pela Chave",
    r"CNPJ",
    r"CPF",
    r"Inscri[çc][ãa]o Estadual",
    r"TOTAL A PAGAR",
    r"VENCIMENTO",
)

# Termos que indicam peculiaridade tarifária/local — exigem mapeamento dedicado
PALAVRAS_PECULIARES: tuple[str, ...] = (
    r"compens",
    r"injetad",
    r"microger",
    r"miniger",
    r"\bgd\b",
    r"saldo\s+de",
    r"energia\s+ativada",
    r"benef[ií]cio",
    r"tarifa\s+social",
    r"desconto\s+social",
    r"cosip",
    r"devolu",
    r"restitu",
    r"reativa\s+excedente",
    r"ultrapassagem",
    r"gera[çc][ãa]o\s+distribu",
    r"autoconsumo",
    r"cr[eé]dito",
    r" SCEE ",
    r"\bscee\b",
)

_RE_ITENS_CONHECIDOS = [re.compile(p, re.IGNORECASE) for p in ITENS_FATURA_CONHECIDOS]
_RE_ITENS_IGNORAR = [re.compile(p, re.IGNORECASE) for p in ITENS_IGNORAR]
_RE_GRANDEZAS_CONHECIDAS = [re.compile(p, re.IGNORECASE) for p in GRANDEZAS_MEDIDOR_CONHECIDAS]
_RE_ROTULOS_CONHECIDOS = [re.compile(p, re.IGNORECASE) for p in ROTULOS_CABECALHO_CONHECIDOS]
_RE_PECULIARES = [re.compile(p, re.IGNORECASE) for p in PALAVRAS_PECULIARES]


def item_e_conhecido(descricao: str) -> bool:
    return any(p.search(descricao) for p in _RE_ITENS_CONHECIDOS)


def item_deve_ignorar(linha: str) -> bool:
    return any(p.search(linha.strip()) for p in _RE_ITENS_IGNORAR)


def grandeza_e_conhecida(tipo: str) -> bool:
    return any(p.search(tipo) for p in _RE_GRANDEZAS_CONHECIDAS)


def rotulo_e_conhecido(rotulo: str) -> bool:
    limpo = rotulo.strip().rstrip(":")
    return any(p.search(limpo) for p in _RE_ROTULOS_CONHECIDOS)


def buscar_palavras_peculiares(texto: str) -> list[str]:
    encontradas: list[str] = []
    for padrao in _RE_PECULIARES:
        for match in padrao.finditer(texto):
            trecho = match.group(0).strip()
            if trecho and trecho not in encontradas:
                encontradas.append(trecho)
    return encontradas

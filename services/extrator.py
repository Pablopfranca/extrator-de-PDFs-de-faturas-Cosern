"""
Módulo de ingestão universal de faturas Neoenergia/Cosern.

Extrai todos os campos disponíveis na DANFE, com pipelines distintos para
Grupo A (alta tensão / horo-sazonal) e Grupo B (baixa tensão / monômia).
"""

from __future__ import annotations

import logging
import re
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO, Union

import pdfplumber
from pdfplumber.page import Page

from services.campos_fatura import (
    COLUNAS_FATURA,
    FaturaExtraida,
    GrupoTarifario,
    campos_vazios,
)

logger = logging.getLogger(__name__)

KEYWORD_PAGINA_VALIDA = r"C[ÓO]DIGO\s+DA\s+INSTALA"
HEADER_CROP_HEIGHT_PT = 250

PdfSource = Union[str, Path, BinaryIO, bytes]

# ---------------------------------------------------------------------------
# RegEx — identificação e metadados
# ---------------------------------------------------------------------------

# Padrão genérico de CNPJ mascarado na DANFE (sem prefixo fixo do tomador)
_CNPJ_MASCARADO = r"\d{2}\.\d{3}\.\*+\/\*+\-\*+"

_RE_CODIGO_INSTALACAO_MASCARADO = re.compile(
    rf"{_CNPJ_MASCARADO}\s+(\d{{4,10}})",
    re.IGNORECASE,
)
_RE_CODIGO_INSTALACAO_ANTES_NF = re.compile(
    r"C[ÓO]DIGO DA INSTALA[ÇC][ÃA]O\s*\n\s*.+?\s+(\d{4,10})\s+NOTA FISCAL",
    re.IGNORECASE | re.DOTALL,
)
_RE_CODIGO_INSTALACAO_COID = re.compile(
    r"COID\s+(\d{4,10})",
    re.IGNORECASE,
)
_RE_CNPJ_MASCARADO = re.compile(_CNPJ_MASCARADO, re.IGNORECASE)
_RE_CNPJ_MASCARADO_CAPTURA = re.compile(rf"({_CNPJ_MASCARADO})", re.IGNORECASE)
_RE_CODIGO_CLIENTE_EXPLICITO = re.compile(
    r"C[ÓO]DIGO\s+DO\s+CLIENTE\s+(\d{6,12})",
    re.IGNORECASE,
)
_RE_CODIGO_CLIENTE_ENDERECO = re.compile(
    r"\d{5}-\d{3}\s+[A-ZÁÉÍÓÚÇÃÕÂÊÔ\s]+\s+RN\s+(\d{6,12})",
    re.IGNORECASE,
)
_RE_CODIGO_CLIENTE_RODAPE = re.compile(
    r"^(\d{6,12})\s+\d{2}/\d{2}/\d{4}\s+[\d.,]+",
    re.MULTILINE,
)
_RE_NUMERO_UC = re.compile(
    r"(?:N[°º]?\s*(?:da\s+)?Unidade Consumidora|UC)\s*[:\s]+(\d{4,15})",
    re.IGNORECASE,
)
_RE_CLASSIFICACAO_A = re.compile(
    r"CLASSIFICA[ÇC][ÃA]O\s*:\s*(A\d+[A-Za-z]?)\s+(.+?)(?:\n\s*TIPO DE FORNECIMENTO|\n)",
    re.IGNORECASE | re.DOTALL,
)
_RE_CLASSIFICACAO_B = re.compile(
    r"CLASSIFICA[ÇC][ÃA]O\s*:\s*(B\d+[A-Za-z]?)\s+(.+?)\s+TIPO DE FORNECIMENTO\s*:\s*(.+?)(?:\n|Cadastra)",
    re.IGNORECASE | re.DOTALL,
)
_RE_PODER_PUBLICO = re.compile(
    r"PODER\s+PUBLICO\s*[-–]?\s*(ESTADUAL|DISTRITAL|MUNICIPAL)[^\n]*",
    re.IGNORECASE,
)
_RE_NOME_CLIENTE = re.compile(
    r"NOME DO CLIENTE:\s*\n(.+?)\n",
    re.IGNORECASE,
)
_RE_BLOCO_ENDERECO = re.compile(
    r"ENDERE[ÇC]O\s*:\s*(.*?)(?:REF\s*:\s*M[EÊ]S/ANO|CLASSIFICA[ÇC][ÃA]O\s*:)",
    re.IGNORECASE | re.DOTALL,
)
_RE_BAIRRO_LINHA = re.compile(
    r"^([A-Z0-9ÁÉÍÓÚÇÃÕÂÊÎÔÛ\s.\-]+/(?:AREA\s+)?(?:URBANA|RURAL))"
    r"(?:\s+\d{4,12})?",
    re.IGNORECASE,
)
_RE_LOGRADOURO = re.compile(
    r"^(RUA|AV\.?|AVENIDA|LG\.?|LARGO|ROD\.?|RODOVIA|EST|ESTRADA|ALAMEDA|TRAVESSA|VIA|BR\.?|TV\.?)\b",
    re.IGNORECASE,
)
_RE_NOME_LOCAL_CODIGO = re.compile(
    r"^(.+?)\s+C[ÓO]DIGO\s+DO\s+CLIENTE",
    re.MULTILINE | re.IGNORECASE,
)
_RE_CODIGO_CLIENTE_BAIRRO = re.compile(
    r"/(?:AREA\s+)?(?:URBANA|RURAL)\s+(\d{4,12})",
    re.IGNORECASE,
)
_RE_CEP = re.compile(r"(\d{5}-\d{3})\s+[A-ZÁÉÍÓÚÇÃÕÂÊÔ\s]+\s+RN", re.IGNORECASE)
_RE_NOTA_FISCAL = re.compile(
    r"NOTA FISCAL N[°º]?\s*(\d+)\s*-\s*S[ÉE]RIE\s*(\d+)\s*/\s*DATA DE EMISS[ÃA]O:\s*(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)
_RE_CHAVE_ACESSO = re.compile(
    r"(\d{4}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{2})"
)
_RE_PROTOCOLO = re.compile(
    r"Protocolo de autoriza[çc][ãa]o:\s*(\S+)\s*-\s*(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)
_RE_CLASSIFICACAO_COMPLETA = re.compile(
    r"CLASSIFICA[ÇC][ÃA]O\s*:\s*([AB]\d+[A-Za-z]?)\s+(.+?)(?:\s+TIPO DE FORNECIMENTO|\n)",
    re.IGNORECASE | re.DOTALL,
)
_RE_TIPO_FORNECIMENTO = re.compile(
    r"TIPO DE FORNECIMENTO:\s*(.+?)(?:\n|PODER PUBLICO)",
    re.IGNORECASE,
)
_RE_REF_BLOCO = re.compile(
    r"REF\s*:\s*M[EÊ]S/ANO[^\n]*\n\s*(\d{2}/\d{4})\s+([\d.,]+)\s+(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)
_RE_LEITURAS = re.compile(
    r"LEITURA ANTERIOR\s+(\d{2}/\d{2}/\d{4})\s+LEITURA ATUAL\s+(\d{2}/\d{2}/\d{4})"
    r"\s+N[°º]?\s*DE\s*DIAS\s+(\d+)\s+PR[ÓO]XIMA LEITURA\s+(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)
_RE_CONTA_COLETIVA = re.compile(
    r"Conta Contrato Coletiva n[°º]?\s*(\d+)",
    re.IGNORECASE,
)
_RE_DOC_PAGAMENTO = re.compile(
    r"Doc\.\s*Pgto\.\s*n[°º]?\s*(\d+)",
    re.IGNORECASE,
)
_RE_BANDEIRA = re.compile(
    r"bandeira em vigor [ée]\s+a\s+(\w+)",
    re.IGNORECASE,
)
_RE_TOTAL_ITENS = re.compile(
    r"^TOTAL\s+([\d.,]+)(?:\s|$)", re.MULTILINE | re.IGNORECASE
)

_RE_TRIBUTO = re.compile(
    r"^(PIS|COFINS|ICMS)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s*$",
    re.MULTILINE | re.IGNORECASE,
)

_RE_MEDIDOR = re.compile(
    r"(\d{8,12})\s+"
    r"(Energia Ativa Ponta|Energia Ativa Fora Ponta|Demanda Ativa Ponta|"
    r"Demanda Ativa Fora Ponta|Energia Ativa [ÚU]nico|Energia Reativa [ÚU]nico)\s+"
    r"([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)",
    re.IGNORECASE,
)

_RE_PERDA_TRANSFORMACAO = re.compile(
    r"Perda de Transforma[çc][ãa]o de\s+([\d.,]+)\s*%",
    re.IGNORECASE,
)
_RE_FATOR_POTENCIA = re.compile(
    r"Fator de Pot[êe]ncia M[ée]dio\s*=\s*([\d.,]+)",
    re.IGNORECASE,
)
_RE_GRUPO_A = re.compile(r"^A", re.IGNORECASE)


def _eh_horario_azul(descricao: str) -> bool:
    return "azul" in descricao.lower()


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------


from services.numeros import parse_numero_brasileiro


def _primeiro_match(padrao: re.Pattern[str], texto: str) -> str | None:
    match = padrao.search(texto)
    return match.group(1).strip() if match else None


def _inferir_grupo(classificacao: str | None) -> GrupoTarifario:
    if classificacao and _RE_GRUPO_A.match(classificacao):
        return "A"
    return "B"


def _valor_ou_vazio(valor: float | None) -> str:
    if valor is None:
        return ""
    return str(valor)


def _limpar_texto(raw: str | None) -> str:
    if not raw:
        return ""
    return re.sub(r"\s+", " ", raw.strip())


def _item_quantidade_valor(
    texto: str,
    rotulo: str,
    unidade: str | None = None,
) -> tuple[float | None, float | None]:
    """Extrai quantidade e valor de linha de item (Demanda, Consumo-TUSD, etc.)."""
    uni = rf"{re.escape(unidade)}\s+" if unidade else ""
    padrao = re.compile(
        rf"{rotulo}\s+{uni}([\d.,]+)\s+[\d.,]+\s+([\d.,]+-?)",
        re.IGNORECASE,
    )
    match = padrao.search(texto)
    if not match:
        return None, None
    return (
        parse_numero_brasileiro(match.group(1)),
        parse_numero_brasileiro(match.group(2)),
    )


def _item_valor_simples(texto: str, rotulo: str) -> float | None:
    padrao = re.compile(rf"{rotulo}\s+([\d.,]+-?)", re.IGNORECASE)
    match = padrao.search(texto)
    return parse_numero_brasileiro(match.group(1)) if match else None


def _resolver_nome_arquivo(fonte: PdfSource) -> str:
    if isinstance(fonte, (str, Path)):
        return str(Path(fonte).name)
    if hasattr(fonte, "name") and getattr(fonte, "name", None):
        return Path(str(fonte.name)).name
    return "<stream>"


def _abrir_pdf(fonte: PdfSource) -> pdfplumber.PDF:
    if isinstance(fonte, bytes):
        return pdfplumber.open(BytesIO(fonte))
    if isinstance(fonte, (str, Path)):
        caminho = Path(fonte)
        if not caminho.is_file():
            raise FileNotFoundError(f"Arquivo PDF não encontrado: {caminho}")
        return pdfplumber.open(caminho)
    if hasattr(fonte, "read"):
        if hasattr(fonte, "seek"):
            fonte.seek(0)
        return pdfplumber.open(fonte)
    raise TypeError(f"Tipo de fonte não suportado: {type(fonte)!r}")


# ---------------------------------------------------------------------------
# Validação de página e identificadores
# ---------------------------------------------------------------------------


def _pagina_e_fatura_valida(texto: str) -> bool:
    if not re.search(KEYWORD_PAGINA_VALIDA, texto, re.IGNORECASE):
        return False
    if not _RE_CLASSIFICACAO_COMPLETA.search(texto):
        return False
    if not _RE_REF_BLOCO.search(texto):
        return False
    tem_itens = "ITENS DA FATURA" in texto.upper()
    tem_consumo_b = "CONSUMO / KWH" in texto.upper()
    tem_demonstrativo = "DEMONSTRATIVO DE CONSUMO" in texto.upper()
    if tem_demonstrativo and not tem_itens and not tem_consumo_b:
        return False
    if not tem_itens and not tem_consumo_b:
        return False
    return True


def _extrair_texto_cabecalho(page: Page) -> str:
    try:
        altura = min(HEADER_CROP_HEIGHT_PT, page.height)
        return page.crop((0, 0, page.width, altura)).extract_text(
            x_tolerance=2, y_tolerance=2
        ) or ""
    except Exception:
        logger.exception("Erro no crop do cabeçalho (página %s)", page.page_number)
        return ""


def _extrair_codigo_instalacao_geometrico(page: Page) -> str | None:
    try:
        palavras = page.extract_words(x_tolerance=2, y_tolerance=2)
    except Exception:
        return None

    # Padrão 1: à direita do CNPJ mascarado na mesma linha
    for palavra in palavras:
        if not _RE_CNPJ_MASCARADO.search(palavra["text"]):
            continue
        y_ref = palavra["top"]
        candidatos = [
            p
            for p in palavras
            if abs(p["top"] - y_ref) < 6
            and p["x0"] > palavra["x0"]
            and re.fullmatch(r"\d{4,10}", p["text"])
        ]
        if candidatos:
            return min(candidatos, key=lambda p: p["x0"])["text"]

    # Padrão 2: linha abaixo do rótulo CÓDIGO DA INSTALAÇÃO (layout alternativo)
    rotulo_y: float | None = None
    for palavra in palavras:
        if re.search(r"INSTALA", palavra["text"], re.I):
            rotulo_y = palavra["top"]
            break
    if rotulo_y is not None:
        candidatos_rotulo = [
            p
            for p in palavras
            if rotulo_y - 2 <= p["top"] <= rotulo_y + 14
            and re.fullmatch(r"\d{4,10}", p["text"])
        ]
        if candidatos_rotulo:
            return min(candidatos_rotulo, key=lambda p: p["x0"])["text"]

    return None


def _extrair_codigo_instalacao(page: Page, texto: str, cabecalho: str) -> str | None:
    for bloco in (cabecalho, texto):
        for padrao in (
            _RE_CODIGO_INSTALACAO_MASCARADO,
            _RE_CODIGO_INSTALACAO_ANTES_NF,
            _RE_CODIGO_INSTALACAO_COID,
        ):
            codigo = _primeiro_match(padrao, bloco)
            if codigo:
                return codigo
    return _extrair_codigo_instalacao_geometrico(page)


def _extrair_chave_acesso(texto: str) -> str:
    match = _RE_CHAVE_ACESSO.search(texto)
    if match:
        return re.sub(r"\s+", "", match.group(1))

    idx = texto.lower().find("chave de acesso")
    if idx >= 0:
        trecho = texto[idx : idx + 220]
        digitos = re.sub(r"\D", "", trecho)
        if len(digitos) >= 44:
            return digitos[:44]

    for candidato in re.findall(r"(?<!\d)(\d{44})(?!\d)", re.sub(r"\s+", "", texto)):
        return candidato

    return ""


def _extrair_numero_uc(texto: str) -> str:
    """UC só quando explícita na fatura; concessionária ainda não informa na maioria."""
    return _limpar_texto(_primeiro_match(_RE_NUMERO_UC, texto))


def _extrair_bloco_endereco(texto: str) -> tuple[str, str, str]:
    """
    Extrai logradouro, nome do local e bairro do bloco ENDEREÇO da DANFE.

    Layout Neoenergia típico::
        RUA ...                    → endereco
        UNIDADE_LOCAL              → nome_local (opcional)
        LAGOA NOVA/AREA URBANA     → bairro
    """
    match = _RE_BLOCO_ENDERECO.search(texto)
    if not match:
        return "", "", ""

    bloco = match.group(1)
    bairro = ""
    for linha in bloco.split("\n"):
        linha = linha.strip()
        if not linha or linha.lower().startswith("http") or "//" in linha:
            continue
        match_bairro = _RE_BAIRRO_LINHA.match(linha)
        if match_bairro:
            bairro = _limpar_texto(match_bairro.group(1))
            break

    nome_local = ""
    nome_codigo = _RE_NOME_LOCAL_CODIGO.search(bloco)
    if nome_codigo:
        candidato = _limpar_texto(nome_codigo.group(1))
        if candidato and not _RE_LOGRADOURO.match(candidato):
            nome_local = candidato

    endereco = ""
    linhas = [
        linha.strip()
        for linha in bloco.split("\n")
        if linha.strip()
        and not linha.strip().lower().startswith("http")
        and "consulte" not in linha.lower()
        and "chave de acesso" not in linha.lower()
        and "protocolo" not in linha.lower()
    ]

    for linha in linhas:
        if _RE_LOGRADOURO.match(linha):
            endereco = _limpar_texto(linha)
            break

    if not nome_local:
        for linha in linhas:
            if linha == endereco or _RE_BAIRRO_LINHA.match(linha):
                continue
            if re.match(r"^\d{5}-\d{3}", linha):
                continue
            if re.search(r"C[ÓO]DIGO\s+DO\s+CLIENTE", linha, re.I):
                parte = re.split(r"C[ÓO]DIGO\s+DO\s+CLIENTE", linha, flags=re.I)[0].strip()
                if parte and not _RE_LOGRADOURO.match(parte) and not _RE_BAIRRO_LINHA.match(parte):
                    nome_local = _limpar_texto(parte)
                continue
            if not _RE_LOGRADOURO.match(linha):
                nome_local = _limpar_texto(linha)
                break

    return endereco, nome_local, bairro


def _extrair_codigo_cliente(texto: str, cabecalho: str) -> str | None:
    for bloco in (texto, cabecalho):
        for padrao in (
            _RE_CODIGO_CLIENTE_BAIRRO,
            _RE_CODIGO_CLIENTE_EXPLICITO,
            _RE_CODIGO_CLIENTE_ENDERECO,
            _RE_CODIGO_CLIENTE_RODAPE,
        ):
            codigo = _primeiro_match(padrao, bloco)
            if codigo:
                return codigo
    return None


# ---------------------------------------------------------------------------
# Campos universais (identificação, NF, leituras, tributos)
# ---------------------------------------------------------------------------


def _extrair_identificacao(texto: str, cabecalho: str) -> dict[str, str]:
    endereco, nome_local, bairro = _extrair_bloco_endereco(texto)
    protocolo = _RE_PROTOCOLO.search(texto)

    return {
        "numero_uc": "",
        "nome_cliente": _limpar_texto(_primeiro_match(_RE_NOME_CLIENTE, texto)),
        "endereco": endereco,
        "nome_local": nome_local,
        "bairro": bairro,
        "cep": _primeiro_match(_RE_CEP, texto) or "",
        "cnpj_tomador_mascarado": _primeiro_match(_RE_CNPJ_MASCARADO_CAPTURA, texto) or "",
        "nota_fiscal": "",
        "serie_nf": "",
        "data_emissao": "",
        "protocolo_autorizacao": (
            f"{protocolo.group(1)} - {protocolo.group(2)}" if protocolo else ""
        ),
        "chave_acesso": _extrair_chave_acesso(texto),
    }


def _extrair_nota_fiscal(texto: str) -> dict[str, str]:
    match = _RE_NOTA_FISCAL.search(texto)
    if not match:
        return {}
    return {
        "nota_fiscal": match.group(1),
        "serie_nf": match.group(2),
        "data_emissao": match.group(3),
    }


def _normalizar_poder_publico(texto: str) -> str:
    match = _RE_PODER_PUBLICO.search(texto)
    if not match:
        return ""
    # Reconstrói texto legível a partir do trecho capturado
    trecho = match.group(0)
    trecho = re.sub(r"\s+", " ", trecho.strip())
    trecho = re.sub(r"\s*-\s*", " - ", trecho)
    return _limpar_texto(trecho)


def _extrair_tarifa(texto: str) -> dict[str, str]:
    poder_publico = _normalizar_poder_publico(texto)
    tipo = _limpar_texto(_primeiro_match(_RE_TIPO_FORNECIMENTO, texto))

    match_a = _RE_CLASSIFICACAO_A.search(texto)
    if match_a:
        classificacao = re.sub(r"\s+", "", match_a.group(1).upper())
        modalidade = _limpar_texto(match_a.group(2))
        return {
            "grupo": "A",
            "classificacao": classificacao,
            "classificacao_descricao": poder_publico,
            "tipo_fornecimento": tipo,
            "modalidade_tarifaria": modalidade,
        }

    match_b = _RE_CLASSIFICACAO_B.search(texto)
    if match_b:
        classificacao = re.sub(r"\s+", "", match_b.group(1).upper())
        subclasse = _limpar_texto(match_b.group(2))
        tipo_b = _limpar_texto(match_b.group(3))
        descricao = subclasse if subclasse else poder_publico
        return {
            "grupo": "B",
            "classificacao": classificacao,
            "classificacao_descricao": descricao,
            "tipo_fornecimento": tipo_b,
            "modalidade_tarifaria": tipo_b,
        }

    # Fallback legado
    match = _RE_CLASSIFICACAO_COMPLETA.search(texto)
    classificacao = re.sub(r"\s+", "", match.group(1).upper()) if match else ""
    grupo = _inferir_grupo(classificacao)
    return {
        "grupo": grupo,
        "classificacao": classificacao,
        "classificacao_descricao": poder_publico,
        "tipo_fornecimento": tipo,
        "modalidade_tarifaria": "",
    }


def _extrair_faturamento(texto: str) -> dict[str, str]:
    ref = _RE_REF_BLOCO.search(texto)
    total_itens = _primeiro_match(_RE_TOTAL_ITENS, texto)
    return {
        "mes_referencia": ref.group(1) if ref else "",
        "valor_total": _valor_ou_vazio(
            parse_numero_brasileiro(ref.group(2)) if ref else None
        ),
        "data_vencimento": ref.group(3) if ref else "",
        "total_itens_fatura": _valor_ou_vazio(parse_numero_brasileiro(total_itens)),
        "bandeira_tarifaria": _limpar_texto(_primeiro_match(_RE_BANDEIRA, texto)),
    }


def _extrair_leituras(texto: str) -> dict[str, str]:
    match = _RE_LEITURAS.search(texto)
    if not match:
        return {
            "leitura_anterior": "",
            "leitura_atual": "",
            "dias_faturados": "",
            "proxima_leitura": "",
        }
    return {
        "leitura_anterior": match.group(1),
        "leitura_atual": match.group(2),
        "dias_faturados": match.group(3),
        "proxima_leitura": match.group(4),
    }


def _extrair_coletiva(texto: str) -> dict[str, str]:
    medidor = ""
    for match in _RE_MEDIDOR.finditer(texto):
        medidor = match.group(1)
        break
    return {
        "conta_coletiva": _primeiro_match(_RE_CONTA_COLETIVA, texto) or "",
        "documento_pagamento": _primeiro_match(_RE_DOC_PAGAMENTO, texto) or "",
        "numero_medidor": medidor,
    }


def _extrair_tributos(texto: str) -> dict[str, str]:
    resultado = {
        "pis_base": "",
        "pis_aliquota_pct": "",
        "pis_valor": "",
        "cofins_base": "",
        "cofins_aliquota_pct": "",
        "cofins_valor": "",
        "icms_base": "",
        "icms_aliquota_pct": "",
        "icms_valor": "",
    }
    prefixos = {"PIS": "pis", "COFINS": "cofins", "ICMS": "icms"}
    for match in _RE_TRIBUTO.finditer(texto):
        nome = match.group(1).upper()
        prefixo = prefixos.get(nome)
        if not prefixo:
            continue
        resultado[f"{prefixo}_base"] = _valor_ou_vazio(
            parse_numero_brasileiro(match.group(2))
        )
        resultado[f"{prefixo}_aliquota_pct"] = _valor_ou_vazio(
            parse_numero_brasileiro(match.group(3))
        )
        resultado[f"{prefixo}_valor"] = _valor_ou_vazio(
            parse_numero_brasileiro(match.group(4))
        )
    return resultado


def _extrair_encargos(texto: str) -> dict[str, str]:
    return {
        "iluminacao_publica_valor": _valor_ou_vazio(
            _item_valor_simples(texto, r"Ilum\.\s*P[uú]b\.\s*Municipal")
        ),
        "acrescimo_bandeira_valor": _valor_ou_vazio(
            _item_valor_simples(texto, r"Acr[eé]s\.\s*Band\.\s*(?:AMARELA|VERMELHA(?: P1|P2)?)")
        ),
        "trib_irrf_1_2_valor": _valor_ou_vazio(
            _item_valor_simples(texto, r"TRIBF-IRRF\(1\.2%\)")
        ),
        "trib_irrf_4_8_valor": _valor_ou_vazio(
            _item_valor_simples(texto, r"TRIBF-IRRF\(4\.8%\)")
        ),
    }


def _parse_medidor(texto: str) -> dict[str, dict[str, float | None]]:
    """Indexa linhas da tabela MEDIDOR por tipo de grandeza."""
    mapa: dict[str, dict[str, float | None]] = {}

    def _classificar_grandeza(tipo_raw: str) -> str | None:
        t = tipo_raw.lower().replace("ú", "u").replace("ó", "o")
        if "energia ativa" in t and "fora" in t:
            return "energia_fponta"
        if "energia ativa" in t and "ponta" in t:
            return "energia_ponta"
        if "demanda ativa" in t and "fora" in t:
            return "demanda_fponta"
        if "demanda ativa" in t and "ponta" in t:
            return "demanda_ponta"
        if "energia ativa" in t and "unico" in t:
            return "energia_unico"
        if "energia reativa" in t and "unico" in t:
            return "reativa_unico"
        return None

    for match in _RE_MEDIDOR.finditer(texto):
        chave = _classificar_grandeza(match.group(2))
        if not chave:
            continue
        mapa[chave] = {
            "leit_ant": parse_numero_brasileiro(match.group(3)),
            "leit_atual": parse_numero_brasileiro(match.group(4)),
            "constante": parse_numero_brasileiro(match.group(5)),
            "consumo": parse_numero_brasileiro(match.group(6)),
        }
    return mapa


# ---------------------------------------------------------------------------
# Grupo A — demanda + consumo ponta / fora ponta
# ---------------------------------------------------------------------------


def _campos_comuns_grupo_a(texto: str, med: dict) -> dict[str, str]:
    """Campos compartilhados entre modalidades Verde e Azul."""
    ct_p_q, ct_p_v = _item_quantidade_valor(texto, r"Consumo-TUSD NPonta", "kWh")
    ct_f_q, ct_f_v = _item_quantidade_valor(texto, r"Consumo-TUSD F\.Ponta", "kWh")
    ce_p_q, ce_p_v = _item_quantidade_valor(texto, r"Consumo-TE Na Ponta", "kWh")
    ce_f_q, ce_f_v = _item_quantidade_valor(texto, r"Consumo-TE F\.Ponta", "kWh")
    cr_p_q, cr_p_v = _item_quantidade_valor(texto, r"Cons\.Reat\.Exc\.NPonta", "kVARh")
    cr_f_q, cr_f_v = _item_quantidade_valor(texto, r"Cons\.Reat Exc\.FPonta", "kVARh")

    ep = med.get("energia_ponta", {})
    ef = med.get("energia_fponta", {})
    dp = med.get("demanda_ponta", {})
    df = med.get("demanda_fponta", {})

    return {
        "demanda_medida_ponta_kw": _valor_ou_vazio(dp.get("consumo")),
        "demanda_medida_fponta_kw": _valor_ou_vazio(df.get("consumo")),
        "consumo_ponta_kwh": _valor_ou_vazio(ep.get("consumo")),
        "consumo_fponta_kwh": _valor_ou_vazio(ef.get("consumo")),
        "consumo_tusd_ponta_kwh": _valor_ou_vazio(ct_p_q),
        "consumo_tusd_ponta_valor": _valor_ou_vazio(ct_p_v),
        "consumo_tusd_fponta_kwh": _valor_ou_vazio(ct_f_q),
        "consumo_tusd_fponta_valor": _valor_ou_vazio(ct_f_v),
        "consumo_te_ponta_kwh": _valor_ou_vazio(ce_p_q),
        "consumo_te_ponta_valor": _valor_ou_vazio(ce_p_v),
        "consumo_te_fponta_kwh": _valor_ou_vazio(ce_f_q),
        "consumo_te_fponta_valor": _valor_ou_vazio(ce_f_v),
        "consumo_reat_exc_ponta_kvarh": _valor_ou_vazio(cr_p_q),
        "consumo_reat_exc_ponta_valor": _valor_ou_vazio(cr_p_v),
        "consumo_reat_exc_fponta_kvarh": _valor_ou_vazio(cr_f_q),
        "consumo_reat_exc_fponta_valor": _valor_ou_vazio(cr_f_v),
        "medidor_en_ponta_leit_ant": _valor_ou_vazio(ep.get("leit_ant")),
        "medidor_en_ponta_leit_atual": _valor_ou_vazio(ep.get("leit_atual")),
        "medidor_en_ponta_constante": _valor_ou_vazio(ep.get("constante")),
        "medidor_en_fponta_leit_ant": _valor_ou_vazio(ef.get("leit_ant")),
        "medidor_en_fponta_leit_atual": _valor_ou_vazio(ef.get("leit_atual")),
        "medidor_en_fponta_constante": _valor_ou_vazio(ef.get("constante")),
        "medidor_dem_ponta_leit_ant": _valor_ou_vazio(dp.get("leit_ant")),
        "medidor_dem_ponta_leit_atual": _valor_ou_vazio(dp.get("leit_atual")),
        "medidor_dem_fponta_leit_ant": _valor_ou_vazio(df.get("leit_ant")),
        "medidor_dem_fponta_leit_atual": _valor_ou_vazio(df.get("leit_atual")),
        "demanda_ponta": _valor_ou_vazio(dp.get("consumo")),
        "demanda_fponta": _valor_ou_vazio(df.get("consumo")),
        "consumo_ponta": _valor_ou_vazio(ep.get("consumo")),
        "consumo_fponta": _valor_ou_vazio(ef.get("consumo")),
    }


def _extrair_grupo_a_verde(texto: str, med: dict) -> dict[str, str]:
    """A4 Horo-sazonal Verde — demanda contratada única."""
    dem_kw, dem_val = _item_quantidade_valor(
        texto, r"Demanda Ativa(?!\s*(?:NPonta|FPonta|-))", "kW"
    )
    dem_reat_q, dem_reat_v = _item_quantidade_valor(
        texto, r"Demanda Reativa Exc\.", "kVAr"
    )
    dem_ultra_q, dem_ultra_v = _item_quantidade_valor(
        texto, r"Demanda Ativa-\s*Lim", "kW"
    )
    demanda_contratada = parse_numero_brasileiro(
        _primeiro_match(
            re.compile(r"Demanda Contratada(?!\s*(?:NP|FP))\s+(\d+(?:[.,]\d+)?)", re.I),
            texto,
        )
    )

    return {
        **_campos_comuns_grupo_a(texto, med),
        "demanda_contratada_kw": _valor_ou_vazio(demanda_contratada),
        "demanda_faturada_kw": _valor_ou_vazio(dem_kw),
        "demanda_faturada_valor": _valor_ou_vazio(dem_val),
        "demanda_reativa_exc_kvar": _valor_ou_vazio(dem_reat_q),
        "demanda_reativa_exc_valor": _valor_ou_vazio(dem_reat_v),
        "demanda_ultrapassagem_kw": _valor_ou_vazio(dem_ultra_q),
        "demanda_ultrapassagem_valor": _valor_ou_vazio(dem_ultra_v),
        "demanda_contratada": _valor_ou_vazio(demanda_contratada),
    }


def _extrair_grupo_a_azul(texto: str, med: dict) -> dict[str, str]:
    """A4 Horo-sazonal Azul — demandas contratadas e faturadas NP + FP."""
    dem_np_q, dem_np_v = _item_quantidade_valor(texto, r"Demanda Ativa NPonta", "kW")
    dem_fp_q, dem_fp_v = _item_quantidade_valor(texto, r"Demanda Ativa FPonta", "kW")
    dem_reat_np_q, dem_reat_np_v = _item_quantidade_valor(
        texto, r"Dem\.Reat\.Exc\.\s*NPonta", "kVAr"
    )
    dem_reat_fp_q, dem_reat_fp_v = _item_quantidade_valor(
        texto, r"Dem\.\s*Reativa Exc\.\s*FP", "kVAr"
    )
    dem_ultra_np_q, dem_ultra_np_v = _item_quantidade_valor(
        texto, r"Demanda Na Ponta Lim", "kW"
    )
    dem_ultra_fp_q, dem_ultra_fp_v = _item_quantidade_valor(
        texto, r"Dem\.\s*Fora Ponta-Lim", "kW"
    )

    contratada_np = parse_numero_brasileiro(
        _primeiro_match(re.compile(r"Demanda Contratada NP\s+(\d+(?:[.,]\d+)?)", re.I), texto)
    )
    contratada_fp = parse_numero_brasileiro(
        _primeiro_match(re.compile(r"Demanda Contratada FP\s+(\d+(?:[.,]\d+)?)", re.I), texto)
    )

    return {
        **_campos_comuns_grupo_a(texto, med),
        "demanda_contratada_np_kw": _valor_ou_vazio(contratada_np),
        "demanda_contratada_fp_kw": _valor_ou_vazio(contratada_fp),
        "demanda_contratada_kw": _valor_ou_vazio(contratada_fp),
        "demanda_faturada_np_kw": _valor_ou_vazio(dem_np_q),
        "demanda_faturada_fp_kw": _valor_ou_vazio(dem_fp_q),
        "demanda_faturada_np_valor": _valor_ou_vazio(dem_np_v),
        "demanda_faturada_fp_valor": _valor_ou_vazio(dem_fp_v),
        "demanda_reativa_exc_np_kvar": _valor_ou_vazio(dem_reat_np_q),
        "demanda_reativa_exc_fp_kvar": _valor_ou_vazio(dem_reat_fp_q),
        "demanda_reativa_exc_np_valor": _valor_ou_vazio(dem_reat_np_v),
        "demanda_reativa_exc_fp_valor": _valor_ou_vazio(dem_reat_fp_v),
        "demanda_ultrapassagem_np_kw": _valor_ou_vazio(dem_ultra_np_q),
        "demanda_ultrapassagem_fp_kw": _valor_ou_vazio(dem_ultra_fp_q),
        "demanda_ultrapassagem_np_valor": _valor_ou_vazio(dem_ultra_np_v),
        "demanda_ultrapassagem_fp_valor": _valor_ou_vazio(dem_ultra_fp_v),
        "demanda_contratada": _valor_ou_vazio(contratada_fp),
    }


def _extrair_grupo_a(texto: str, descricao: str) -> dict[str, str]:
    med = _parse_medidor(texto)
    if _eh_horario_azul(descricao):
        return _extrair_grupo_a_azul(texto, med)
    return _extrair_grupo_a_verde(texto, med)


# ---------------------------------------------------------------------------
# Grupo B — consumo monômico (sem postos ponta/fora ponta)
# ---------------------------------------------------------------------------


def _extrair_te_b_por_bandeira(texto: str) -> dict[str, str]:
    """B3 com Consumo-TE dividido por bandeira tarifária (Amarela/Verde)."""
    resultado: dict[str, str] = {
        "consumo_te_kwh_amarela": "",
        "consumo_te_valor_amarela": "",
        "consumo_te_kwh_verde": "",
        "consumo_te_valor_verde": "",
    }
    mapa = {
        "AMARELA": ("consumo_te_kwh_amarela", "consumo_te_valor_amarela"),
        "VERDE": ("consumo_te_kwh_verde", "consumo_te_valor_verde"),
    }
    for bandeira, (campo_q, campo_v) in mapa.items():
        padrao = re.compile(
            rf"BANDEIRA\s+{bandeira}[\s\S]{{0,500}}?"
            rf"Consumo-TE kWh\s+([\d.,]+)\s+[\d.,]+\s+([\d.,]+-?)",
            re.IGNORECASE,
        )
        match = padrao.search(texto)
        if match:
            resultado[campo_q] = _valor_ou_vazio(parse_numero_brasileiro(match.group(1)))
            resultado[campo_v] = _valor_ou_vazio(parse_numero_brasileiro(match.group(2)))
    return resultado


def _extrair_informacoes(texto: str) -> dict[str, str]:
    return {
        "perda_transformacao_pct": _valor_ou_vazio(
            parse_numero_brasileiro(_primeiro_match(_RE_PERDA_TRANSFORMACAO, texto))
        ),
        "fator_potencia_medio": _valor_ou_vazio(
            parse_numero_brasileiro(_primeiro_match(_RE_FATOR_POTENCIA, texto))
        ),
    }


def _extrair_grupo_b(texto: str) -> dict[str, str]:
    med = _parse_medidor(texto)
    eu = med.get("energia_unico", {})
    ru = med.get("reativa_unico", {})

    ct_q, ct_v = _item_quantidade_valor(texto, r"Consumo-TUSD", "kWh")
    te_split = _extrair_te_b_por_bandeira(texto)
    cr_q, cr_v = _item_quantidade_valor(texto, r"Cons\.Reat\.Excedente", "kVARh")

    ce_q, ce_v = _item_quantidade_valor(texto, r"Consumo-TE", "kWh")
    if te_split["consumo_te_kwh_amarela"] and te_split["consumo_te_kwh_verde"]:
        q_am = parse_numero_brasileiro(te_split["consumo_te_kwh_amarela"]) or 0
        q_vd = parse_numero_brasileiro(te_split["consumo_te_kwh_verde"]) or 0
        v_am = parse_numero_brasileiro(te_split["consumo_te_valor_amarela"]) or 0
        v_vd = parse_numero_brasileiro(te_split["consumo_te_valor_verde"]) or 0
        ce_q = q_am + q_vd
        ce_v = v_am + v_vd

    consumo = eu.get("consumo")
    if consumo is None:
        consumo = parse_numero_brasileiro(
            _primeiro_match(
                re.compile(
                    r"CONSUMO\s+FATURADO[\s\S]{0,120}?(?:[A-Z]{3}\d{2}\s+)(\d[\d.,]*)",
                    re.I,
                ),
                texto,
            )
        )

    return {
        "consumo_unico_kwh": _valor_ou_vazio(consumo),
        "consumo_tusd_kwh": _valor_ou_vazio(ct_q),
        "consumo_tusd_valor": _valor_ou_vazio(ct_v),
        "consumo_te_kwh": _valor_ou_vazio(ce_q),
        "consumo_te_valor": _valor_ou_vazio(ce_v),
        **te_split,
        "consumo_reat_excedente_kvarh": _valor_ou_vazio(cr_q),
        "consumo_reat_excedente_valor": _valor_ou_vazio(cr_v),
        "energia_reativa_unico_kwh": _valor_ou_vazio(ru.get("consumo")),
        "medidor_en_leit_ant": _valor_ou_vazio(eu.get("leit_ant")),
        "medidor_en_leit_atual": _valor_ou_vazio(eu.get("leit_atual")),
        "medidor_en_constante": _valor_ou_vazio(eu.get("constante")),
        "medidor_reat_leit_ant": _valor_ou_vazio(ru.get("leit_ant")),
        "medidor_reat_leit_atual": _valor_ou_vazio(ru.get("leit_atual")),
        "medidor_reat_constante": _valor_ou_vazio(ru.get("constante")),
        "demanda_contratada": "0.0",
        "demanda_ponta": "0.0",
        "demanda_fponta": "0.0",
        "consumo_ponta": "0.0",
        "consumo_fponta": "0.0",
    }


# ---------------------------------------------------------------------------
# Orquestração por página
# ---------------------------------------------------------------------------


def _extrair_pagina(
    page: Page,
    numero_pagina: int,
    arquivo_origem: str,
) -> dict[str, str] | None:
    try:
        texto = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
    except Exception:
        logger.exception("Erro ao extrair texto da página %d", numero_pagina)
        return None

    if not _pagina_e_fatura_valida(texto):
        return None

    cabecalho = _extrair_texto_cabecalho(page)
    codigo_instalacao = _extrair_codigo_instalacao(page, texto, cabecalho)
    if not codigo_instalacao:
        logger.warning(
            "Página %d de %s descartada: código de instalação ausente.",
            numero_pagina,
            arquivo_origem,
        )
        return None

    fatura = campos_vazios()
    fatura.update(_extrair_identificacao(texto, cabecalho))
    fatura.update(_extrair_nota_fiscal(texto))
    fatura.update(_extrair_tarifa(texto))
    fatura.update(_extrair_faturamento(texto))
    fatura.update(_extrair_leituras(texto))
    fatura.update(_extrair_coletiva(texto))
    fatura.update(_extrair_tributos(texto))
    fatura.update(_extrair_encargos(texto))
    fatura.update(_extrair_informacoes(texto))

    fatura["codigo_instalacao"] = codigo_instalacao
    fatura["codigo_cliente"] = _extrair_codigo_cliente(texto, cabecalho) or ""
    fatura["numero_uc"] = _extrair_numero_uc(texto)

    if fatura["grupo"] == "A":
        fatura.update(
            _extrair_grupo_a(texto, fatura.get("modalidade_tarifaria", ""))
        )
    else:
        fatura.update(_extrair_grupo_b(texto))

    from services.colunas_dinamicas import aplicar_itens_dinamicos
    from services.itens_fatura import extrair_itens_nao_catalogados

    itens_novos = extrair_itens_nao_catalogados(texto)
    if itens_novos:
        aplicar_itens_dinamicos(fatura, itens_novos)
        logger.warning(
            "Colunas dinâmicas preenchidas — inst=%s ref=%s: %s",
            codigo_instalacao,
            fatura["mes_referencia"],
            [i["descricao"] for i in itens_novos],
        )

    fatura["pagina"] = str(numero_pagina)
    fatura["arquivo_origem"] = arquivo_origem

    logger.info(
        "Fatura extraída — grupo=%s, inst=%s, ref=%s, total=R$ %s, pág=%d",
        fatura["grupo"],
        codigo_instalacao,
        fatura["mes_referencia"],
        fatura["valor_total"],
        numero_pagina,
    )
    return fatura


def _deduplicar_faturas(faturas: list[dict[str, str]]) -> list[dict[str, str]]:
    melhor: dict[tuple[str, str], dict[str, str]] = {}
    for fatura in faturas:
        chave = (fatura["codigo_instalacao"], fatura["mes_referencia"])
        existente = melhor.get(chave)
        atual_total = float(fatura.get("valor_total") or 0)
        existente_total = float(existente.get("valor_total") or 0) if existente else -1
        if existente is None or atual_total >= existente_total:
            melhor[chave] = fatura
    return list(melhor.values())


def extrair_faturas(fonte: PdfSource) -> list[dict[str, Any]]:
    """
    Extrai todas as faturas válidas de um PDF com campos completos.

    Returns
    -------
    list[dict]
        Dicionários com todas as colunas de ``COLUNAS_FATURA``.
        Campos específicos de Grupo A ou B ficam vazios conforme o tipo.
    """
    arquivo_origem = _resolver_nome_arquivo(fonte)
    faturas: list[dict[str, str]] = []

    logger.info("Iniciando extração do PDF: %s", arquivo_origem)

    with _abrir_pdf(fonte) as pdf:
        for page in pdf.pages:
            numero = page.page_number or 0
            try:
                registro = _extrair_pagina(page, numero, arquivo_origem)
                if registro:
                    faturas.append(registro)
            except Exception:
                logger.exception("Erro na página %d de %s", numero, arquivo_origem)

    faturas = _deduplicar_faturas(faturas)
    logger.info(
        "Extração concluída — %d fatura(s) de %s", len(faturas), arquivo_origem
    )
    return faturas


def listar_campos_disponiveis() -> dict[str, list[str]]:
    """Documenta todos os campos extraídos, agrupados por categoria."""
    from services import campos_fatura as cf
    from services.colunas_dinamicas import obter_registro

    return {
        "identificacao": list(cf.COLUNAS_IDENTIFICACAO),
        "nota_fiscal": list(cf.COLUNAS_NOTA_FISCAL),
        "tarifa": list(cf.COLUNAS_TARIFA),
        "faturamento": list(cf.COLUNAS_FATURAMENTO),
        "leitura": list(cf.COLUNAS_LEITURA),
        "conta_coletiva": list(cf.COLUNAS_COLETIVA),
        "tributos": list(cf.COLUNAS_TRIBUTOS),
        "grupo_a_consumo_demanda_verde": list(cf.COLUNAS_GRUPO_A),
        "grupo_a_consumo_demanda_azul": list(cf.COLUNAS_GRUPO_A_AZUL),
        "grupo_b_consumo": list(cf.COLUNAS_GRUPO_B),
        "encargos": list(cf.COLUNAS_ENCARGOS),
        "informacoes_complementares": list(cf.COLUNAS_INFORMACOES),
        "medidor_grupo_a": list(cf.COLUNAS_MEDIDOR_A),
        "medidor_grupo_b": list(cf.COLUNAS_MEDIDOR_B),
        "aliases_legado": list(cf.COLUNAS_LEGADO),
        "colunas_dinamicas": list(obter_registro().listar_colunas()),
        "meta": list(cf.COLUNAS_META),
    }

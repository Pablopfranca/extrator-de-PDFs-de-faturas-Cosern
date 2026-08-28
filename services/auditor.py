"""
Auditoria de faturas — detecta conteúdo não mapeado e falhas de extração.

Foco principal: campos/linhas presentes no PDF que o extrator ainda não conhece,
não apenas colunas vazias no CSV.
"""

from __future__ import annotations

import csv
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pdfplumber
from pdfplumber.page import Page

from services.detector_conteudo import ResultadoDeteccao, detectar_conteudo_nao_mapeado
from services.extrator import PdfSource, _abrir_pdf, _extrair_pagina, _pagina_e_fatura_valida

logger = logging.getLogger(__name__)

DEFAULT_FALHAS_DIR = Path(__file__).resolve().parent.parent / "data" / "falhas"
DEFAULT_RELATORIO = Path(__file__).resolve().parent.parent / "data" / "relatorio_auditoria.csv"

COLUNAS_RELATORIO: tuple[str, ...] = (
    "arquivo_pdf",
    "pagina",
    "codigo_instalacao",
    "codigo_cliente",
    "mes_referencia",
    "grupo",
    "classificacao",
    "valor_total",
    "extracao_ok",
    "tem_conteudo_nao_mapeado",
    "itens_nao_mapeados",
    "medidor_nao_mapeado",
    "rotulos_nao_mapeados",
    "palavras_peculiares",
    "soma_itens_detectados",
    "total_itens_fatura",
    "divergencia_total_itens",
    "motivos",
    "data_auditoria",
)


@dataclass
class LinhaAuditoria:
    arquivo_pdf: str
    pagina: int
    codigo_instalacao: str = ""
    codigo_cliente: str = ""
    mes_referencia: str = ""
    grupo: str = ""
    classificacao: str = ""
    valor_total: str = ""
    extracao_ok: bool = False
    tem_conteudo_nao_mapeado: bool = False
    itens_nao_mapeados: list[str] = field(default_factory=list)
    medidor_nao_mapeado: list[str] = field(default_factory=list)
    rotulos_nao_mapeados: list[str] = field(default_factory=list)
    palavras_peculiares: list[str] = field(default_factory=list)
    soma_itens_detectados: float | None = None
    total_itens_fatura: str = ""
    divergencia_total_itens: float | None = None
    motivos: str = ""
    data_auditoria: str = ""

    @property
    def requer_atencao(self) -> bool:
        return not self.extracao_ok or self.tem_conteudo_nao_mapeado

    def para_csv(self) -> dict[str, str]:
        return {
            "arquivo_pdf": self.arquivo_pdf,
            "pagina": str(self.pagina),
            "codigo_instalacao": self.codigo_instalacao,
            "codigo_cliente": self.codigo_cliente,
            "mes_referencia": self.mes_referencia,
            "grupo": self.grupo,
            "classificacao": self.classificacao,
            "valor_total": self.valor_total,
            "extracao_ok": "sim" if self.extracao_ok else "nao",
            "tem_conteudo_nao_mapeado": "sim" if self.tem_conteudo_nao_mapeado else "nao",
            "itens_nao_mapeados": " | ".join(self.itens_nao_mapeados),
            "medidor_nao_mapeado": " | ".join(self.medidor_nao_mapeado),
            "rotulos_nao_mapeados": " | ".join(self.rotulos_nao_mapeados),
            "palavras_peculiares": " | ".join(self.palavras_peculiares),
            "soma_itens_detectados": (
                str(self.soma_itens_detectados) if self.soma_itens_detectados is not None else ""
            ),
            "total_itens_fatura": self.total_itens_fatura,
            "divergencia_total_itens": (
                str(self.divergencia_total_itens)
                if self.divergencia_total_itens is not None
                else ""
            ),
            "motivos": self.motivos,
            "data_auditoria": self.data_auditoria,
        }


def _resolver_caminho_pdf(fonte: PdfSource) -> Path | None:
    if isinstance(fonte, (str, Path)):
        return Path(fonte)
    return None


def _auditar_pagina(
    page: Page,
    numero_pagina: int,
    arquivo_origem: str,
    momento: datetime,
) -> LinhaAuditoria:
    linha = LinhaAuditoria(
        arquivo_pdf=arquivo_origem,
        pagina=numero_pagina,
        data_auditoria=momento.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    try:
        texto = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
    except Exception:
        logger.exception("Erro ao ler página %d de %s", numero_pagina, arquivo_origem)
        linha.motivos = "erro_leitura_pagina"
        return linha

    if not _pagina_e_fatura_valida(texto):
        return linha

    fatura = _extrair_pagina(page, numero_pagina, arquivo_origem)
    if not fatura:
        linha.motivos = "pagina_fatura_sem_extracao"
        return linha

    linha.extracao_ok = True
    linha.codigo_instalacao = fatura.get("codigo_instalacao", "")
    linha.codigo_cliente = fatura.get("codigo_cliente", "")
    linha.mes_referencia = fatura.get("mes_referencia", "")
    linha.grupo = fatura.get("grupo", "")
    linha.classificacao = fatura.get("classificacao", "")
    linha.valor_total = fatura.get("valor_total", "")
    linha.total_itens_fatura = fatura.get("total_itens_fatura", "")

    deteccao = detectar_conteudo_nao_mapeado(texto, fatura)
    _aplicar_deteccao(linha, deteccao)
    return linha


def _aplicar_deteccao(linha: LinhaAuditoria, deteccao: ResultadoDeteccao) -> None:
    linha.itens_nao_mapeados = deteccao.itens_nao_mapeados
    linha.medidor_nao_mapeado = deteccao.medidor_nao_mapeado
    linha.rotulos_nao_mapeados = deteccao.rotulos_nao_mapeados
    linha.palavras_peculiares = deteccao.palavras_peculiares
    linha.soma_itens_detectados = deteccao.soma_itens_detectados
    linha.divergencia_total_itens = deteccao.divergencia_total_itens
    linha.tem_conteudo_nao_mapeado = deteccao.tem_conteudo_nao_mapeado
    linha.motivos = deteccao.resumo_motivos() if deteccao.tem_conteudo_nao_mapeado else "ok"


def auditar_pdf(fonte: PdfSource) -> list[LinhaAuditoria]:
    """Audita todas as páginas-fatura de um PDF."""
    caminho = _resolver_caminho_pdf(fonte)
    arquivo_origem = caminho.name if caminho else "<stream>"
    momento = datetime.now(timezone.utc)
    resultados: list[LinhaAuditoria] = []

    with _abrir_pdf(fonte) as pdf:
        for page in pdf.pages:
            numero = page.page_number or 0
            linha = _auditar_pagina(page, numero, arquivo_origem, momento)
            if linha.extracao_ok or linha.motivos:
                resultados.append(linha)

    return resultados


def iterar_pdfs(pasta: Path, recursivo: bool = True) -> Iterator[Path]:
    if not pasta.is_dir():
        raise NotADirectoryError(f"Pasta não encontrada: {pasta}")
    glob = pasta.rglob("*.pdf") if recursivo else pasta.glob("*.pdf")
    yield from sorted(p for p in glob if p.is_file())


def auditar_pasta(
    pasta: Path,
    recursivo: bool = True,
) -> list[LinhaAuditoria]:
    todas: list[LinhaAuditoria] = []
    for pdf in iterar_pdfs(pasta, recursivo=recursivo):
        logger.info("Auditando %s", pdf.name)
        try:
            todas.extend(auditar_pdf(pdf))
        except Exception:
            logger.exception("Falha ao auditar %s", pdf)
            todas.append(
                LinhaAuditoria(
                    arquivo_pdf=pdf.name,
                    pagina=0,
                    extracao_ok=False,
                    motivos="erro_arquivo_pdf",
                    data_auditoria=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
            )
    return todas


def salvar_relatorio(
    linhas: list[LinhaAuditoria],
    caminho: Path | str = DEFAULT_RELATORIO,
    apenas_problemas: bool = False,
) -> Path:
    arquivo = Path(caminho)
    arquivo.parent.mkdir(parents=True, exist_ok=True)

    registros = [
        linha.para_csv()
        for linha in linhas
        if linha.extracao_ok and (not apenas_problemas or linha.requer_atencao)
    ]

    with arquivo.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUNAS_RELATORIO)
        writer.writeheader()
        writer.writerows(registros)

    return arquivo.resolve()


def copiar_pdfs_com_falha(
    linhas: list[LinhaAuditoria],
    pasta_origem: Path | None,
    destino: Path | str = DEFAULT_FALHAS_DIR,
) -> list[Path]:
    """
    Copia PDFs que têm ao menos uma fatura com conteúdo não mapeado
    ou falha de extração.
    """
    dest = Path(destino)
    dest.mkdir(parents=True, exist_ok=True)

    arquivos_problema = {
        linha.arquivo_pdf
        for linha in linhas
        if linha.requer_atencao and linha.arquivo_pdf not in {"", "<stream>"}
    }

    copiados: list[Path] = []
    for nome in sorted(arquivos_problema):
        origem = _localizar_pdf(nome, pasta_origem)
        if origem is None:
            logger.warning("PDF com falha não localizado para cópia: %s", nome)
            continue
        alvo = dest / origem.name
        if not alvo.exists() or origem.stat().st_mtime > alvo.stat().st_mtime:
            shutil.copy2(origem, alvo)
        copiados.append(alvo.resolve())

    return copiados


def _localizar_pdf(nome: str, pasta_origem: Path | None) -> Path | None:
    if pasta_origem:
        for pdf in pasta_origem.rglob(nome):
            if pdf.is_file():
                return pdf
    candidato = Path(nome)
    if candidato.is_file():
        return candidato
    return None


def resumir_auditoria(linhas: list[LinhaAuditoria]) -> dict[str, Any]:
    extraidas = [l for l in linhas if l.extracao_ok]
    problemas = [l for l in extraidas if l.tem_conteudo_nao_mapeado]
    falhas_extracao = [l for l in linhas if not l.extracao_ok and l.motivos]

    pdfs_afetados = len({l.arquivo_pdf for l in linhas if l.requer_atencao})

    return {
        "faturas_auditadas": len(extraidas),
        "faturas_com_conteudo_nao_mapeado": len(problemas),
        "registros_falha_extracao": len(falhas_extracao),
        "pdfs_com_atencao": pdfs_afetados,
    }

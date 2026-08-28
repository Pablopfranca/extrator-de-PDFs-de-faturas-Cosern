"""Utilitários numéricos compartilhados (evita import circular)."""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


def parse_numero_brasileiro(valor: str | None) -> float | None:
    """Converte formatos BR (``1.000,50`` ou ``941,72-``) para float."""
    if valor is None:
        return None
    limpo = valor.strip()
    if not limpo:
        return None
    negativo = limpo.endswith("-")
    limpo = re.sub(r"[^\d,.\-]", "", limpo).rstrip("-")
    if not limpo or limpo in {".", ",", "-"}:
        return None
    try:
        if "," in limpo:
            limpo = limpo.replace(".", "").replace(",", ".")
        elif limpo.count(".") > 1:
            limpo = limpo.replace(".", "")
        numero = float(limpo)
        return -numero if negativo else numero
    except ValueError:
        logger.warning("Falha ao converter valor numérico: %r", valor)
        return None


def valor_ou_vazio(valor: float | None) -> str:
    if valor is None:
        return ""
    return str(valor)

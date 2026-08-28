"""
Fuso horário de referência para cálculos de posto horário (ponta/fora ponta).

Neoenergia/Cosern — RN: horário oficial de Fortaleza (UTC−3, sem horário de verão).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

try:
    FUSO_FORTALEZA = ZoneInfo("America/Fortaleza")
except Exception:
    # Fallback se tzdata não estiver disponível no ambiente
    FUSO_FORTALEZA = timezone(timedelta(hours=-3))

UTC_MENOS_3 = FUSO_FORTALEZA


def agora_fortaleza() -> datetime:
    return datetime.now(FUSO_FORTALEZA)

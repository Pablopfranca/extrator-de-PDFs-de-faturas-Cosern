"""Camada de persistência (CSV hoje; SQLAlchemy/SQLite no futuro)."""

from models.csv_store import (
    DEFAULT_CSV_PATH,
    carregar_faturas_csv,
    extrair_e_salvar_csv,
    salvar_faturas_csv,
)

__all__ = [
    "DEFAULT_CSV_PATH",
    "carregar_faturas_csv",
    "extrair_e_salvar_csv",
    "salvar_faturas_csv",
]

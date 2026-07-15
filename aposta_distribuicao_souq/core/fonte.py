"""Fonte dos dados: Excel (seu PC) ou Supabase/Postgres (nuvem).

O Excel nunca vai para a nuvem. No PC, `publica_supabase.py` prepara os dados e
grava as tabelas; o app hospedado lê essas tabelas prontas e só aplica as regras.

Configuração (variável de ambiente no PC, Secrets no Streamlit Cloud):
    FONTE_DADOS = "excel" (default) | "supabase"
    DATABASE_URL = string de conexão do Supabase (use a do **Pooler**)

As tabelas levam o prefixo `aposta_` para conviver, no mesmo banco, com as do app
de transferências entre lojas — que tem uma tabela `produtos` e a recria a cada
publicação. Sem o prefixo, um app apagaria a tabela do outro.
"""
from __future__ import annotations

import os

import pandas as pd

PREFIXO = "aposta_"
TABELAS = ("produtos", "vendas", "lojas", "faixas")

# Colunas de data por tabela — o ida-e-volta pelo Postgres perde o tipo.
_COLS_DATA = {
    "produtos": ["dt_envio"],
    "vendas": ["dt_transacao"],
    "lojas": ["dt_abertura", "dt_fechamento"],
}


def segredo(nome: str) -> str:
    """Lê uma configuração de variável de ambiente ou dos Secrets do Streamlit."""
    v = os.getenv(nome)
    if v:
        return v
    try:
        import streamlit as st
        if nome in st.secrets:
            return str(st.secrets[nome])
    except Exception:
        pass
    return ""


def fonte() -> str:
    return (segredo("FONTE_DADOS") or "excel").strip().lower()


def usa_supabase() -> bool:
    return fonte() in ("supabase", "db", "postgres")


def db_url() -> str:
    return segredo("DATABASE_URL")


def engine():
    from sqlalchemy import create_engine

    url = db_url()
    if not url:
        raise RuntimeError(
            "DATABASE_URL não configurada. No PC use o .env; na nuvem, os Secrets."
        )
    return create_engine(url, pool_pre_ping=True)


def ler_tabela(nome: str) -> pd.DataFrame:
    """Lê `aposta_<nome>` do Postgres, recompondo as colunas de data."""
    from sqlalchemy import text

    eng = engine()
    try:
        with eng.connect() as con:
            df = pd.read_sql(text(f'select * from "{PREFIXO}{nome}"'), con)
    finally:
        eng.dispose()
    for col in _COLS_DATA.get(nome, []):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df

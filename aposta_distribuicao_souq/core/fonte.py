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

# Carrega o .env do projeto (no PC). Na nuvem não há .env — lá valem os Secrets.
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

PREFIXO = "aposta_"
TABELAS = ("produtos", "vendas", "lojas", "faixas")

# Colunas de data por tabela — o ida-e-volta pelo Postgres perde o tipo.
_COLS_DATA = {
    "produtos": ["dt_envio", "dt_entrada_loja", "dt_liquidacao"],
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


_ESQUEMAS = ("postgresql+psycopg2://", "postgresql://", "postgres://")


def db_url() -> str:
    """String de conexão, tolerando colagens comuns.

    Aceita valor entre aspas, com o próprio nome da chave na frente
    (`DATABASE_URL=...`) e os esquemas `postgres://` / `postgresql://`, que
    normaliza para `postgresql+psycopg2://`.
    """
    v = segredo("DATABASE_URL").strip()
    if not v:
        return ""
    if v.lower().startswith("database_url"):      # colou a linha inteira
        v = v.split("=", 1)[-1].strip()
    v = v.strip('"').strip("'").strip()
    for esq in ("postgres://", "postgresql://"):  # normaliza p/ o driver do Python
        if v.startswith(esq):
            return "postgresql+psycopg2://" + v[len(esq):]
    return v


def engine():
    from sqlalchemy import create_engine

    url = db_url()
    if not url:
        raise RuntimeError(
            "DATABASE_URL não configurada. No PC use o .env; na nuvem, os Secrets "
            "do Streamlit (Manage app > Settings > Secrets)."
        )
    if not url.startswith(_ESQUEMAS):
        # Mostra só o começo — nunca a senha — para dar para diagnosticar.
        raise RuntimeError(
            f"DATABASE_URL não parece uma conexão Postgres: começa com {url[:15]!r}. "
            "Ela deve começar com 'postgresql+psycopg2://'. Copie o valor que está "
            "no arquivo .env do projeto (o mesmo que já funciona no seu PC)."
        )
    return create_engine(url, pool_pre_ping=True)


def diagnostico() -> str:
    """Resumo da conexão em uso, **sem a senha** — para depurar na nuvem.

    O Streamlit Cloud censura a mensagem de exceção ("error message is
    redacted"), então este texto é exibido via st.error, que não é censurado.
    """
    from urllib.parse import urlparse

    u = db_url()
    if not u:
        return "DATABASE_URL vazia (Secret não configurado)."
    p = urlparse(u)
    usuario = p.username or ""
    tenant_ok = "." in usuario  # o pooler exige postgres.<project_ref>
    return (
        f"esquema={p.scheme} | usuario={usuario!r} | host={p.hostname} | "
        f"porta={p.port} | banco={p.path} | usuario_tem_ref_do_projeto={tenant_ok}"
    )


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

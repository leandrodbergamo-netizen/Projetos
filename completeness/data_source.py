# -*- coding: utf-8 -*-
"""Camada de dados do app.

Fontes (config.fonte_dados()):
  - "local":    lê os CSVs gerados pela rotina diária nesta pasta (uso no PC).
  - "supabase": lê as tabelas comp_* do Postgres (usado pelo app na nuvem).

Contrato de saída (igual para as duas fontes):
  detalhe        -> um produto publicado no site por linha, com as 14 flags
  disponibilidade-> um SKU pai candidato (estoque >= 2) por linha
  historico      -> série diária agregada do completeness
  hist_disp      -> série diária agregada da disponibilidade
  meta           -> uma linha com o resumo do último processamento
"""
from __future__ import annotations

import pandas as pd

import config

TABELAS = ["detalhe", "disponibilidade", "historico", "hist_disp", "meta"]

_ARQUIVOS = {
    "detalhe": config.DETALHE_ATUAL,
    "disponibilidade": config.DISP_ATUAL,
    "historico": config.HIST,
    "hist_disp": config.HIST_DISP,
}

# Colunas texto que não podem virar número (SKU com pontos, datas ISO).
_TEXTO = {"detalhe": ["sku_pai"], "disponibilidade": ["pai", "dt_envio", "foto_arq"]}


def nome_tabela(nome: str) -> str:
    return f"{config.PREFIXO_TABELAS}{nome}"


# --- Fonte LOCAL (CSVs da rotina diária) ------------------------------------
def carregar_local() -> dict[str, pd.DataFrame]:
    dados: dict[str, pd.DataFrame] = {}
    for nome, arq in _ARQUIVOS.items():
        if not arq.exists():
            raise FileNotFoundError(
                f"{arq.name} não encontrado. Rode 'python atualiza_completeness.py --processa'.")
        dados[nome] = pd.read_csv(arq, dtype={c: "string" for c in _TEXTO.get(nome, [])})
    dados["meta"] = _meta_local(dados)
    return dados


def _meta_local(dados: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Resumo do último processamento: data/resumo.json, com fallback nos snapshots.

    O fallback não conhece o total coletado no products.json (só o que entrou no
    dash), então deixa 'coletados' vazio para o alerta de coleta não mentir.
    """
    import datetime
    import json

    atualizado = datetime.datetime.fromtimestamp(
        config.DISP_ATUAL.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
    if config.RESUMO_JSON.exists():
        resumo = json.loads(config.RESUMO_JSON.read_text(encoding="utf-8"))
        return pd.DataFrame([{**resumo, "atualizado": atualizado}])

    det, disp = dados["detalhe"], dados["disponibilidade"]
    cand = len(disp)
    no_site = int(disp["no_site"].sum())
    return pd.DataFrame([{
        "data": dados["hist_disp"]["data"].max(),
        "atualizado": atualizado,
        "coletados": None,
        "no_site": len(det),
        "candidatos": cand,
        "publicados": no_site,
        "pct_disponibilidade": round(no_site / cand * 100, 1) if cand else 0.0,
        "fora_do_site": cand - no_site,
        "fora_com_foto": int(((disp["no_site"] == 0) & (disp["tem_foto"] == 1)).sum()),
        "sem_match": int((det["colecao"] == "Sem cadastro").sum()),
        "sem_imagem_no_site": int((det["f6"] == 0).sum()),
    }])


# --- Fonte SUPABASE (nuvem) -------------------------------------------------
def db_url() -> str:
    return config.segredo("DATABASE_URL")


def carregar_supabase() -> dict[str, pd.DataFrame]:
    from sqlalchemy import create_engine, text

    url = db_url()
    if not url:
        raise RuntimeError("DATABASE_URL não configurada (env ou st.secrets).")
    # dispose() no finally devolve a conexão ao pooler do Supabase; sem isso cada
    # carga deixa uma sessão ociosa presa até o processo morrer.
    eng = create_engine(url, pool_pre_ping=True)
    dados: dict[str, pd.DataFrame] = {}
    try:
        with eng.connect() as con:
            for nome in TABELAS:
                try:
                    dados[nome] = pd.read_sql(text(f'select * from "{nome_tabela(nome)}"'), con)
                except Exception:
                    dados[nome] = pd.DataFrame()
                    con.rollback()   # SELECT que falha aborta a transação no Postgres
    finally:
        eng.dispose()
    return dados


def carregar_dados() -> dict[str, pd.DataFrame]:
    if config.fonte_dados() in ("supabase", "db", "postgres"):
        return carregar_supabase()
    return carregar_local()

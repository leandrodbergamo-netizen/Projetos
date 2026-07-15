"""Camada de acesso a dados para o app (cacheada com Streamlit).

Concentra a leitura pesada (cadastro + vendas de vários anos, já no escopo Souq/
full price e enriquecidos) para não recarregar a cada interação.

Duas fontes (ver `core/fonte.py`):
- **excel** (seu PC): lê as planilhas/parquet e prepara os dados aqui.
- **supabase** (nuvem): lê as tabelas `aposta_*` já prontas, publicadas pelo
  `publica_supabase.py`. O trabalho pesado fica no PC, não no servidor.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from core import fonte
from core.dados import (carregar_produtos, carregar_vendas, cluster_por_loja,
                        escopo_souq, lojas_alvo_souq, localidades_ecom)
from core.espelho import preparar_produtos, preparar_vendas

ANOS = (2022, 2023, 2024, 2025, 2026)
_CACHE = Path(".cache_dados")

# Colunas das vendas efetivamente usadas pelas regras — é o que se publica.
COLS_VENDAS = ["dt_transacao", "sk_localidade", "sk_produto", "cod_sku_pai",
               "qtd_produto", "subgrupo", "grupo_material", "cor_grupo"]


def _ler_ano(ano: int) -> pd.DataFrame:
    p = _CACHE / f"vendas_{ano}.parquet"
    if p.exists():
        return pd.read_parquet(p)
    return carregar_vendas([ano])  # constrói o cache a partir do Excel


def construir_produtos() -> pd.DataFrame:
    """Cadastro enriquecido (tecido/cor/faixa/rank), a partir do Excel."""
    return preparar_produtos(carregar_produtos())


def construir_vendas(produtos_preparados: pd.DataFrame) -> pd.DataFrame:
    """Vendas full price no escopo Souq, alinhadas ao cadastro."""
    v = pd.concat([_ler_ano(a) for a in ANOS], ignore_index=True)
    fp = escopo_souq(v)
    fp = fp[(fp["flag_liquidacao"] == 0) & (fp["tipo_venda"] == "venda") & (fp["qtd_produto"] > 0)]
    return preparar_vendas(fp, produtos_preparados)


@st.cache_data(show_spinner="Carregando cadastro de produtos...")
def produtos_prep() -> pd.DataFrame:
    if fonte.usa_supabase():
        return fonte.ler_tabela("produtos")
    return construir_produtos()


@st.cache_data(show_spinner="Carregando vendas (2022–2026)...")
def vendas_fp() -> pd.DataFrame:
    if fonte.usa_supabase():
        return fonte.ler_tabela("vendas")
    return construir_vendas(produtos_prep())


@st.cache_data(show_spinner=False)
def contexto_lojas() -> dict:
    alvo = lojas_alvo_souq()
    return {
        "lojas_alvo": [str(float(x)) for x in alvo["sk_localidade"]],
        "n_lojas_alvo": len(alvo),
        "cluster_por_loja": cluster_por_loja(),
        "ecom_locs": localidades_ecom(),
    }


def opcoes(coluna: str) -> list[str]:
    """Valores distintos (ordenados) de uma coluna do cadastro para dropdowns."""
    s = produtos_prep()[coluna].dropna().astype(str)
    return sorted(s.unique().tolist())


def opcoes_por_relevancia(coluna: str, ultimos=("Outros", "Indefinido")) -> list[str]:
    """Valores ordenados por volume de produtos (mais relevante primeiro).

    Buckets residuais (`Outros`/`Indefinido`) vão para o fim da lista, por mais
    numerosos que sejam: ninguém procura por eles primeiro.
    """
    vc = produtos_prep()[coluna].dropna().astype(str).value_counts()
    principais = [v for v in vc.index if v not in ultimos]
    finais = [v for v in vc.index if v in ultimos]
    return principais + finais


def recarregar_bases() -> None:
    """Relê os Excel (ignorando o cache parquet) e limpa o cache do Streamlit.

    Use quando as bases mudarem (ex.: coluna nova no cadastro) — evita ter que
    apagar `.cache_dados/` na mão. Só faz sentido no PC (fonte excel).
    """
    carregar_produtos(forcar=True)
    for ano in ANOS:
        # um parquet por ano — mesmo nome que `_ler_ano` procura
        carregar_vendas([ano], forcar=True)
    st.cache_data.clear()


def botao_recarregar(local: str = "sidebar") -> None:
    """Renderiza o botão de recarga das bases (oculto na nuvem: lá não há Excel)."""
    if fonte.usa_supabase():
        return
    alvo = st.sidebar if local == "sidebar" else st
    if alvo.button("🔄 Recarregar bases", help="Relê os Excel e refaz o cache."):
        recarregar_bases()
        alvo.success("Bases recarregadas.")
        st.rerun()

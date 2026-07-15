"""Camada de acesso a dados para o app (cacheada com Streamlit).

Concentra a leitura pesada (cadastro + vendas de vários anos, já no escopo Souq/
full price e enriquecidos) para não recarregar a cada interação.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from core.dados import (carregar_vendas, cluster_por_loja, escopo_souq,
                        lojas_alvo_souq, localidades_ecom)
from core.espelho import preparar_produtos, preparar_vendas

ANOS = (2022, 2023, 2024, 2025, 2026)
_CACHE = Path(".cache_dados")


def _ler_ano(ano: int) -> pd.DataFrame:
    p = _CACHE / f"vendas_{ano}.parquet"
    if p.exists():
        return pd.read_parquet(p)
    return carregar_vendas([ano])  # constrói o cache a partir do Excel


@st.cache_data(show_spinner="Carregando cadastro de produtos...")
def produtos_prep() -> pd.DataFrame:
    from core.dados import carregar_produtos
    return preparar_produtos(carregar_produtos())


@st.cache_data(show_spinner="Carregando vendas (2022–2026)...")
def vendas_fp() -> pd.DataFrame:
    pp = produtos_prep()
    v = pd.concat([_ler_ano(a) for a in ANOS], ignore_index=True)
    fp = escopo_souq(v)
    fp = fp[(fp["flag_liquidacao"] == 0) & (fp["tipo_venda"] == "venda") & (fp["qtd_produto"] > 0)]
    return preparar_vendas(fp, pp)


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


def recarregar_bases() -> None:
    """Relê os Excel (ignorando o cache parquet) e limpa o cache do Streamlit.

    Use quando as bases mudarem (ex.: coluna nova no cadastro) — evita ter que
    apagar `.cache_dados/` na mão.
    """
    from core.dados import carregar_produtos
    carregar_produtos(forcar=True)
    for ano in ANOS:
        # um parquet por ano — mesmo nome que `_ler_ano` procura
        carregar_vendas([ano], forcar=True)
    st.cache_data.clear()


def botao_recarregar(local: str = "sidebar") -> None:
    """Renderiza o botão de recarga das bases."""
    alvo = st.sidebar if local == "sidebar" else st
    if alvo.button("🔄 Recarregar bases", help="Relê os Excel e refaz o cache."):
        recarregar_bases()
        alvo.success("Bases recarregadas.")
        st.rerun()

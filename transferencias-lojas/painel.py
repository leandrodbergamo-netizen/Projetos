"""Painel loja (linhas) x SKU pai (colunas): estoque, vendas e giro.

Como há milhares de SKUs pai, o painel filtra por grupo (opcional) e mostra
apenas os top-N SKUs pai com maior venda na janela, para ficar legível.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

import config


def _grupo_por_pai(produtos: pd.DataFrame) -> pd.Series:
    """Grupo predominante de cada SKU pai (a partir dos filhos)."""
    return produtos.groupby("sku_pai")["grupo"].agg(
        lambda s: s.mode().iloc[0] if not s.mode().empty else "Roupa")


def montar_matrizes(dados: dict[str, pd.DataFrame], hoje: date,
                    janela_dias: int = config.JANELA_VENDAS_DIAS,
                    grupo: str | None = None, top_n: int = 30):
    """Retorna três pivôs (loja x sku_pai): estoque, vendas e giro."""
    produtos = dados["produtos"]
    estoque_loja = dados["estoque_loja"]
    vendas = dados["vendas"]

    pai_para_grupo = _grupo_por_pai(produtos)
    pais_validos = pai_para_grupo.index
    if grupo and grupo != "Todos":
        pais_validos = pai_para_grupo[pai_para_grupo == grupo].index

    # Vendas na janela por loja x sku_pai.
    corte = pd.Timestamp(hoje) - pd.Timedelta(days=janela_dias)
    vend = vendas[(vendas["data"] >= corte) & (vendas["sku_pai"].isin(pais_validos))]

    # Top-N SKUs pai por venda total na janela.
    top_pais = (vend.groupby("sku_pai")["qtd"].sum()
                .sort_values(ascending=False).head(top_n).index)

    vend = vend[vend["sku_pai"].isin(top_pais)]
    pivot_vend = vend.pivot_table(index="loja", columns="sku_pai", values="qtd",
                                  aggfunc="sum", fill_value=0)

    # Estoque por loja x sku_pai (mesmos pais do top).
    est = estoque_loja.merge(produtos[["sku_filho", "sku_pai"]], on="sku_filho", how="left")
    est = est[est["sku_pai"].isin(top_pais)]
    pivot_est = est.pivot_table(index="loja", columns="sku_pai", values="qtd",
                                aggfunc="sum", fill_value=0)

    pivot_est, pivot_vend = pivot_est.align(pivot_vend, fill_value=0)
    giro = pivot_vend / pivot_est.replace(0, pd.NA)

    return pivot_est, pivot_vend, giro


def estilizar(matriz: pd.DataFrame, fmt: str = "{:.0f}", cmap: str = "RdYlGn"):
    """Aplica heatmap (formatação condicional) a uma matriz loja x sku_pai."""
    return (matriz.style
            .background_gradient(cmap=cmap, axis=None)
            .format(fmt, na_rep="—"))


def estilizar_giro(giro: pd.DataFrame, cmap: str = "RdYlGn"):
    return estilizar(giro, fmt="{:.2f}", cmap=cmap)

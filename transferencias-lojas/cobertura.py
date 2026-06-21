"""Cobertura e previsão de venda do SKU pai por loja (combina com sazonalidade).

Previsão (full price) = velocidade recente dessazonalizada × soma dos índices
sazonais das próximas semanas × fator de feriado. Cobertura = estoque do pai
na loja ÷ previsão no horizonte. Usada para priorizar quem recebe (alta
demanda prevista + baixa cobertura) e dimensionar a quantidade.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

import config
import feriados
import sazonalidade


def _moda(s: pd.Series):
    m = s.mode()
    return m.iloc[0] if not m.empty else None


def segmento_por_pai(produtos: pd.DataFrame) -> pd.DataFrame:
    """Segmento de sazonalidade (grupo merch/subgrupo/matéria) e nº de tamanhos por pai."""
    return produtos.groupby("sku_pai").agg(
        grupo_merc=("grupo_merc", _moda),
        subgrupo=("subgrupo", _moda),
        materia=("materia", _moda),
        n_tam=("sku_filho", "nunique"),
    ).reset_index()


def _semanas(hoje: date, n_passado: int, n_futuro: int):
    base = pd.Timestamp(hoje)
    passado = [base - pd.Timedelta(weeks=i) for i in range(n_passado)]
    futuro = [base + pd.Timedelta(weeks=i) for i in range(1, n_futuro + 1)]
    iso = lambda d: (int(d.isocalendar().year), int(d.isocalendar().week))
    return [iso(d) for d in passado], [iso(d) for d in futuro]


def cobertura_receptoras(pares: pd.DataFrame, produtos: pd.DataFrame,
                         estoque_loja: pd.DataFrame, vendas: pd.DataFrame, hoje: date,
                         semanas_hist: int = config.COBERTURA_SEMANAS_HIST,
                         horizonte: int = config.COBERTURA_HORIZONTE_SEMANAS,
                         curva: pd.DataFrame | None = None) -> pd.DataFrame:
    """pares: DataFrame único de (loja, sku_pai). Retorna previsão e cobertura."""
    curva = curva if curva is not None else sazonalidade.carregar_curva()
    seg = segmento_por_pai(produtos)
    sem_pass, sem_fut = _semanas(hoje, semanas_hist, horizonte)

    # Velocidade full price por (loja, sku_pai) nas últimas semanas.
    corte = pd.Timestamp(hoje) - pd.Timedelta(weeks=semanas_hist)
    v = vendas[(vendas["data"] >= corte) & (vendas["liquidacao"] == 0)]
    vp = v.groupby(["loja", "sku_pai"])["qtd"].sum().reset_index(name="qtd_hist")

    df = pares.merge(vp, on=["loja", "sku_pai"], how="left").fillna({"qtd_hist": 0})
    df = df.merge(seg, on="sku_pai", how="left")

    # Fatores sazonais por segmento (memoizado).
    cache: dict = {}

    def fatores(gm, sg, mat):
        key = (gm, sg, mat)
        if key not in cache:
            ip = [sazonalidade.indice(curva, gm, sg, mat, w) for (_, w) in sem_pass]
            mean_pass = (sum(ip) / len(ip)) if ip else 1.0
            soma_fut = sum(sazonalidade.indice(curva, gm, sg, mat, w) * feriados.fator_semana(a, w)
                           for (a, w) in sem_fut)
            cache[key] = (mean_pass if mean_pass > 0 else 1.0, soma_fut)
        return cache[key]

    prev = []
    for r in df.itertuples(index=False):
        mean_pass, soma_fut = fatores(r.grupo_merc, r.subgrupo, r.materia)
        deseason = (r.qtd_hist / semanas_hist) / mean_pass
        prev.append(deseason * soma_fut)
    df["vel_semana"] = df["qtd_hist"] / semanas_hist
    df["prev_horizonte"] = prev

    # Estoque do pai na loja e cobertura.
    est_pai = (estoque_loja.merge(produtos[["sku_filho", "sku_pai"]], on="sku_filho", how="left")
               .groupby(["loja", "sku_pai"])["qtd"].sum().reset_index(name="estoque_pai"))
    df = df.merge(est_pai, on=["loja", "sku_pai"], how="left").fillna({"estoque_pai": 0})
    df["cobertura_pai"] = df["estoque_pai"] / df["prev_horizonte"].replace(0, pd.NA)

    return df[["loja", "sku_pai", "n_tam", "vel_semana", "prev_horizonte",
               "estoque_pai", "cobertura_pai"]]

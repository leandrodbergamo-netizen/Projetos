"""Histórico diário de estoque (compacto) e métricas derivadas.

As bases não trazem data de recebimento — só um snapshot do dia. Para:
  (a) calcular velocidade de venda SEM o efeito ruptura (dividir pelos dias COM
      estoque, não por dias corridos),
  (b) usar a 1ª data de entrada para ajustar o range do cálculo, e
  (c) aproximar a "data de recebimento" (início da sequência atual em estoque),
gravamos, a cada atualização, apenas as linhas com qtde > 0 (loja, sku_filho,
qtde, data), em Parquet particionado por mês — leve e barato de acrescentar.

Como só guardamos qtde > 0, a AUSÊNCIA de um (loja, sku, dia) já significa estoque
zerado naquele dia: os zeros saem de graça do cálculo de velocidade.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

import config

COLS = ["data", "loja", "sku_filho", "qtde"]


def _mes_path(hoje: date):
    return config.PASTA_HIST / f"{pd.Timestamp(hoje):%Y-%m}.parquet"


def carregar_hist() -> pd.DataFrame:
    """Concatena todos os meses do histórico (+ arquivo legado, se existir)."""
    partes = []
    if config.PASTA_HIST.exists():
        for p in sorted(config.PASTA_HIST.glob("*.parquet")):
            partes.append(pd.read_parquet(p))
    if config.HIST_ESTOQUE.exists():  # migração do formato antigo (único arquivo)
        antigo = pd.read_parquet(config.HIST_ESTOQUE)
        partes.append(antigo[[c for c in COLS if c in antigo.columns]])
    if not partes:
        return pd.DataFrame(columns=COLS)
    h = pd.concat(partes, ignore_index=True)
    h["data"] = pd.to_datetime(h["data"]).dt.normalize()
    return h[h["qtde"] > 0]


def gravar_snapshot(snap: pd.DataFrame, hoje: date) -> None:
    """Acumula o estoque (qtde>0) de 'hoje' no mês corrente (idempotente por dia).

    snap deve ter colunas: loja, sku_filho, qtde.
    """
    data = pd.Timestamp(hoje).normalize()
    path = _mes_path(hoje)
    mes = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=COLS)
    if not mes.empty and (pd.to_datetime(mes["data"]).dt.normalize() == data).any():
        return  # já gravado hoje

    novo = snap.loc[snap["qtde"] > 0, ["loja", "sku_filho", "qtde"]].copy()
    novo["data"] = data
    out = pd.concat([mes, novo[COLS]], ignore_index=True)
    config.PASTA_HIST.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path, index=False)


def primeira_entrada() -> pd.DataFrame:
    """1ª data observada com estoque por (loja, sku_filho). Vazio se sem histórico."""
    h = carregar_hist()
    if h.empty:
        return pd.DataFrame(columns=["loja", "sku_filho", "primeira_entrada"])
    return (h.groupby(["loja", "sku_filho"])["data"].min()
            .reset_index().rename(columns={"data": "primeira_entrada"}))


def dias_disponiveis(hoje: date, dias: int) -> pd.DataFrame:
    """Nº de dias COM estoque por (loja, sku_filho) nos últimos `dias` (p/ velocidade)."""
    h = carregar_hist()
    cols = ["loja", "sku_filho", "dias_disp"]
    if h.empty:
        return pd.DataFrame(columns=cols)
    corte = pd.Timestamp(hoje).normalize() - pd.Timedelta(days=dias)
    h = h[h["data"] >= corte]
    return (h.groupby(["loja", "sku_filho"])["data"].nunique()
            .reset_index().rename(columns={"data": "dias_disp"}))


def recebimento_estimado() -> pd.DataFrame:
    """Data de recebimento = início da sequência ATUAL de dias com estoque.

    Só reporta quando OBSERVAMOS a chegada (transição 0->>0) dentro do histórico;
    se o item já estava em estoque no 1º dia gravado, fica desconhecido (fallback).
    Requer >= 2 datas de histórico.
    """
    h = carregar_hist()
    cols = ["loja", "sku_filho", "data_recebimento"]
    if h.empty:
        return pd.DataFrame(columns=cols)
    datas = sorted(h["data"].unique())
    if len(datas) < 2:
        return pd.DataFrame(columns=cols)

    disp = (h.groupby(["loja", "sku_filho", "data"])["qtde"].sum() > 0)
    pivot = disp.unstack("data", fill_value=False).reindex(columns=datas, fill_value=False)

    registros = []
    for (loja, sku), linha in pivot.iterrows():
        v = list(linha.values)
        if not v[-1]:
            continue  # não está disponível hoje
        ini = len(v) - 1
        while ini - 1 >= 0 and v[ini - 1]:
            ini -= 1
        if ini == 0:
            continue  # não observamos a chegada -> desconhecido
        registros.append({"loja": loja, "sku_filho": sku, "data_recebimento": datas[ini]})
    return pd.DataFrame(registros, columns=cols)

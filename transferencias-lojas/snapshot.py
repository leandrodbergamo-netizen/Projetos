"""Histórico diário de estoque.

As bases não trazem data de recebimento — apenas um snapshot do dia. Para:
  (a) calcular a velocidade de vendas SEM o efeito ruptura (dividir por dias
      COM estoque, não por dias corridos), e
  (b) aproximar a "data de recebimento" (início da sequência atual em que o
      item está disponível na loja),
gravamos um snapshot do estoque a cada atualização e o acumulamos aqui.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

import config

COLS = ["data", "loja", "sku_filho", "qtde", "status"]


def carregar_hist() -> pd.DataFrame:
    p = config.HIST_ESTOQUE
    if p.exists():
        return pd.read_parquet(p)
    return pd.DataFrame(columns=COLS)


def gravar_snapshot(snap: pd.DataFrame, hoje: date) -> pd.DataFrame:
    """Acumula o estoque de 'hoje' no histórico (idempotente por dia).

    snap deve ter colunas: loja, sku_filho, qtde, status.
    """
    data = pd.Timestamp(hoje).normalize()
    hist = carregar_hist()
    if not hist.empty and (pd.to_datetime(hist["data"]) == data).any():
        return hist  # já gravado hoje

    novo = snap.copy()
    novo["data"] = data
    novo = novo[COLS]
    out = pd.concat([hist, novo], ignore_index=True)
    config.HIST_ESTOQUE.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(config.HIST_ESTOQUE, index=False)
    return out


def recebimento_estimado() -> pd.DataFrame:
    """Estima a data de recebimento por (loja, sku_filho) a partir do histórico.

    É o início da sequência mais recente de dias em que o item esteve com
    estoque > 0 (status 'Estoque') na loja. Requer >= 2 datas de histórico;
    caso contrário retorna vazio (a regra de recebimento fica relaxada).
    """
    hist = carregar_hist()
    cols_saida = ["loja", "sku_filho", "data_recebimento"]
    if hist.empty:
        return pd.DataFrame(columns=cols_saida)

    hist = hist[hist["status"] == "Estoque"].copy()
    hist["data"] = pd.to_datetime(hist["data"]).dt.normalize()
    datas = sorted(hist["data"].unique())
    if len(datas) < 2:
        return pd.DataFrame(columns=cols_saida)

    # disp[(loja, sku, data)] = item disponível (qtde>0) naquele dia.
    disp = (hist.groupby(["loja", "sku_filho", "data"])["qtde"].sum() > 0)
    pivot = disp.unstack("data", fill_value=False).reindex(columns=datas, fill_value=False)

    registros = []
    for (loja, sku), linha in pivot.iterrows():
        valores = list(linha.values)
        if not valores[-1]:
            continue  # não está disponível hoje -> não é doadora candidata
        # anda de trás para frente enquanto disponível
        inicio = len(valores) - 1
        while inicio - 1 >= 0 and valores[inicio - 1]:
            inicio -= 1
        # Só consideramos recebimento conhecido se OBSERVAMOS a chegada
        # (transição 0->>0). Se o item já estava em estoque no primeiro dia do
        # histórico, a data real é desconhecida -> deixamos para o fallback.
        if inicio == 0:
            continue
        registros.append({"loja": loja, "sku_filho": sku,
                          "data_recebimento": datas[inicio]})

    return pd.DataFrame(registros, columns=cols_saida)

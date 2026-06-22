"""Camada de dados: carrega os DataFrames usados pelo motor de remanejamento.

Fontes (config.FONTE_DADOS):
  - "excel": lê as bases reais (.xlsx) na raiz do projeto.
  - "mock":  gera dados de exemplo em memória (para testes, sem bases).

Contrato de saída (igual para todas as fontes):
  produtos      -> sku_filho, sku_pai, descricao, grupo
  estoque_loja  -> loja, sku_filho, qtd
  estoque_cd    -> sku_filho, qtd
  transito      -> sku_filho, loja_destino, qtd
  vendas        -> loja, sku_filho, sku_pai, data (datetime), qtd
  recebimento   -> loja, sku_filho, data_recebimento (datetime)  [pode vir vazio]
"""
from __future__ import annotations

import unicodedata
from datetime import date, timedelta

import numpy as np
import pandas as pd

import config
import snapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ler_excel(caminho, sheet, usecols=None):
    """Lê uma aba (opcionalmente só algumas colunas); se não existir, cai na 1ª aba."""
    try:
        return pd.read_excel(caminho, sheet_name=sheet, usecols=usecols)
    except ValueError:
        return pd.read_excel(caminho, sheet_name=0, usecols=usecols)


def _norm(texto) -> str:
    """Normaliza nome de loja para casar vendas x cadastro (sem acento, minúsculo)."""
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return ""
    s = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


# ---------------------------------------------------------------------------
# Fonte EXCEL (bases reais)
# ---------------------------------------------------------------------------
def _build_excel(hoje: date) -> dict[str, pd.DataFrame]:
    # --- Lojas ativas (canal Lojas, exclui marcas vetadas: Outlet) ------
    loj = _ler_excel(config.ARQ_LOJAS, "Lojas")
    ativas = loj[(loj["desc_ativa"] == "T") & (loj["canal"] == "Lojas")
                 & (~loj["Marca"].isin(config.EXCLUIR_MARCAS_LOJA))].copy()
    sk_para_nome = dict(zip(ativas["sk_localidade"], ativas["desc_nome"]))
    lojas_validas = set(sk_para_nome)
    norm_para_nome = {_norm(n): n for n in ativas["desc_nome"]}

    # --- Produtos (grupo via desc_linha; dt_envio p/ recebimento) -------
    cols_prod = ["sk_produto", "cod_sku_pai", "desc_item", "desc_linha", "desc_grupo_wgb",
                 "desc_sub_grupo_wbg", "desc_material", "dt_envio", "desc_colecao", "url"]
    prod = _ler_excel(config.ARQ_PRODUTOS, "Consulta1", usecols=cols_prod)
    prod = prod.dropna(subset=["sk_produto", "cod_sku_pai"]).drop_duplicates("sk_produto")
    dt_envio = pd.to_datetime(prod["dt_envio"], errors="coerce")
    dt_envio = dt_envio.where(dt_envio >= pd.Timestamp("2015-01-01"))  # descarta lixo (1900)
    produtos = pd.DataFrame({
        "sku_filho": prod["sk_produto"].astype("int64").astype(str),
        "sku_pai": prod["cod_sku_pai"].astype(str),
        "descricao": prod["desc_item"].astype(str),
        "linha": prod["desc_linha"].astype(str),                          # Linha (ROUPA/HOME/ACESSÓRIO)
        "grupo": prod["desc_grupo_wgb"].astype(str),                      # Grupo merchandising (display/filtro)
        "subgrupo": prod["desc_sub_grupo_wbg"].astype(str),               # Subgrupo (BLUSA/COLAR)
        "colecao": prod["desc_colecao"].astype(str),                      # coleção (filtro/tabela)
        "grupo_limite": prod["desc_linha"].map(config.grupo_de_linha),   # Home/Acessórios/Roupa (limite de peças)
        "grupo_merc": prod["desc_grupo_wgb"].astype(str),                 # = grupo (usado por cobertura/sazonalidade)
        "materia": prod["desc_material"].map(config.materia_prima_de),    # matéria-prima predominante
        "dt_envio": dt_envio.values,
        "foto_url": prod["url"].astype("string"),                         # foto do produto (coluna W)
    })

    # --- Estoque -------------------------------------------------------
    est = _ler_excel(config.ARQ_ESTOQUE, "Consulta1")
    est["sku_filho"] = est["sk_produto"].astype("int64").astype(str)

    # Status do produto por SKU (foto atual) — antes de filtrar, para a tabela/filtros.
    sku_status = (est.dropna(subset=["desc_status_produto"])
                  .groupby("sku_filho")["desc_status_produto"].first()
                  .rename("status").reset_index())
    produtos = produtos.merge(sku_status, on="sku_filho", how="left")
    produtos["status"] = produtos["status"].fillna("—")

    # Filtra status permitidos para remanejamento.
    est = est[est["desc_status_produto"].isin(config.STATUS_ESTOQUE_PERMITIDOS)]

    # Estoque em loja (status Estoque, localidade de loja válida).
    el = est[(est["status_estoque"] == "Estoque") & (est["sk_localidade"].isin(lojas_validas))].copy()
    el["loja"] = el["sk_localidade"].map(sk_para_nome)
    estoque_loja = (el.groupby(["loja", "sku_filho"])["qtde"].sum()
                    .reset_index().rename(columns={"qtde": "qtd"}))
    estoque_loja = estoque_loja[estoque_loja["qtd"] > 0]

    # SKUs que têm estoque com status permitido em algum lugar (loja/CD/trânsito).
    skus_permitidos = pd.DataFrame({"sku_filho": est["sku_filho"].unique()})

    # Estoque no CD disponível para reposição (apenas CDES Vendas).
    cd = est[(est["status_estoque"] == "Estoque")
             & (est["localidade"].isin(config.CD_LOCALIDADES_DISPONIVEIS))].copy()
    estoque_cd = (cd.groupby("sku_filho")["qtde"].sum()
                  .reset_index().rename(columns={"qtde": "qtd"}))

    # Itens em trânsito para a loja.
    tr = est[(est["status_estoque"] == "Transito") & (est["sk_localidade"].isin(lojas_validas))].copy()
    tr["loja_destino"] = tr["sk_localidade"].map(sk_para_nome)
    transito = (tr.groupby(["sku_filho", "loja_destino"])["qtde"].sum()
                .reset_index().rename(columns={"qtde": "qtd"}))

    # --- Vendas (ano corrente) ------------------------------------------
    cols_ven = ["dt_transacao", "sk_produto", "cod_sku_pai", "qtd_produto",
                "flag_liquidacao", "tipo_venda", "desc_nome"]
    ven = _ler_excel(config.ARQS_VENDAS[-1], "Base_Vendas", usecols=cols_ven)
    ven = ven[ven["tipo_venda"] == "venda"].copy()
    ven["loja"] = ven["desc_nome"].map(lambda n: norm_para_nome.get(_norm(n)))
    ven = ven.dropna(subset=["loja", "cod_sku_pai"])
    vendas = pd.DataFrame({
        "loja": ven["loja"],
        "sku_filho": ven["sk_produto"].astype("int64").astype(str),
        "sku_pai": ven["cod_sku_pai"].astype(str),
        "data": pd.to_datetime(ven["dt_transacao"]),
        "qtd": pd.to_numeric(ven["qtd_produto"], errors="coerce").fillna(0),
        "liquidacao": pd.to_numeric(ven["flag_liquidacao"], errors="coerce").fillna(0).astype(int),
    })
    vendas = vendas[vendas["qtd"] > 0]

    # --- Recebimento: snapshot (quando maduro) OU dt_envio + leadtime ----
    receb_envio = estoque_loja[["loja", "sku_filho"]].merge(
        produtos[["sku_filho", "dt_envio"]], on="sku_filho", how="left")
    receb_envio["data_recebimento"] = receb_envio["dt_envio"] + pd.Timedelta(days=config.LEADTIME_DIAS)
    receb_envio = receb_envio.dropna(subset=["data_recebimento"])[["loja", "sku_filho", "data_recebimento"]]

    snap = estoque_loja[["loja", "sku_filho", "qtd"]].rename(columns={"qtd": "qtde"})
    snapshot.gravar_snapshot(snap, hoje)
    receb_hist = snapshot.recebimento_estimado()

    # Prioriza o histórico salvo; completa com dt_envio+leadtime.
    if not receb_hist.empty:
        recebimento = pd.concat([receb_hist, receb_envio]).drop_duplicates(
            subset=["loja", "sku_filho"], keep="first")
    else:
        recebimento = receb_envio

    return {
        "produtos": produtos,
        "estoque_loja": estoque_loja,
        "estoque_cd": estoque_cd,
        "transito": transito,
        "vendas": vendas,
        "recebimento": recebimento,
        "skus_permitidos": skus_permitidos,
    }


def carregar_excel(hoje: date | None = None, usar_cache: bool = True) -> dict[str, pd.DataFrame]:
    """Carrega as bases reais, com cache diário (pickle) para abrir em segundos."""
    import pickle

    hoje = hoje or config.data_referencia()
    cache = config.PASTA_CACHE / f"dados_{hoje:%Y%m%d}.pkl"

    if usar_cache and cache.exists():
        with open(cache, "rb") as f:
            return pickle.load(f)

    dados = _build_excel(hoje)

    config.PASTA_CACHE.mkdir(parents=True, exist_ok=True)
    with open(cache, "wb") as f:
        pickle.dump(dados, f)
    return dados


# ---------------------------------------------------------------------------
# Fonte MOCK (dados de exemplo determinísticos)
# ---------------------------------------------------------------------------
def carregar_mock(hoje: date | None = None) -> dict[str, pd.DataFrame]:
    hoje = hoje or config.data_referencia()
    rng = np.random.default_rng(42)

    lojas = [f"L{n:02d}" for n in range(1, 9)]
    pais = [f"P{n:03d}" for n in range(100, 106)]
    tamanhos = ["P", "M", "G", "GG"]
    grupos = ["Home", "Acessórios", "Roupa"]

    produtos = pd.DataFrame(
        [{"sku_filho": f"{pai}-{tam}", "sku_pai": pai,
          "descricao": f"Produto {pai} tam {tam}",
          "linha": grupos[int(pai[-1]) % 3].upper(), "colecao": "INVERNO 2026",
          "status": "NOVIDADE",
          "grupo": "GRUPO " + grupos[int(pai[-1]) % 3], "subgrupo": "GERAL",
          "grupo_limite": grupos[int(pai[-1]) % 3],
          "grupo_merc": "GRUPO " + grupos[int(pai[-1]) % 3],
          "materia": "Não informado", "foto_url": ""}
         for pai in pais for tam in tamanhos]
    )
    filhos = produtos["sku_filho"].tolist()

    estoque_rows = []
    for loja in lojas:
        for sku in filhos:
            q = int(rng.choice([0, 0, 1, 2, 3, 5, 8], p=[.30, .10, .18, .15, .12, .10, .05]))
            if q > 0:
                estoque_rows.append({"loja": loja, "sku_filho": sku, "qtd": q})
    estoque_loja = pd.DataFrame(estoque_rows)

    estoque_cd = pd.DataFrame(
        [{"sku_filho": sku,
          "qtd": int(rng.choice([0, 0, 0, 2, 6], p=[.45, .20, .10, .15, .10]))}
         for sku in filhos]
    )

    transito_rows = []
    for sku in rng.choice(filhos, size=8, replace=False):
        transito_rows.append({"sku_filho": sku, "loja_destino": rng.choice(lojas),
                              "qtd": int(rng.integers(1, 4))})
    transito = pd.DataFrame(transito_rows)

    fator_loja = {loja: f for loja, f in zip(lojas, rng.uniform(0.2, 1.6, len(lojas)))}
    vendas_rows = []
    for loja in lojas:
        for sku in filhos:
            pai = sku.rsplit("-", 1)[0]
            n_vendas = rng.poisson(fator_loja[loja] * rng.uniform(0.0, 0.8) * 12)
            for _ in range(int(n_vendas)):
                vendas_rows.append({
                    "loja": loja, "sku_filho": sku, "sku_pai": pai,
                    "data": pd.Timestamp(hoje - timedelta(days=int(rng.integers(0, 120)))),
                    "qtd": int(rng.integers(1, 3)), "liquidacao": 0,
                })
    vendas = pd.DataFrame(vendas_rows)

    receb_rows = [{"loja": r["loja"], "sku_filho": r["sku_filho"],
                   "data_recebimento": pd.Timestamp(hoje - timedelta(days=int(rng.integers(3, 90))))}
                  for _, r in estoque_loja.iterrows()]
    recebimento = pd.DataFrame(receb_rows)

    return {
        "produtos": produtos, "estoque_loja": estoque_loja, "estoque_cd": estoque_cd,
        "transito": transito, "vendas": vendas, "recebimento": recebimento,
        "skus_permitidos": pd.DataFrame({"sku_filho": filhos}),
    }


def carregar_dados(hoje: date | None = None) -> dict[str, pd.DataFrame]:
    if config.FONTE_DADOS == "mock":
        return carregar_mock(hoje)
    return carregar_excel(hoje)

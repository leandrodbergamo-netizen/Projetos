"""Aderência de remanejamento (aba Alertas).

O usuário sobe um CSV com o remanejamento solicitado (loja doadora, loja
receptora, sku pai, tamanho, qtd, data) e o app estima quanto foi de fato
transferido, cruzando com o que está disponível na nuvem: estoque atual,
vendas do ano (com data) e trânsito atual.

Sem histórico de estoque na nuvem, o atendimento é estimado por um waterfall
sobre a quantidade solicitada de cada linha:
  1. o que AINDA está na doadora não saiu (não atendido);
  2. do restante, o que a doadora VENDEU desde a data virou venda (não atendido);
  3. o que sobra é considerado TRANSFERIDO (atendido).
O trânsito para a receptora e o estoque atual dela entram como contraponto
(evidência), não como critério do score.

Funções puras (bytes/DataFrames -> DataFrames/dict), sem Streamlit — testáveis
fora do app.
"""
from __future__ import annotations

import io
from datetime import date

import pandas as pd

import config

# header normalizado (config.norm_loja: sem acento, minúsculo) -> nome canônico
COLUNAS = {
    "loja doadora": "loja_doadora",
    "doadora": "loja_doadora",
    "loja receptora": "loja_receptora",
    "receptora": "loja_receptora",
    "sku pai": "sku_pai",
    "sku_pai": "sku_pai",
    "tamanho": "tamanho",
    "qtd": "qtd",
    "quantidade": "qtd",
    "data": "data",
}
OBRIGATORIAS = ["loja_doadora", "loja_receptora", "sku_pai", "tamanho", "qtd", "data"]

# Tamanhos tratados como coringa (casam com pai de filho único, sem grade).
CORINGAS = {"", "-", "—", "U", "UNICO", "NAN", "NONE"}

DETALHE_COLS = ["loja_doadora", "loja_receptora", "sku_pai", "tamanho", "sku_filho",
                "qtd", "data", "nao_saiu", "virou_venda", "transferido",
                "transito_receptora", "estoque_receptora", "classificacao"]


def _norm_txt(t) -> str:
    """Normaliza texto para comparação (sem acento, maiúsculo, sem espaços extras)."""
    return config.norm_loja(t).upper()


def _norm_sku(t) -> str:
    s = str(t).strip()
    return s[:-2] if s.endswith(".0") else s


def ler_csv(conteudo: bytes) -> pd.DataFrame:
    """bytes -> DataFrame cru (tudo string) com colunas canônicas.

    Aceita separador ";" (padrão pt-BR) ou ",", encoding utf-8/utf-8-sig ou
    latin-1. Levanta ValueError com mensagem amigável se faltarem colunas.
    """
    texto = None
    for enc in ("utf-8-sig", "latin-1"):
        try:
            texto = conteudo.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if texto is None:
        raise ValueError("Não foi possível ler o arquivo (encoding não reconhecido).")

    df = pd.read_csv(io.StringIO(texto), sep=";", dtype=str)
    if df.shape[1] <= 1:  # provavelmente separado por vírgula
        df = pd.read_csv(io.StringIO(texto), sep=",", dtype=str)

    ren = {}
    for c in df.columns:
        chave = config.norm_loja(c)
        if chave in COLUNAS and COLUNAS[chave] not in ren.values():
            ren[c] = COLUNAS[chave]
    df = df.rename(columns=ren)

    faltam = [c for c in OBRIGATORIAS if c not in df.columns]
    if faltam:
        raise ValueError(
            "Colunas não encontradas no CSV: " + ", ".join(faltam)
            + ". Esperado (separado por ';'): loja doadora; loja receptora; "
              "sku pai; tamanho; qtd; data.")

    df = df[OBRIGATORIAS].fillna("")
    return df[~(df == "").all(axis=1)].reset_index(drop=True)


def mapa_grade(produtos: pd.DataFrame) -> tuple[dict, set]:
    """(sku_pai, TAMANHO normalizado) -> sku_filho, e o conjunto de chaves
    ambíguas (2+ filhos no mesmo tamanho). Pai de filho único também entra
    com a chave coringa (sku_pai, "*")."""
    grade: dict[tuple[str, str], str] = {}
    ambiguas: set[tuple[str, str]] = set()
    base = produtos[["sku_pai", "tamanho", "sku_filho"]].drop_duplicates()
    for pai, tam, filho in base.itertuples(index=False):
        chave = (str(pai), _norm_txt(tam))
        if chave in grade and grade[chave] != filho:
            ambiguas.add(chave)
        else:
            grade[chave] = filho
    n_filhos = base.groupby("sku_pai")["sku_filho"].nunique()
    for pai in n_filhos[n_filhos == 1].index:
        filho = base.loc[base["sku_pai"] == pai, "sku_filho"].iloc[0]
        grade[(str(pai), "*")] = filho
    return grade, ambiguas


def validar(cru: pd.DataFrame, produtos: pd.DataFrame,
            lojas_conhecidas: set[str], hoje: date
            ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separa o CSV cru em (validas, invalidas) — nunca aborta o lote.

    validas: lojas canônicas, sku_filho mapeado, qtd int, data Timestamp.
    invalidas: linha original + coluna `motivo`.
    """
    norm_para_loja = {config.norm_loja(n): n for n in lojas_conhecidas}
    grade, ambiguas = mapa_grade(produtos)
    pais = set(produtos["sku_pai"].astype(str))

    validas, invalidas = [], []
    for _, r in cru.iterrows():
        motivo = None
        doa = norm_para_loja.get(config.norm_loja(r["loja_doadora"]))
        rec = norm_para_loja.get(config.norm_loja(r["loja_receptora"]))
        sku_pai = _norm_sku(r["sku_pai"])
        qtd = pd.to_numeric(str(r["qtd"]).replace(",", "."), errors="coerce")
        data = pd.to_datetime(r["data"], dayfirst=True, errors="coerce")
        tam = _norm_txt(r["tamanho"])
        filho = None

        if pd.isna(qtd) or qtd <= 0:
            motivo = "qtd inválida"
        elif pd.isna(data):
            motivo = "data inválida (use dd/mm/aaaa)"
        elif data.date() > hoje:
            motivo = "data futura"
        elif doa is None:
            motivo = "loja doadora desconhecida"
        elif rec is None:
            motivo = "loja receptora desconhecida"
        elif doa == rec:
            motivo = "doadora igual à receptora"
        elif sku_pai not in pais:
            motivo = "sku pai inexistente"
        else:
            chave = (sku_pai, tam)
            if chave in ambiguas:
                motivo = "grade ambígua (2+ SKUs no mesmo tamanho)"
            elif tam not in CORINGAS and chave in grade:
                filho = grade[chave]
            elif (sku_pai, "*") in grade:
                filho = grade[(sku_pai, "*")]
            else:
                motivo = "tamanho sem correspondência na grade"

        if motivo:
            inv = r.to_dict()
            inv["motivo"] = motivo
            invalidas.append(inv)
        else:
            validas.append({"loja_doadora": doa, "loja_receptora": rec,
                            "sku_pai": sku_pai, "tamanho": str(r["tamanho"]).strip() or "—",
                            "sku_filho": filho, "qtd": int(qtd), "data": data})

    cols_inv = list(cru.columns) + ["motivo"]
    return (pd.DataFrame(validas, columns=["loja_doadora", "loja_receptora", "sku_pai",
                                           "tamanho", "sku_filho", "qtd", "data"]),
            pd.DataFrame(invalidas, columns=cols_inv))


def calcular(validas: pd.DataFrame, estoque_loja: pd.DataFrame,
             transito: pd.DataFrame, vendas: pd.DataFrame) -> dict:
    """Waterfall por linha, com pools compartilhados por (doadora, sku_filho)
    para não contar o mesmo estoque/venda duas vezes quando o CSV repete o par.

    Retorna {"detalhe": DataFrame, "kpis": dict}. KPIs: pct_pecas (Σ transferido
    ÷ Σ solicitado), pct_skus (linhas 100% atendidas ÷ linhas válidas) e
    score = média dos dois.
    """
    kpis_zero = {"pecas_solicitadas": 0, "pecas_transferidas": 0, "linhas": 0,
                 "linhas_atendidas": 0, "pct_pecas": 0.0, "pct_skus": 0.0,
                 "score": 0.0}
    if validas.empty:
        return {"detalhe": pd.DataFrame(columns=DETALHE_COLS), "kpis": kpis_zero}

    est_atual = estoque_loja.groupby(["loja", "sku_filho"])["qtd"].sum().to_dict()
    tra_atual = (transito.groupby(["sku_filho", "loja_destino"])["qtd"].sum().to_dict()
                 if not transito.empty else {})
    vendas_grp = {chave: g[["data", "qtd"]]
                  for chave, g in vendas.groupby(["loja", "sku_filho"])}

    est_pool = dict(est_atual)          # consumido pelo "não saiu"
    venda_consumida: dict[tuple, float] = {}

    linhas = []
    for _, r in validas.sort_values("data", kind="stable").iterrows():
        d, f, q = r["loja_doadora"], r["sku_filho"], int(r["qtd"])

        nao_saiu = min(q, int(est_pool.get((d, f), 0)))
        est_pool[(d, f)] = est_pool.get((d, f), 0) - nao_saiu

        vg = vendas_grp.get((d, f))
        venda_desde = float(vg.loc[vg["data"] >= r["data"], "qtd"].sum()) if vg is not None else 0.0
        venda_disp = max(venda_desde - venda_consumida.get((d, f), 0.0), 0.0)
        virou_venda = min(q - nao_saiu, int(venda_disp))
        venda_consumida[(d, f)] = venda_consumida.get((d, f), 0.0) + virou_venda

        transferido = q - nao_saiu - virou_venda
        if transferido >= q:
            classif = "Atendido"
        elif transferido > 0:
            classif = "Parcial"
        elif virou_venda > 0:
            classif = "Venda na doadora"
        else:
            classif = "Não atendido"

        linhas.append({
            "loja_doadora": d, "loja_receptora": r["loja_receptora"],
            "sku_pai": r["sku_pai"], "tamanho": r["tamanho"], "sku_filho": f,
            "qtd": q, "data": r["data"], "nao_saiu": nao_saiu,
            "virou_venda": virou_venda, "transferido": transferido,
            "transito_receptora": int(tra_atual.get((f, r["loja_receptora"]), 0)),
            "estoque_receptora": int(est_atual.get((r["loja_receptora"], f), 0)),
            "classificacao": classif,
        })

    detalhe = pd.DataFrame(linhas, columns=DETALHE_COLS)
    total_q = int(detalhe["qtd"].sum())
    total_t = int(detalhe["transferido"].sum())
    atendidas = int((detalhe["classificacao"] == "Atendido").sum())
    pct_pecas = total_t / total_q if total_q else 0.0
    pct_skus = atendidas / len(detalhe) if len(detalhe) else 0.0
    return {"detalhe": detalhe,
            "kpis": {"pecas_solicitadas": total_q, "pecas_transferidas": total_t,
                     "linhas": len(detalhe), "linhas_atendidas": atendidas,
                     "pct_pecas": pct_pecas, "pct_skus": pct_skus,
                     "score": (pct_pecas + pct_skus) / 2}}

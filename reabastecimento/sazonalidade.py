"""Curva de sazonalidade SEMANAL a partir do histórico de vendas (2022–2025).

Índice sazonal por segmento **grupo × subgrupo × matéria-prima** (com fallback
para grupo×subgrupo e para grupo quando não há material). Base full price
(exclui liquidação) para refletir a demanda; liquidação e feriados/emendas
entram como ajustes na previsão.

A construção lê ~2,3 milhões de linhas — é pesada, então o resultado fica em
cache (data/curva_sazonal.parquet). Reconstrua quando atualizar o histórico.
"""
from __future__ import annotations

import pandas as pd

import config
import feriados

# Colunas necessárias do histórico de vendas (acelera a leitura).
_COLS = ["dt_transacao", "sk_produto", "grupo", "subgrupo",
         "qtd_produto", "flag_liquidacao", "tipo_venda"]


def _material_por_sku() -> pd.DataFrame:
    prod = pd.read_excel(config.ARQ_PRODUTOS, sheet_name="Consulta1",
                         usecols=["sk_produto", "desc_material"])
    prod = prod.drop_duplicates("sk_produto")
    prod["materia"] = prod["desc_material"].map(config.materia_prima_de)
    return prod[["sk_produto", "materia"]]


def construir_curva(salvar: bool = True) -> pd.DataFrame:
    mat = _material_por_sku()

    partes = []
    for arq in config.ARQS_VENDAS[:-1]:  # históricos (2022..2025); 2026 é o ano corrente
        if not arq.exists():
            continue
        df = pd.read_excel(arq, sheet_name="Base_Vendas", usecols=_COLS)
        df = df[(df["tipo_venda"] == "venda") & (df["flag_liquidacao"] == 0)]  # full price
        df["dt_transacao"] = pd.to_datetime(df["dt_transacao"])
        df["ano"] = df["dt_transacao"].dt.year
        df["semana"] = df["dt_transacao"].dt.isocalendar().week.astype(int)
        df = df.merge(mat, on="sk_produto", how="left")
        df["materia"] = df["materia"].fillna("Não informado")
        df["grupo"] = df["grupo"].fillna("SEM_GRUPO")
        df["subgrupo"] = df["subgrupo"].fillna("SEM_SUBGRUPO")
        partes.append(df[["ano", "semana", "grupo", "subgrupo", "materia", "qtd_produto"]])

    base = pd.concat(partes, ignore_index=True)

    # Índice = venda média da semana / venda média geral, por segmento,
    # em 3 níveis de granularidade (com fallback).
    curvas = []
    for nivel, chaves in [
        ("g_sg_mat", ["grupo", "subgrupo", "materia"]),
        ("g_sg", ["grupo", "subgrupo"]),
        ("g", ["grupo"]),
    ]:
        sem = base.groupby(chaves + ["ano", "semana"])["qtd_produto"].sum().reset_index()
        media = sem.groupby(chaves)["qtd_produto"].transform("mean")
        sem["indice"] = sem["qtd_produto"] / media
        idx = sem.groupby(chaves + ["semana"])["indice"].mean().reset_index()
        idx["nivel"] = nivel
        # normaliza colunas de chave ausentes
        for c in ["grupo", "subgrupo", "materia"]:
            if c not in idx.columns:
                idx[c] = "*"
        curvas.append(idx[["nivel", "grupo", "subgrupo", "materia", "semana", "indice"]])

    curva = pd.concat(curvas, ignore_index=True)
    if salvar:
        config.CURVA_SAZONAL.parent.mkdir(parents=True, exist_ok=True)
        curva.to_parquet(config.CURVA_SAZONAL, index=False)
    return curva


def carregar_curva() -> pd.DataFrame | None:
    if config.CURVA_SAZONAL.exists():
        return pd.read_parquet(config.CURVA_SAZONAL)
    return None


def indice(curva: pd.DataFrame, grupo: str, subgrupo: str, materia: str,
           semana: int) -> float:
    """Índice sazonal com fallback: g_sg_mat -> g_sg -> g -> 1.0."""
    if curva is None:
        return 1.0
    for nivel, filtro in [
        ("g_sg_mat", (curva["grupo"] == grupo) & (curva["subgrupo"] == subgrupo) & (curva["materia"] == materia)),
        ("g_sg", (curva["grupo"] == grupo) & (curva["subgrupo"] == subgrupo)),
        ("g", (curva["grupo"] == grupo)),
    ]:
        m = curva[(curva["nivel"] == nivel) & filtro & (curva["semana"] == semana)]
        if not m.empty:
            return float(m["indice"].iloc[0])
    return 1.0


def prever(media_semanal: float, grupo: str, subgrupo: str, materia: str,
           ano: int, semana: int, curva: pd.DataFrame | None = None) -> float:
    """Venda prevista da semana = média recente × índice sazonal × fator de feriado."""
    curva = curva if curva is not None else carregar_curva()
    return (media_semanal
            * indice(curva, grupo, subgrupo, materia, semana)
            * feriados.fator_semana(ano, semana))


if __name__ == "__main__":
    import time
    t0 = time.time()
    c = construir_curva()
    print("Curva construída em %.0fs | linhas: %d" % (time.time() - t0, len(c)))

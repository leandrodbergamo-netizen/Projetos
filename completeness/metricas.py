# -*- coding: utf-8 -*-
"""Cálculos de apresentação: séries, % por campo e as checagens de alerta.

Toda leitura de negócio do app passa por aqui — as regras de coleta e
elegibilidade ficam em analise.py e não são recalculadas nesta camada.
"""
from __future__ import annotations

import pandas as pd

import config

# Índices dos campos que entram na média de completeness (Alt-text fica fora).
CAMPOS_ATIVOS = [i for i, c in enumerate(config.FLAGS) if c not in config.FLAGS_FORA_DA_MEDIA]
NOMES_ATIVOS = [config.FLAGS[i] for i in CAMPOS_ATIVOS]
MEDIA = "Média"


def aplicar_filtros(df: pd.DataFrame, filtros: dict) -> pd.DataFrame:
    """Filtra por igualdade, ignorando chaves vazias e colunas ausentes."""
    for col, val in filtros.items():
        if val in (None, "", "Todas", "Todos") or col not in df.columns:
            continue
        df = df[df[col].astype(str) == str(val)]
    return df


def desde_inicio_serie(df: pd.DataFrame) -> pd.DataFrame:
    """Corta a série na quebra de 14/07/2026 (entrada dos filtros exceção/dt_envio)."""
    return df[df["data"] >= config.DATA_INICIO_SERIE] if "data" in df.columns else df


# --- Completeness -----------------------------------------------------------
def pct_por_campo(det: pd.DataFrame) -> pd.DataFrame:
    """% de produtos que atendem cada campo, no snapshot filtrado."""
    if det.empty:
        return pd.DataFrame({"campo": NOMES_ATIVOS, "pct": [0.0] * len(NOMES_ATIVOS)})
    return pd.DataFrame({
        "campo": NOMES_ATIVOS,
        "pct": [det[f"f{i}"].mean() * 100 for i in CAMPOS_ATIVOS],
    })


def completeness_por_produto(det: pd.DataFrame) -> pd.Series:
    """% de campos atendidos por produto (só os campos que entram na média)."""
    cols = [f"f{i}" for i in CAMPOS_ATIVOS]
    return det[cols].sum(axis=1) / len(cols)


def campos_faltantes(linha: pd.Series) -> str:
    return ", ".join(config.FLAGS[i] for i in CAMPOS_ATIVOS if not linha[f"f{i}"])


def serie_completeness(hist: pd.DataFrame, campos: list[str]) -> pd.DataFrame:
    """Série diária em formato longo (data, campo, pct) para os campos pedidos."""
    if hist.empty:
        return pd.DataFrame(columns=["data", "campo", "pct"])
    ag = hist.groupby("data", as_index=False).sum(numeric_only=True)
    linhas = []
    for campo in campos:
        if campo == MEDIA:
            soma = sum(ag[f"s{i}"] for i in CAMPOS_ATIVOS)
            pct = soma / (ag["n"] * len(CAMPOS_ATIVOS)) * 100
        else:
            i = config.FLAGS.index(campo)
            pct = ag[f"s{i}"] / ag["n"] * 100
        linhas.append(pd.DataFrame({"data": ag["data"], "campo": campo, "pct": pct}))
    return pd.concat(linhas, ignore_index=True)


def media_completeness(hist: pd.DataFrame) -> pd.DataFrame:
    """Série diária (data, n, pct) da média de completeness."""
    if hist.empty:
        return pd.DataFrame(columns=["data", "n", "pct"])
    ag = hist.groupby("data", as_index=False).sum(numeric_only=True)
    soma = sum(ag[f"s{i}"] for i in CAMPOS_ATIVOS)
    return pd.DataFrame({"data": ag["data"], "n": ag["n"],
                         "pct": soma / (ag["n"] * len(CAMPOS_ATIVOS)) * 100})


# --- Disponibilidade --------------------------------------------------------
def serie_disponibilidade(hist_disp: pd.DataFrame) -> pd.DataFrame:
    """Série diária (data, n_cand, n_site, pct) do % de candidatos no site."""
    if hist_disp.empty:
        return pd.DataFrame(columns=["data", "n_cand", "n_site", "pct"])
    ag = hist_disp.groupby("data", as_index=False)[["n_cand", "n_site"]].sum()
    ag["pct"] = ag["n_site"] / ag["n_cand"] * 100
    return ag


def disp_por_colecao(disp: pd.DataFrame, min_itens: int = 5, top: int = 14) -> pd.DataFrame:
    """% no site por coleção, só coleções com massa mínima."""
    if disp.empty:
        return pd.DataFrame(columns=["colecao", "n", "pct"])
    ag = disp.groupby("colecao").agg(n=("pai", "size"), site=("no_site", "sum")).reset_index()
    ag = ag[ag["n"] >= min_itens].nlargest(top, "n")
    ag["pct"] = ag["site"] / ag["n"] * 100
    return ag.sort_values("pct")


# --- Alertas ----------------------------------------------------------------
def _delta_disponibilidade(hist_disp: pd.DataFrame) -> tuple[float | None, str]:
    serie = serie_disponibilidade(hist_disp).sort_values("data")
    if len(serie) < 2:
        return None, ""
    hoje, ontem = serie.iloc[-1], serie.iloc[-2]
    return hoje["pct"] - ontem["pct"], str(ontem["data"])


def alertas(dados: dict[str, pd.DataFrame]) -> list[dict]:
    """As cinco checagens diárias. Cada item traz situação, valor e limiar."""
    lim = config.ALERTAS
    meta = dados["meta"].iloc[0] if not dados["meta"].empty else {}
    disp = dados["disponibilidade"]
    itens: list[dict] = []

    coletados = meta.get("coletados")
    coletados = None if pd.isna(coletados) else coletados
    itens.append({
        "nome": "Volume da coleta",
        "detalhe": f"produtos lidos do products.json (mínimo {config.numero(lim['coleta_min'])})",
        "valor": config.numero(int(coletados)) if coletados else "—",
        "alerta": bool(coletados) and int(coletados) < lim["coleta_min"],
        "indefinido": not coletados,
        "acao": "Suspeitar do endpoint products.json — foi o que quebrou em 17/08/2026.",
    })

    cand = int(meta.get("candidatos") or len(disp))
    itens.append({
        "nome": "SKUs elegíveis",
        "detalhe": f"SKUs pai com estoque ≥ {config.ESTOQUE_MIN_CANDIDATO} "
                   f"(mínimo {config.numero(lim['candidatos_min'])})",
        "valor": config.numero(cand),
        "alerta": cand < lim["candidatos_min"],
        "indefinido": False,
        "acao": "Checar se Base_Estoque/Base_Produtos foram atualizadas hoje.",
    })

    sem_match = int(meta.get("sem_match") or 0)
    itens.append({
        "nome": "Produtos sem cadastro",
        "detalhe": f"no site sem correspondência na Base_Produtos (máximo {lim['sem_match_max']})",
        "valor": config.numero(sem_match),
        "alerta": sem_match > lim["sem_match_max"],
        "indefinido": False,
        "acao": "SKU do site fora do padrão ou produto ainda não cadastrado.",
    })

    delta, dia_ant = _delta_disponibilidade(dados["hist_disp"])
    itens.append({
        "nome": "Queda de disponibilidade",
        "detalhe": f"variação vs {dia_ant or 'dia anterior'} (limite −{lim['queda_disp_pp']:.0f} p.p.)",
        "valor": (f"{'+' if delta > 0 else '−' if delta < 0 else ''}"
                  f"{config.numero(abs(delta), 1)} p.p." if delta is not None else "—"),
        "alerta": delta is not None and delta <= -lim["queda_disp_pp"],
        "indefinido": delta is None,
        "acao": "Produtos despublicados em bloco ou entrada de estoque sem publicação.",
    })

    fila = fila_de_publicacao(disp)
    urgentes = com_volume_no_cd(fila)
    novidades = int((urgentes["status"] == "NOVIDADE").sum()) if not urgentes.empty else 0
    itens.append({
        "nome": "Foto pronta e fora do site",
        "detalhe": f"{config.plural(len(urgentes), 'SKU')} com CD ≥ "
                   f"{lim['cd_min_foto_fora']} un. ({novidades} em NOVIDADE)",
        "valor": config.numero(len(fila)),
        "alerta": len(urgentes) > 0,
        "indefinido": False,
        "acao": "Fila de publicação: a foto existe e o estoque já está no CD.",
    })
    return itens


def fila_de_publicacao(disp: pd.DataFrame) -> pd.DataFrame:
    """Candidatos fora do site que já têm foto de e-commerce pronta.

    É o indicador que o time acompanha ("com foto e sem publicação"). O corte de
    volume no CD entra só como gatilho do alerta, via com_volume_no_cd().
    """
    if disp.empty:
        return disp
    fila = disp[(disp["no_site"] == 0) & (disp["tem_foto"] == 1)]
    return fila.sort_values(["qtde_cd", "qtde"], ascending=False)


def com_volume_no_cd(fila: pd.DataFrame) -> pd.DataFrame:
    """Subconjunto da fila com volume relevante parado no CD de vendas."""
    if fila.empty:
        return fila
    return fila[fila["qtde_cd"] >= config.ALERTAS["cd_min_foto_fora"]]

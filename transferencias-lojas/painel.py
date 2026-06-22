"""Painel SKU pai (linhas) × Loja (colunas).

Cada célula traz, em linhas separadas:
  QLF: peças vendidas (janela) | STK: estoque total | Dias: dias desde o recebimento
A cor de fundo da célula vem das peças vendidas (QLF). A 1ª coluna traz a foto do
SKU pai (se houver URL configurada) e a descrição.
"""
from __future__ import annotations

import html as _html
from datetime import date

import pandas as pd

import config

_COLS_FILTRO = ["linha", "grupo", "subgrupo", "colecao", "status"]


def _cor(v: float, vmax: float) -> str:
    """Cor de fundo (vermelho→amarelo→verde) proporcional à venda."""
    import matplotlib
    import matplotlib.colors as mcolors
    norm = mcolors.Normalize(vmin=0, vmax=max(vmax, 1))
    try:
        cmap = matplotlib.colormaps["RdYlGn"]
    except Exception:
        cmap = matplotlib.cm.get_cmap("RdYlGn")
    r, g, b, _ = cmap(norm(v))
    return f"rgba({int(r*255)},{int(g*255)},{int(b*255)},0.55)"


def _matrizes(dados, hoje, janela_dias, filtros, top_n):
    produtos = dados["produtos"]
    estoque_loja = dados["estoque_loja"]
    vendas = dados["vendas"]
    recebimento = dados.get("recebimento")

    prod = produtos
    for col in _COLS_FILTRO:
        vals = (filtros or {}).get(col)
        if vals:
            prod = prod[prod[col].isin(vals)]
    pais_validos = set(prod["sku_pai"])

    corte = pd.Timestamp(hoje) - pd.Timedelta(days=janela_dias)
    vend = vendas[(vendas["data"] >= corte) & (vendas["sku_pai"].isin(pais_validos))]
    top_pais = list(vend.groupby("sku_pai")["qtd"].sum()
                    .sort_values(ascending=False).head(top_n).index)
    if not top_pais:
        return None

    vend = vend[vend["sku_pai"].isin(top_pais)]
    mat_v = vend.pivot_table(index="sku_pai", columns="loja", values="qtd",
                             aggfunc="sum", fill_value=0)

    est = estoque_loja.merge(produtos[["sku_filho", "sku_pai"]], on="sku_filho", how="left")
    est = est[est["sku_pai"].isin(top_pais)]
    mat_e = est.pivot_table(index="sku_pai", columns="loja", values="qtd",
                            aggfunc="sum", fill_value=0)

    mat_v, mat_e = mat_v.align(mat_e, fill_value=0)

    # Dias desde o recebimento (mín. data de recebimento dos filhos do pai na loja).
    if recebimento is not None and not recebimento.empty:
        rec = recebimento.merge(produtos[["sku_filho", "sku_pai"]], on="sku_filho", how="left")
        rec = rec[rec["sku_pai"].isin(top_pais)]
        recmin = rec.groupby(["loja", "sku_pai"])["data_recebimento"].min()
        dias = ((pd.Timestamp(hoje) - recmin).dt.days).unstack("loja")
        dias = dias.reindex(index=mat_v.index, columns=mat_v.columns)
    else:
        dias = pd.DataFrame(index=mat_v.index, columns=mat_v.columns)

    # Ordena linhas (pais) por venda total desc.
    ordem = mat_v.sum(axis=1).sort_values(ascending=False).index
    mat_v, mat_e, dias = mat_v.loc[ordem], mat_e.loc[ordem], dias.loc[ordem]

    desc = produtos.groupby("sku_pai")["descricao"].first()
    # Foto do pai = 1ª URL não-vazia entre os filhos.
    if "foto_url" in produtos.columns:
        fu = produtos.dropna(subset=["foto_url"])
        fu = fu[fu["foto_url"].astype(str).str.startswith("http")]
        foto = fu.groupby("sku_pai")["foto_url"].first()
    else:
        foto = pd.Series(dtype="object")
    return mat_v, mat_e, dias, desc, foto


def opcoes_filtro(dados) -> dict:
    """Valores possíveis de cada filtro (coleção ordenada por recência)."""
    prod = dados["produtos"]
    op = {}
    for col in _COLS_FILTRO:
        if col not in prod.columns:
            op[col] = []
        elif col == "colecao":
            op[col] = config.colecoes_ordenadas(prod[col])
        else:
            op[col] = sorted(x for x in prod[col].dropna().unique() if str(x).strip())
    return op


def html_painel(dados, hoje: date, janela_dias: int = config.JANELA_VENDAS_DIAS,
                filtros: dict | None = None, top_n: int = 25) -> str | None:
    """Monta o painel como tabela HTML (foto + descrição + células QLF/STK/Dias)."""
    res = _matrizes(dados, hoje, janela_dias, filtros, top_n)
    if res is None:
        return None
    mat_v, mat_e, dias, desc, foto = res
    vmax = float(mat_v.to_numpy().max() or 1)
    lojas = list(mat_v.columns)

    css = """
    <style>
    .ve-wrap{overflow-x:auto}
    .ve{border-collapse:collapse;font-size:12px}
    .ve th,.ve td{border:1px solid #ddd;padding:4px 6px;text-align:center;vertical-align:middle}
    .ve th.prod,.ve td.prod{position:sticky;left:0;background:#fff;text-align:left;min-width:170px;z-index:1}
    .ve th{background:#f4f4f4;position:sticky;top:0}
    .ve img{height:46px;border-radius:4px;display:block;margin-bottom:2px}
    .ve .lin{white-space:nowrap}
    </style>
    """
    out = [css, '<div class="ve-wrap"><table class="ve">']
    out.append("<tr><th class='prod'>Produto</th>" +
               "".join(f"<th>{_html.escape(str(l))}</th>" for l in lojas) + "</tr>")

    for pai in mat_v.index:
        url = foto.get(pai)
        if (not url or str(url) == "nan") and config.URL_FOTO_TEMPLATE:
            try:
                url = config.URL_FOTO_TEMPLATE.format(sku_pai=pai, sku_filho="")
            except Exception:
                url = None
        img = f"<img src='{_html.escape(str(url))}' loading='lazy'/>" if url and str(url) != "nan" else ""
        d = _html.escape(str(desc.get(pai, "")))
        cels = [f"<td class='prod'>{img}<b>{_html.escape(str(pai))}</b><br>{d}</td>"]
        for l in lojas:
            v = int(mat_v.at[pai, l]); e = int(mat_e.at[pai, l])
            dd = dias.at[pai, l]
            d_txt = "—" if pd.isna(dd) else f"{int(dd)}"
            bg = _cor(v, vmax)
            cels.append(
                f"<td style='background:{bg}'><span class='lin'>QLF: {v}</span><br>"
                f"<span class='lin'>STK: {e}</span><br>"
                f"<span class='lin'>Dias: {d_txt}</span></td>")
        out.append("<tr>" + "".join(cels) + "</tr>")

    out.append("</table></div>")
    return "".join(out)

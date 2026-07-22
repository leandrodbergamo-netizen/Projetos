"""Painel SKU pai (linhas) × Loja (colunas).

Cada célula traz um número dominante (QLF = peças vendidas na janela) e o
estoque pequeno embaixo ("stk N"). Item parado ≥ 60 dias vira um ponto
terracota no canto. O fundo usa 3 tons pastel conforme a intensidade de
venda. A 1ª coluna (sticky) traz thumbnail, descrição e SKU pai.
"""
from __future__ import annotations

import html as _html
import re as _re
from datetime import date

import pandas as pd

import config

_COLS_FILTRO = ["linha", "grupo", "subgrupo", "colecao", "status"]

# Tons pastel de fundo (venda alta / média / baixa) — texto escuro sempre.
_TOM_ALTA, _TOM_MEDIA, _TOM_BAIXA = "#DCEBE4", "#FAF7EE", "#F7E8E2"
_DIAS_PARADO = 60
_SEM_SOUQ = _re.compile(r"^Souq\s+", flags=_re.IGNORECASE)


def _tom(v: float, vmax: float) -> str:
    """Fundo pastel em 3 faixas da venda (0 = branco neutro)."""
    if v <= 0:
        return "#FFFFFF"
    vmax = max(vmax, 1.0)
    if v >= (2 / 3) * vmax:
        return _TOM_ALTA
    if v >= (1 / 3) * vmax:
        return _TOM_MEDIA
    return _TOM_BAIXA


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
    """Monta o painel como tabela HTML (legenda + thumbnail + células QLF/stk)."""
    res = _matrizes(dados, hoje, janela_dias, filtros, top_n)
    if res is None:
        return None
    mat_v, mat_e, dias, desc, foto = res
    vmax = float(mat_v.to_numpy().max() or 1)
    lojas = list(mat_v.columns)

    css = f"""
    <style>
    .ve-leg{{display:flex;align-items:center;gap:14px;font:12px 'IBM Plex Sans',sans-serif;
        color:#1C1E21;background:#fff;border:1px solid #E4E2DD;border-bottom:none;
        border-radius:10px 10px 0 0;padding:8px 14px}}
    .ve-leg .sw{{display:inline-block;width:12px;height:12px;border-radius:3px;
        margin-right:5px;vertical-align:-1px;border:1px solid #E4E2DD}}
    .ve-leg .pt{{display:inline-block;width:7px;height:7px;border-radius:50%;
        background:#B04A3A;margin-right:5px;vertical-align:1px}}
    .ve-leg .dir{{margin-left:auto;color:#9A9E9C;font-size:11px}}
    .ve-wrap{{overflow-x:auto;border:1px solid #E4E2DD;border-radius:0 0 10px 10px;background:#fff}}
    .ve{{border-collapse:separate;border-spacing:0;font:12px 'IBM Plex Sans',sans-serif;
        color:#1C1E21;min-width:100%}}
    .ve th,.ve td{{border-bottom:1px solid #EDECE8;padding:5px 8px;text-align:center;
        vertical-align:middle}}
    .ve thead th{{position:sticky;top:0;background:#FAFAF8;color:#6B7075;font-size:10px;
        font-weight:600;text-transform:uppercase;letter-spacing:.05em;z-index:2;
        max-width:96px;white-space:normal;line-height:1.3;border-bottom:1px solid #E4E2DD}}
    .ve th.pfoto,.ve td.pfoto{{position:sticky;left:0;background:#fff;width:64px;
        min-width:64px;max-width:64px;z-index:1}}
    .ve th.pinfo,.ve td.pinfo{{position:sticky;left:64px;background:#fff;text-align:left;
        min-width:185px;max-width:210px;z-index:1;border-right:1px solid #E4E2DD}}
    .ve thead th.pfoto,.ve thead th.pinfo{{z-index:3;background:#FAFAF8}}
    .ve td{{position:relative;height:52px}}
    .ve .qlf{{font-size:14px;font-weight:600;font-variant-numeric:tabular-nums}}
    .ve .stk{{font-size:10px;color:#6B7075;font-variant-numeric:tabular-nums}}
    .ve .dot{{position:absolute;top:5px;right:6px;width:6px;height:6px;border-radius:50%;
        background:#B04A3A}}
    .ve img,.ve .noimg{{width:40px;height:40px;border-radius:6px;object-fit:cover;
        display:block;margin:0 auto}}
    .ve .noimg{{background:#ECEAE5}}
    .ve td.pfoto a{{display:block;width:40px;height:40px;margin:0 auto}}
    .ve td.pfoto img{{cursor:zoom-in;transition:transform .15s ease;
        transform-origin:left center}}
    .ve td.pfoto img:hover{{transform:scale(3.4);position:relative;z-index:60;
        border-radius:4px;box-shadow:0 6px 20px rgba(0,0,0,.3)}}
    .ve .pnome{{font-weight:500;line-height:1.3}}
    .ve .psku{{font:10px 'IBM Plex Mono',monospace;color:#9A9E9C}}
    </style>
    """
    leg = (f'<div class="ve-leg"><b>Legenda</b>'
           f'<span><span class="sw" style="background:{_TOM_ALTA}"></span>Venda alta</span>'
           f'<span><span class="sw" style="background:{_TOM_MEDIA}"></span>Venda média</span>'
           f'<span><span class="sw" style="background:{_TOM_BAIXA}"></span>Venda baixa</span>'
           f'<span><span class="pt"></span>Parado &gt; {_DIAS_PARADO} dias</span>'
           f'<span class="dir">QLF grande · stk pequeno</span></div>')

    out = [css, leg, '<div class="ve-wrap"><table class="ve">']
    cab = "".join(f"<th>{_html.escape(_SEM_SOUQ.sub('', str(l)))}</th>" for l in lojas)
    out.append("<thead><tr><th class='pfoto'>Foto</th><th class='pinfo'>Produto</th>"
               f"{cab}</tr></thead><tbody>")

    for pai in mat_v.index:
        url = foto.get(pai)
        if (not url or str(url) == "nan") and config.URL_FOTO_TEMPLATE:
            try:
                url = config.URL_FOTO_TEMPLATE.format(sku_pai=pai, sku_filho="")
            except Exception:
                url = None
        if url and str(url) != "nan":
            u = _html.escape(str(url))
            # Hover aproxima; clique abre a imagem original em nova guia.
            img = (f"<a href='{u}' target='_blank' rel='noopener' "
                   f"title='Clique para ampliar'><img src='{u}' loading='lazy'/></a>")
        else:
            img = "<span class='noimg'></span>"
        nome = _html.escape(str(desc.get(pai, "")).title())
        cels = [f"<td class='pfoto'>{img}</td>",
                f"<td class='pinfo'><div class='pnome'>{nome}</div>"
                f"<div class='psku'>{_html.escape(str(pai))}</div></td>"]
        for l in lojas:
            v = int(mat_v.at[pai, l]); e = int(mat_e.at[pai, l])
            dd = dias.at[pai, l]
            ponto = ""
            if not pd.isna(dd) and int(dd) >= _DIAS_PARADO:
                ponto = f"<span class='dot' title='Recebido há {int(dd)} dias'></span>"
            cels.append(
                f"<td style='background:{_tom(v, vmax)}'>{ponto}"
                f"<div class='qlf'>{v}</div><div class='stk'>stk {e}</div></td>")
        out.append("<tr>" + "".join(cels) + "</tr>")

    out.append("</tbody></table></div>")
    return "".join(out)

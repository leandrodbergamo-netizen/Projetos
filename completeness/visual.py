# -*- coding: utf-8 -*-
"""Identidade visual do app: estilo, cartões de indicador, gráficos e exportação."""
from __future__ import annotations

import io

import altair as alt
import pandas as pd
import streamlit as st

import config

TINTA = "#1a1d24"
MUDO = "#6b7280"
MARCA = "#1f3864"
LINHA = "#e5e7eb"
OK = "#16a34a"
ATENCAO = "#d97706"
RUIM = "#dc2626"

PALETA = [MARCA, "#d97706", "#16a34a", "#dc2626", "#7c3aed", "#0891b2", "#be185d",
          "#4d7c0f", "#b45309", "#1d4ed8", "#9333ea", "#0f766e", "#c2410c"]

_CSS = """
<style>
  .block-container { padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1500px; }
  h1, h2, h3 { color: %(tinta)s; letter-spacing: -0.01em; }

  .cabecalho { display:flex; align-items:baseline; gap:14px; flex-wrap:wrap;
               border-bottom:1px solid %(linha)s; padding-bottom:14px; margin-bottom:6px; }
  .cabecalho h1 { font-size:1.5rem; margin:0; font-weight:700; }
  .cabecalho .fonte { color:%(mudo)s; font-size:0.8rem; }

  .kpis { display:grid; gap:12px; margin:18px 0 6px;
          grid-template-columns:repeat(auto-fit, minmax(165px, 1fr)); }
  .kpi { background:#fff; border:1px solid %(linha)s; border-radius:12px; padding:13px 15px; }
  .kpi .rot { color:%(mudo)s; font-size:0.7rem; text-transform:uppercase;
              letter-spacing:.05em; font-weight:600; line-height:1.3; }
  .kpi .val { font-size:1.65rem; font-weight:700; line-height:1.25; margin-top:3px;
              font-variant-numeric:tabular-nums; }
  .kpi .var { font-size:0.72rem; margin-top:1px; font-weight:600; }
  .kpi.destaque { border-left:3px solid %(marca)s; }
  .sobe { color:%(ok)s; } .desce { color:%(ruim)s; } .igual { color:%(mudo)s; }

  .secao { font-size:0.95rem; font-weight:700; margin:22px 0 2px; }
  .nota { color:%(mudo)s; font-size:0.76rem; margin-bottom:8px; }

  .alerta { display:flex; gap:14px; align-items:flex-start; background:#fff;
            border:1px solid %(linha)s; border-left:3px solid %(ok)s;
            border-radius:10px; padding:12px 16px; margin-bottom:9px; }
  .alerta.on { border-left-color:%(ruim)s; background:#fef7f7; }
  .alerta.na { border-left-color:%(linha)s; }
  .alerta .txt { flex:1; }
  .alerta .nome { font-weight:700; font-size:0.9rem; }
  .alerta .det { color:%(mudo)s; font-size:0.78rem; }
  .alerta .acao { color:%(mudo)s; font-size:0.78rem; margin-top:3px; font-style:italic; }
  .alerta .num { font-size:1.25rem; font-weight:700; white-space:nowrap;
                 font-variant-numeric:tabular-nums; }
  .selo { font-size:0.68rem; font-weight:700; text-transform:uppercase; letter-spacing:.05em;
          padding:2px 9px; border-radius:99px; white-space:nowrap; }
  .selo.ok { background:#dcfce7; color:#14532d; }
  .selo.on { background:#fee2e2; color:#7f1d1d; }
  .selo.na { background:#f3f4f6; color:%(mudo)s; }

  div[data-testid="stDataFrame"] { border:1px solid %(linha)s; border-radius:10px; }
</style>
""" % {"tinta": TINTA, "mudo": MUDO, "marca": MARCA, "linha": LINHA, "ok": OK, "ruim": RUIM}


def aplicar_estilo() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def cabecalho(titulo: str, fonte: str) -> None:
    st.markdown(f'<div class="cabecalho"><h1>{titulo}</h1>'
                f'<span class="fonte">{fonte}</span></div>', unsafe_allow_html=True)


def secao(titulo: str, nota: str = "") -> None:
    st.markdown(f'<div class="secao">{titulo}</div>'
                + (f'<div class="nota">{nota}</div>' if nota else ""),
                unsafe_allow_html=True)


num = config.numero


def kpis(itens: list[dict]) -> None:
    """Cartões de indicador. Cada item: rotulo, valor, var (opcional), destaque, sentido."""
    cartoes = []
    for it in itens:
        var = ""
        if it.get("var") is not None:
            d = it["var"]
            # sentido=-1 quando cair é bom (ex.: produtos sem descrição).
            bom = d * it.get("sentido", 1)
            cls = "sobe" if bom > 0 else "desce" if bom < 0 else "igual"
            seta = "▲" if d > 0 else "▼" if d < 0 else "•"
            # "carga anterior", não "ontem": a rotina não roda todo dia (fim de
            # semana, PC desligado), então o dia anterior da série pode ser outro.
            var = (f'<div class="var {cls}">{seta} {num(abs(d), it.get("casas_var", 0))}'
                   f'{it.get("sufixo", "")} vs carga anterior</div>')
        cartoes.append(f'<div class="kpi{" destaque" if it.get("destaque") else ""}">'
                       f'<div class="rot">{it["rotulo"]}</div>'
                       f'<div class="val">{it["valor"]}</div>{var}</div>')
    st.markdown(f'<div class="kpis">{"".join(cartoes)}</div>', unsafe_allow_html=True)


def cartao_alerta(item: dict) -> None:
    estado = "na" if item.get("indefinido") else ("on" if item["alerta"] else "ok")
    texto = {"na": "sem dado", "on": "atenção", "ok": "ok"}[estado]
    st.markdown(
        f'<div class="alerta {estado}">'
        f'<div class="txt"><div class="nome">{item["nome"]}</div>'
        f'<div class="det">{item["detalhe"]}</div>'
        f'<div class="acao">{item["acao"]}</div></div>'
        f'<div style="text-align:right"><div class="num">{item["valor"]}</div>'
        f'<span class="selo {estado}">{texto}</span></div></div>',
        unsafe_allow_html=True)


# --- Gráficos ---------------------------------------------------------------
def _base(chart: alt.Chart) -> alt.Chart:
    return (chart.configure_view(strokeWidth=0)
            .configure_axis(labelColor=MUDO, titleColor=MUDO, labelFontSize=11,
                            titleFontSize=11, grid=True, gridColor="#f1f2f4",
                            domainColor=LINHA, tickColor=LINHA)
            .configure_legend(labelColor=TINTA, titleColor=MUDO, labelFontSize=11,
                              titleFontSize=11, symbolType="stroke", orient="bottom",
                              columns=4, direction="horizontal"))


def linha_temporal(df: pd.DataFrame, *, cor: str = "campo", titulo_y: str | None = None,
                   altura: int = 260, dominio: tuple | None = None) -> alt.Chart:
    """Série temporal em % com um traço por categoria."""
    escala = alt.Scale(domain=list(dominio)) if dominio else alt.Scale(zero=False, nice=True)
    enc = {
        "x": alt.X("data:T", title=None, axis=alt.Axis(format="%d/%m", tickCount=8)),
        "y": alt.Y("pct:Q", title=titulo_y, scale=escala,
                   axis=alt.Axis(format=".0f", labelExpr="datum.value + '%'")),
        "tooltip": [alt.Tooltip("data:T", title="Data", format="%d/%m/%Y"),
                    alt.Tooltip("pct:Q", title="%", format=".1f")],
    }
    if cor and cor in df.columns:
        enc["color"] = alt.Color(f"{cor}:N", title=None,
                                 scale=alt.Scale(range=PALETA))
        enc["tooltip"] = [alt.Tooltip(f"{cor}:N", title="Campo")] + enc["tooltip"]
    base = alt.Chart(df).encode(**enc)
    linha = base.mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=28, filled=True))
    if not (cor and cor in df.columns):
        linha = linha.mark_line(strokeWidth=2, color=MARCA,
                                point=alt.OverlayMarkDef(size=28, filled=True, color=MARCA))
    return _base(linha.properties(height=altura, width="container"))


def barras_percentuais(df: pd.DataFrame, campo: str, *, altura: int = 300) -> alt.Chart:
    """Barras horizontais 0-100% coloridas por faixa de saúde."""
    cor = alt.Color("faixa:N", scale=alt.Scale(domain=["Crítico", "Atenção", "Bom"],
                                               range=[RUIM, ATENCAO, OK]),
                    legend=None)
    df = df.assign(faixa=pd.cut(df["pct"], [-0.01, 60, 90, 100.01],
                                labels=["Crítico", "Atenção", "Bom"]))
    # Pior primeiro: quem precisa de ação fica no topo. Em gráfico em camadas o
    # sort="-x" não se propaga, então a ordem vem da própria lista de categorias.
    df = df.sort_values("pct")
    ordem = df[campo].astype(str).tolist()
    eixo_y = alt.Y(f"{campo}:N", title=None, sort=ordem)
    barras = alt.Chart(df).mark_bar(height=13, cornerRadiusEnd=3).encode(
        x=alt.X("pct:Q", title=None, scale=alt.Scale(domain=[0, 100]),
                axis=alt.Axis(labelExpr="datum.value + '%'")),
        y=eixo_y,
        color=cor,
        tooltip=[alt.Tooltip(f"{campo}:N", title=""), alt.Tooltip("pct:Q", title="%", format=".1f")])
    rotulo = alt.Chart(df).mark_text(align="left", dx=5, fontSize=11, color=MUDO).encode(
        x=alt.X("pct:Q", scale=alt.Scale(domain=[0, 100])),
        y=eixo_y,
        text=alt.Text("pct:Q", format=".0f"))
    return _base((barras + rotulo).properties(height=altura, width="container"))


# --- Exportação -------------------------------------------------------------
def para_excel(abas: dict[str, pd.DataFrame]) -> bytes:
    """Uma pasta .xlsx com uma aba por DataFrame, colunas dimensionadas."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as wr:
        for nome, df in abas.items():
            df.to_excel(wr, sheet_name=nome[:31], index=False)
            ws = wr.sheets[nome[:31]]
            cab = wr.book.add_format({"bold": True, "bg_color": "#f1f2f4", "border": 1})
            for i, col in enumerate(df.columns):
                largura = max(len(str(col)) + 2,
                              int(df[col].astype(str).str.len().max() or 0) + 2)
                ws.set_column(i, i, min(largura, 48))
                ws.write(0, i, col, cab)
            ws.freeze_panes(1, 0)
            ws.autofilter(0, 0, len(df), max(len(df.columns) - 1, 0))
    return buf.getvalue()


def botao_excel(rotulo: str, abas: dict[str, pd.DataFrame], arquivo: str, chave: str) -> None:
    st.download_button(rotulo, data=para_excel(abas), file_name=arquivo, key=chave,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

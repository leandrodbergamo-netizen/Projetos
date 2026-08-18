# -*- coding: utf-8 -*-
"""App de auditoria de completeness do catálogo Souq.

Três abas: completeness do catálogo publicado, disponibilidade dos SKUs
elegíveis no site e os alertas diários. Lê os CSVs da rotina local ou as
tabelas comp_* do Supabase (app na nuvem) — nunca recalcula regra de negócio.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Completeness · E-commerce Souq", page_icon="🏷️",
                   layout="wide", initial_sidebar_state="collapsed")

import config          # noqa: E402
import data_source     # noqa: E402
import imagens         # noqa: E402
import metricas        # noqa: E402
import visual          # noqa: E402


@st.cache_data(ttl=900, show_spinner="Carregando dados da auditoria…")
def carregar() -> dict[str, pd.DataFrame]:
    return data_source.carregar_dados()


def seletores(df: pd.DataFrame, especificacoes: list[tuple[str, str]], prefixo: str) -> dict:
    """Uma linha de filtros em cascata: cada um respeita os anteriores."""
    escolhas, filtrado = {}, df
    for col, (chave, rotulo) in zip(st.columns(len(especificacoes)), especificacoes):
        opcoes = ["Todas"] + sorted(filtrado[chave].dropna().astype(str).unique())
        with col:
            valor = st.selectbox(rotulo, opcoes, key=f"{prefixo}_{chave}")
        escolhas[chave] = valor
        if valor != "Todas":
            filtrado = filtrado[filtrado[chave].astype(str) == valor]
    return escolhas


def _delta(serie: pd.DataFrame, coluna: str) -> float | None:
    """Variação do último dia da série contra o dia anterior."""
    s = serie.sort_values("data")
    return None if len(s) < 2 else float(s.iloc[-1][coluna] - s.iloc[-2][coluna])


# ============================ CARGA ========================================
try:
    dados = carregar()
except FileNotFoundError as e:
    st.error(str(e))
    st.stop()

meta = dados["meta"].iloc[0] if not dados["meta"].empty else {}
det_todos = dados["detalhe"]
disp_todos = dados["disponibilidade"]
hist_todo = metricas.desde_inicio_serie(dados["historico"])
hist_disp_todo = metricas.desde_inicio_serie(dados["hist_disp"])

visual.aplicar_estilo()
visual.cabecalho(
    "Completeness · E-commerce Souq",
    f"souqstore.com.br × Base_Produtos × Base_Estoque · atualizado em "
    f"{meta.get('atualizado', '—')}")

with st.sidebar:
    st.markdown("### Fonte dos dados")
    st.caption(f"**{config.fonte_dados()}** · referência {meta.get('data', '—')}")
    if st.button("Recarregar dados", width="stretch"):
        st.cache_data.clear()
        st.rerun()
    st.markdown("---")
    st.caption(f"Série exibida a partir de {config.DATA_INICIO_SERIE} — data em que "
               f"entraram os filtros de SKU exceção e data de envio. Antes disso o "
               f"critério era outro e os números não são comparáveis.")

# ======================= GRANDES NÚMEROS ===================================
serie_disp_geral = metricas.serie_disponibilidade(hist_disp_todo)
serie_media_geral = metricas.media_completeness(hist_todo)
candidatos = int(meta.get("candidatos") or len(disp_todos))
publicados = int(meta.get("publicados") or disp_todos["no_site"].sum())
pct_disp = publicados / candidatos * 100 if candidatos else 0
fora_com_foto = int(meta.get("fora_com_foto")
                    or ((disp_todos["no_site"] == 0) & (disp_todos["tem_foto"] == 1)).sum())
media_hoje = float(serie_media_geral.iloc[-1]["pct"]) if not serie_media_geral.empty else 0

visual.kpis([
    {"rotulo": "SKUs elegíveis", "valor": visual.num(candidatos), "destaque": True,
     "var": _delta(serie_disp_geral, "n_cand")},
    {"rotulo": "Disponibilidade no site", "valor": f"{visual.num(pct_disp, 1)}%", "destaque": True,
     "var": _delta(serie_disp_geral, "pct"), "casas_var": 1, "sufixo": " p.p."},
    {"rotulo": "Fora do site", "valor": visual.num(candidatos - publicados), "sentido": -1,
     "var": (lambda d, s: None if d is None or s is None else d - s)(
         _delta(serie_disp_geral, "n_cand"), _delta(serie_disp_geral, "n_site"))},
    {"rotulo": "Com foto e sem publicação", "valor": visual.num(fora_com_foto), "destaque": True},
    {"rotulo": "Completeness média", "valor": f"{visual.num(media_hoje, 1)}%",
     "var": _delta(serie_media_geral, "pct"), "casas_var": 1, "sufixo": " p.p."},
    {"rotulo": "Produtos no site", "valor": visual.num(int(meta.get("no_site") or len(det_todos))),
     "var": _delta(serie_media_geral, "n")},
])

aba_comp, aba_disp, aba_alertas = st.tabs(
    ["  Completeness do catálogo  ", "  Disponibilidade no site  ", "  Alertas  "])

# ========================= ABA COMPLETENESS =================================
with aba_comp:
    filtros = seletores(det_todos, [("dept", "Departamento"), ("cat", "Categoria no site"),
                                    ("colecao", "Coleção"), ("tipo", "Tipo de produto"),
                                    ("status", "Status")], "c")
    det = metricas.aplicar_filtros(det_todos, filtros)
    hist = metricas.aplicar_filtros(hist_todo, filtros)
    det = det.assign(pct=metricas.completeness_por_produto(det) if not det.empty else [])

    if det.empty:
        st.info("Nenhum produto com essa combinação de filtros.")
    else:
        visual.kpis([
            {"rotulo": "Produtos no recorte", "valor": visual.num(len(det))},
            {"rotulo": "Completeness média", "valor": f"{visual.num(det['pct'].mean() * 100, 1)}%"},
            {"rotulo": "Sem descrição", "valor": visual.num(int((det["f0"] == 0).sum()))},
            {"rotulo": "Com menos de 3 fotos", "valor": visual.num(int((det["f7"] == 0).sum()))},
            {"rotulo": "Sem cor na descrição", "valor": visual.num(int((det["f3"] == 0).sum()))},
            {"rotulo": "Sem medidas", "valor": visual.num(int((det["f4"] == 0).sum()))},
        ])

        esq, dir_ = st.columns([1.25, 1], gap="large")
        with esq:
            visual.secao("Evolução do completeness",
                         "Média dos 13 campos cobrados (Alt-text fica fora do cálculo).")
            campos = st.multiselect(
                "Campos no gráfico", [metricas.MEDIA] + metricas.NOMES_ATIVOS,
                default=[metricas.MEDIA, "Descrição", "Medidas"],
                label_visibility="collapsed", key="c_campos")
            serie = metricas.serie_completeness(hist, campos or [metricas.MEDIA])
            if serie.empty:
                st.caption("Sem série histórica para este recorte.")
            else:
                serie["data"] = pd.to_datetime(serie["data"])
                st.altair_chart(visual.linha_temporal(serie, dominio=(0, 100)))
        with dir_:
            visual.secao("Completeness por campo, hoje", "Verde ≥ 90% · amarelo ≥ 60% · vermelho abaixo.")
            st.altair_chart(visual.barras_percentuais(metricas.pct_por_campo(det), "campo",
                                                      altura=330))

        incompletos = det[det["pct"] < 1].copy()
        visual.secao(f"Produtos com informação faltante · {visual.num(len(incompletos))} de "
                     f"{visual.num(len(det))}")
        f1, f2, f3 = st.columns([1.2, 1.6, 0.9])
        campo_falta = f1.selectbox("Campo faltante", ["Todos"] + metricas.NOMES_ATIVOS,
                                   label_visibility="collapsed", key="c_falta")
        busca = f2.text_input("Buscar produto", placeholder="Buscar produto…",
                              label_visibility="collapsed", key="c_busca")
        if campo_falta != "Todos":
            incompletos = incompletos[incompletos[f"f{config.FLAGS.index(campo_falta)}"] == 0]
        if busca:
            incompletos = incompletos[incompletos["titulo"].str.contains(busca, case=False, na=False)]
        incompletos = incompletos.sort_values("pct")
        tabela = pd.DataFrame({
            "Produto": incompletos["titulo"],
            "Categoria": incompletos["cat"],
            "Coleção": incompletos["colecao"],
            "Tipo": incompletos["tipo"],
            "Status": incompletos["status"],
            "Preço": incompletos["preco"],
            "% Compl.": incompletos["pct"] * 100,
            "Campos faltantes": incompletos.apply(metricas.campos_faltantes, axis=1),
            "Link": incompletos["url"],
        })
        with f3:
            visual.botao_excel("Exportar Excel", {"Completeness": tabela},
                               f"completeness_{meta.get('data', 'hoje')}.xlsx", "x_comp")
        st.dataframe(
            tabela, hide_index=True, width="stretch", height=440,
            column_config={
                "Preço": st.column_config.NumberColumn(format="R$ %.2f", width="small"),
                "% Compl.": st.column_config.ProgressColumn(format="%.0f%%", min_value=0,
                                                            max_value=100, width="small"),
                "Campos faltantes": st.column_config.TextColumn(width="large"),
                "Link": st.column_config.LinkColumn("", display_text="abrir", width="small"),
            })

# ======================= ABA DISPONIBILIDADE ================================
with aba_disp:
    filtros_d = seletores(disp_todos, [("colecao", "Coleção"), ("linha", "Linha"),
                                       ("grupo", "Grupo"), ("subgrupo", "Subgrupo"),
                                       ("status", "Status")], "d")
    c1, c2, c3, _ = st.columns([1, 1, 1, 2])
    grade = c1.selectbox("Grade", ["Todas", "Completa", "Quebrada"], key="d_grade")
    presenca = c2.selectbox("Presença no site", ["Fora do site", "No site", "Todos"], key="d_pres")
    foto = c3.selectbox("Foto de e-commerce", ["Todas", "Com foto", "Sem foto"], key="d_foto")

    disp = metricas.aplicar_filtros(disp_todos, filtros_d)
    hist_disp = metricas.aplicar_filtros(hist_disp_todo, filtros_d)
    if grade != "Todas":
        disp = disp[disp["grade_completa"] == (1 if grade == "Completa" else 0)]
        hist_disp = hist_disp[hist_disp["grade_completa"] == (1 if grade == "Completa" else 0)]
    if foto != "Todas":
        disp = disp[disp["tem_foto"] == (1 if foto == "Com foto" else 0)]

    if disp.empty:
        st.info("Nenhum SKU elegível com essa combinação de filtros.")
    else:
        fora = disp[disp["no_site"] == 0]
        no_site = disp[disp["no_site"] == 1]
        visual.kpis([
            {"rotulo": "SKUs elegíveis", "valor": visual.num(len(disp))},
            {"rotulo": "Publicados no site", "valor": visual.num(len(no_site))},
            {"rotulo": "Disponibilidade", "valor": f"{visual.num(len(no_site)/len(disp)*100, 1)}%"},
            {"rotulo": "Fora do site", "valor": visual.num(len(fora))},
            {"rotulo": "Fora com grade completa",
             "valor": visual.num(int((fora["grade_completa"] == 1).sum()))},
            {"rotulo": "Unidades fora do site", "valor": visual.num(int(fora["qtde"].sum()))},
        ])

        esq, dir_ = st.columns([1.25, 1], gap="large")
        with esq:
            visual.secao("Evolução da disponibilidade",
                         f"% dos SKUs pai com estoque ≥ {config.ESTOQUE_MIN_CANDIDATO} "
                         f"publicados no site.")
            serie = metricas.serie_disponibilidade(hist_disp)
            if serie.empty:
                st.caption("Sem série histórica para este recorte.")
            else:
                serie["data"] = pd.to_datetime(serie["data"])
                st.altair_chart(visual.linha_temporal(serie, cor="", altura=300))
        with dir_:
            visual.secao("Disponibilidade por coleção", "Coleções com 5 SKUs ou mais.")
            st.altair_chart(visual.barras_percentuais(metricas.disp_por_colecao(disp), "colecao",
                                                      altura=300))

        alvo = {"Fora do site": fora, "No site": no_site, "Todos": disp}[presenca]
        alvo = alvo.sort_values("qtde", ascending=False)
        b1, b2 = st.columns([2.6, 0.9])
        with b1:
            visual.secao(f"{presenca} · {config.plural(len(alvo), 'SKU')}")
        busca_d = b1.text_input("Buscar", placeholder="Buscar produto ou código…",
                                label_visibility="collapsed", key="d_busca")
        if busca_d:
            chave = alvo["item"].astype(str) + " " + alvo["pai"].astype(str)
            alvo = alvo[chave.str.contains(busca_d, case=False, na=False)]
        tabela_d = pd.DataFrame({
            "Foto": imagens.coluna_imagem(alvo),
            "Produto": alvo["item"],
            "Código": alvo["pai"],
            "Coleção": alvo["colecao"],
            "Linha": alvo["linha"],
            "Subgrupo": alvo["subgrupo"],
            "Cor": alvo["cor"],
            "Status": alvo["status"],
            "Preço tab.": alvo["preco"],
            "Dt. envio": alvo["dt_envio"],
            "Estoque": alvo["qtde"],
            "CD vendas": alvo["qtde_cd"],
            "Filiais": alvo["n_filiais"],
            "Grade": alvo["grade_pct"] * 100,
            "No site": alvo["no_site"] == 1,
        })
        with b2:
            visual.botao_excel("Exportar Excel",
                               {"Disponibilidade": tabela_d.drop(columns=["Foto"])},
                               f"disponibilidade_{meta.get('data', 'hoje')}.xlsx", "x_disp")
        st.dataframe(
            tabela_d, hide_index=True, width="stretch", height=460,
            column_config={
                "Foto": st.column_config.ImageColumn("", width="small"),
                "Preço tab.": st.column_config.NumberColumn(format="R$ %.2f", width="small"),
                "Grade": st.column_config.ProgressColumn(format="%.0f%%", min_value=0,
                                                         max_value=100, width="small"),
                "No site": st.column_config.CheckboxColumn(width="small"),
            })
        st.caption("Grade = % dos tamanhos cadastrados que têm estoque. "
                   "Foto: miniatura da pasta do Marketing; sem ela, a imagem do cadastro "
                   "ou do site.")

# =========================== ABA ALERTAS ====================================
with aba_alertas:
    checagens = metricas.alertas(dados)
    ligados = [c for c in checagens if c["alerta"]]
    visual.secao(
        f"Checagens do dia · {len(ligados)} de {len(checagens)} pedindo atenção",
        f"Rodadas sobre a carga de {meta.get('data', '—')}. Limiares em config.py.")
    for item in checagens:
        visual.cartao_alerta(item)

    fila = metricas.fila_de_publicacao(disp_todos)
    urgentes = metricas.com_volume_no_cd(fila)
    visual.secao(f"Fila de publicação · {config.plural(len(fila), 'SKU')}",
                 f"Fora do site com a foto de e-commerce já pronta — é a lista de maior "
                 f"retorno imediato. Ordenada pelo estoque no CD de vendas; "
                 f"{config.plural(len(urgentes), 'SKU')} com "
                 f"{config.ALERTAS['cd_min_foto_fora']} unidades ou mais lá.")
    if fila.empty:
        st.success("Nada nesta fila: todo SKU com foto pronta já está publicado.")
    else:
        tabela_f = pd.DataFrame({
            "Foto": imagens.coluna_imagem(fila),
            "Produto": fila["item"],
            "Código": fila["pai"],
            "Coleção": fila["colecao"],
            "Cor": fila["cor"],
            "Status": fila["status"],
            "Preço tab.": fila["preco"],
            "CD vendas": fila["qtde_cd"],
            "Estoque total": fila["qtde"],
            "Grade": fila["grade_pct"] * 100,
            "Arquivo da foto": fila["foto_arq"],
        })
        visual.botao_excel("Exportar fila", {"Fila de publicação": tabela_f.drop(columns=["Foto"])},
                           f"fila_publicacao_{meta.get('data', 'hoje')}.xlsx", "x_fila")
        st.dataframe(
            tabela_f, hide_index=True, width="stretch",
            height=min(420, 60 + 36 * len(tabela_f)),
            column_config={
                "Foto": st.column_config.ImageColumn("", width="small"),
                "Preço tab.": st.column_config.NumberColumn(format="R$ %.2f", width="small"),
                "Grade": st.column_config.ProgressColumn(format="%.0f%%", min_value=0,
                                                         max_value=100, width="small"),
                "Arquivo da foto": st.column_config.TextColumn(width="medium"),
            })

    sem_imagem = det_todos[det_todos["f6"] == 0]
    visual.secao(f"Publicados sem nenhuma imagem · {visual.num(len(sem_imagem))}",
                 "Produto no ar sem foto: pior cenário de conversão.")
    if sem_imagem.empty:
        st.success("Nenhum produto publicado sem imagem.")
    else:
        st.dataframe(
            pd.DataFrame({"Produto": sem_imagem["titulo"], "Categoria": sem_imagem["cat"],
                          "Coleção": sem_imagem["colecao"], "Status": sem_imagem["status"],
                          "Link": sem_imagem["url"]}),
            hide_index=True, width="stretch",
            column_config={"Link": st.column_config.LinkColumn("", display_text="abrir",
                                                               width="small")})

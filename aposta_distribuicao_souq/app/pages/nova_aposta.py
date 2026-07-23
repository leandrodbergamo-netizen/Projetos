"""Nova aposta — fluxo único em 4 etapas (redesign Souq).

Produto → Espelhos → Projeção → Distribuição, com stepper no topo. As etapas 3-4
só destravam depois de projetar; voltar não perde nada (formulário, seleção de
espelhos e projeção ficam no session_state). O motor de cálculo é o mesmo de
sempre (core/espelho, core/regra_distribuicao); aqui só muda a apresentação.
"""
from datetime import date

import pandas as pd
import streamlit as st

from app import estilo
from app.dados_app import (contexto_lojas, opcoes, opcoes_por_relevancia,
                           produtos_prep, totais_por_sku, vendas_fp)
from app.pages import distribuicao
from core.config_utils import load_config
from core.dados import (colecoes_projetaveis, curva_tamanhos, fim_periodo_saudavel,
                        participacao_lojas, semanas_ate)
from core.espelho import (candidatos_espelho, enriquecer_velocidade, grades_por_modelo,
                          janelas_full_price, pool_suavizacao, projetar_aposta,
                          velocidade_de_cada_loja, velocidade_por_loja_desaz)
from core.sazonalidade import curva_por
from core.taxonomia import faixa_preco, ordem_tamanhos, rotulo_grade

ETAPAS = ["① Produto", "② Espelhos", "③ Projeção", "④ Distribuição"]


def _foto(url):
    u = str(url) if url is not None else ""
    return u if u.lower().endswith((".jpg", ".jpeg", ".png", ".webp")) else None


def _grupo_predominante(pp, subgrupo, tecido, desde=2022.0):
    """Construção (grupo) mais comum do subgrupo+tecido no escopo.

    A faixa de preço oficial é por grupo+subgrupo, mas a aba não pergunta mais a
    construção ao usuário — o tecido já carrega essa informação.
    """
    esc = pp[(pp["desc_sub_grupo_wbg"] == subgrupo) & (pp["rank_colecao"] >= desde)]
    com_tecido = esc[esc["grupo_material"] == tecido]
    serie = (com_tecido if len(com_tecido) else esc)["desc_grupo_wgb"].dropna()
    return serie.mode().iat[0] if len(serie) else "TECIDO PLANO"


def _stepper(etapa: int, tem_form: bool, tem_proj: bool) -> None:
    livres = [True, tem_form, tem_proj, tem_proj]
    cols = st.columns(4)
    for i, (col, rotulo) in enumerate(zip(cols, ETAPAS)):
        n = i + 1
        if col.button(rotulo, key=f"etapa_btn_{n}", width="stretch",
                      type="primary" if etapa == n else "secondary",
                      disabled=not livres[i]):
            st.session_state["etapa"] = n
            st.rerun()
    st.markdown("")


def _contexto_form(form: dict) -> str:
    if not form:
        return ""
    ref = f"{form['sku_ref']} · " if form.get("sku_ref") else ""
    return (f"{ref}{form['subgrupo']}/{form['tecido']} · R${form['preco']:.0f} · "
            f"faixa {form.get('faixa') or '—'} · {form['colecao']}")


# --------------------------------------------------------------------------- #
# Etapa 1 — Produto
# --------------------------------------------------------------------------- #
def _etapa_produto(cfg, pp) -> None:
    st.caption("Descreva o produto novo. O sistema busca espelhos comparáveis e "
               "projeta a aposta até o fim do período saudável.")
    form = st.session_state.get("formulario") or {}

    c1, c2, c3 = st.columns(3)
    with c1:
        ops_sub = opcoes("desc_sub_grupo_wbg")
        subgrupo = st.selectbox("Subgrupo", ops_sub,
                                index=ops_sub.index(form["subgrupo"]) if form.get("subgrupo") in ops_sub else 0)
        sku_ref = st.text_input("SKU pai / estilo (opcional)", value=form.get("sku_ref", ""),
                                placeholder="04.26.__.___.___",
                                help="Referência livre do produto novo — identifica o cenário no Histórico.").strip()
    with c2:
        ops_tec = opcoes_por_relevancia("grupo_material")
        tecido = st.selectbox("Tecido (matéria-prima)", ops_tec,
                              index=ops_tec.index(form["tecido"]) if form.get("tecido") in ops_tec else 0)
        cores = st.multiselect("Cor", opcoes("cor_grupo"), default=form.get("cores") or [],
                               help="Vazio = todas as cores. O filtro afrouxa sozinho se faltar espelho.")
    with c3:
        preco = st.number_input("Preço sugerido (R$)", min_value=0.0,
                                value=float(form.get("preco", 498.0)), step=10.0)
        dt_padrao = pd.Timestamp(form["dt_entrada"]).date() if form.get("dt_entrada") else date.today()
        dt_entrada = st.date_input("Data de entrada em loja", value=dt_padrao, format="DD/MM/YYYY",
                                   help="Premissa dt_envio + 7 dias; posiciona a janela sazonal.")

    c4, c5, c6 = st.columns(3)
    with c4:
        opcoes_col = colecoes_projetaveis(date.today().year)
        if form.get("colecao") in opcoes_col:
            padrao = opcoes_col.index(form["colecao"])
        else:
            padrao = next((i for i, c in enumerate(opcoes_col)
                           if fim_periodo_saudavel(c, cfg.get("fim_periodo_verao", "02/01"),
                                                   cfg.get("fim_periodo_inverno", "14/06")) >= dt_entrada), 0)
        colecao = st.selectbox("Coleção apostada", opcoes_col, index=padrao,
                               help="Define o fim do período saudável e o horizonte da projeção.")
    with c5:
        aproveitamento = st.number_input(
            "Aproveitamento (%)", 10, 100,
            int(form.get("aproveitamento_pct", round(100 * float(cfg.get("aproveitamento", 0.70))))), 5,
            help="Fração da aposta que se espera vender a full price no período.")
    with c6:
        reserva = st.number_input(
            "Reserva CD (%)", 0, 50,
            int(form.get("reserva_pct", round(100 * float(cfg.get("reserva_cd_pct", 0.20))))), 5,
            help="Parcela da aposta que fica no CD para reposição.")

    todos_tam = ordem_tamanhos()
    grade_padrao = form.get("grade") or [t for t in todos_tam
                                         if t in {"38|PP", "40|P", "42|M", "44|G", "46|GG"}]
    grade_sel = st.multiselect(
        "Grade de tamanhos da aposta", todos_tam, default=grade_padrao,
        help="Filtro: só entram como espelho os modelos que venderam TODOS os tamanhos da "
             "grade (36≡XPP … 46≡GG). A grade também define as colunas da matriz.")

    desde = float(cfg.get("desde_colecao", 2022.0))
    grupo_faixa = _grupo_predominante(pp, subgrupo, tecido, desde=desde)
    fx = faixa_preco(grupo_faixa, subgrupo, preco)["faixa"]
    fim = fim_periodo_saudavel(colecao, cfg.get("fim_periodo_verao", "02/01"),
                               cfg.get("fim_periodo_inverno", "14/06"))
    if pd.Timestamp(dt_entrada) > pd.Timestamp(fim):
        st.warning("A data de entrada é depois do fim do período desta coleção. Confira a coleção.")

    b, resto = st.columns([1.6, 4])
    if b.button("Buscar espelhos →", type="primary", width="stretch"):
        st.session_state["formulario"] = {
            "subgrupo": subgrupo, "tecido": tecido, "cores": cores, "preco": float(preco),
            "sku_ref": sku_ref, "colecao": colecao, "dt_entrada": str(dt_entrada),
            "aproveitamento_pct": int(aproveitamento), "reserva_pct": int(reserva),
            "grade": grade_sel, "faixa": fx, "grupo_faixa": grupo_faixa,
        }
        st.session_state["etapa"] = 2
        st.rerun()
    resto.caption(f"{subgrupo} · {tecido} · faixa {fx or '—'} · "
                  f"grade {rotulo_grade(set(grade_sel)) if grade_sel else '—'} · "
                  f"fim saudável {fim:%d/%m/%Y}")


# --------------------------------------------------------------------------- #
# Etapa 2 — Espelhos (cards com foto)
# --------------------------------------------------------------------------- #
def _cartao_espelho(linha, grades, marcados) -> bool:
    sku = linha["cod_sku_pai"]
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns([0.4, 0.8, 5.4, 1.6], vertical_alignment="center")
        sel = c1.checkbox("Usar", key=f"esp_{sku}", value=sku in marcados,
                          label_visibility="collapsed")
        foto = _foto(linha.get("url"))
        nome = str(linha.get("desc_item") or sku)
        if foto:
            # st.image tem o botão nativo de ampliar (⛶) ao passar o mouse
            c2.image(foto, width=64)
        else:
            c2.markdown(f'<div class="swatch">{nome[:1]}</div>', unsafe_allow_html=True)
        envio = linha.get("dt_envio")
        envio = f"{pd.Timestamp(envio):%d/%m/%Y}" if pd.notna(envio) else "—"
        aprov = f"{linha['aprov_real']:.0f}%" if pd.notna(linha.get("aprov_real")) else "—"
        meta1 = (f"{sku} · {linha.get('desc_colecao')} · envio {envio} · "
                 f"{linha.get('grupo_material')} · grade {rotulo_grade(grades.get(sku))}")
        preco_txt = f"R$ {linha['preco']:.0f}" if pd.notna(linha.get("preco")) else "R$ —"
        meta2 = (f"{linha.get('cor_grupo')} · {preco_txt} · "
                 f"{int(linha['unidades'])} un hist · aprov. real {aprov} · "
                 f"{int(linha['n_lojas'])} lojas · "
                 f"{linha.get('desc_manga') or '—'} · {linha.get('desc_fit') or '—'}")
        c3.markdown(f"**{nome}**<br><span style='font-size:12.5px;color:#8A8378'>{meta1}</span>"
                    f"<br><span style='font-size:12.5px;color:#8A8378'>{meta2}</span>",
                    unsafe_allow_html=True)
        c4.markdown(f"<div style='text-align:right'><span style='font-size:19px;"
                    f"font-weight:700'>{linha['vel_loja_desaz']:.2f}</span>"
                    f"<span style='font-size:11px;color:#8A8378'> un/sem</span><br>"
                    f"<span style='font-size:11.5px;color:#8A8378'>vel/loja desaz.</span></div>",
                    unsafe_allow_html=True)
    return sel


def _etapa_espelhos(cfg, pp, fp) -> None:
    form = st.session_state["formulario"]
    desde = float(cfg.get("desde_colecao", 2022.0))
    ctx = contexto_lojas()
    fim = fim_periodo_saudavel(form["colecao"], cfg.get("fim_periodo_verao", "02/01"),
                               cfg.get("fim_periodo_inverno", "14/06"))
    horizonte = semanas_ate(pd.Timestamp(form["dt_entrada"]).date(), fim)
    estilo.banner([("faixa de preço", form.get("faixa") or "—"),
                   ("fim do período saudável", f"{fim:%d/%m/%Y}"),
                   ("horizonte", f"{horizonte} semanas"),
                   ("lojas-alvo", str(ctx["n_lojas_alvo"]))])

    cand, soft = candidatos_espelho(
        pp, subgrupo=form["subgrupo"], faixa=form.get("faixa"), tecido=form["tecido"],
        cor_grupo=form.get("cores") or None, grade=form.get("grade") or None,
        desde_colecao=desde)
    curva, nivel = curva_por(fp, subgrupo=form["subgrupo"], material=form["tecido"])
    if cand.empty:
        st.warning("Nenhum candidato a espelho com esses filtros. Volte e reduza a grade, "
                   "afrouxe a cor ou ajuste o preço.")
        if st.button("← Produto"):
            st.session_state["etapa"] = 1
            st.rerun()
        return

    total_bruto = len(cand)
    janelas = janelas_full_price(pp)
    hoje = pd.Timestamp(date.today())
    dias_ativo = int(cfg.get("dias_para_considerar_ativo", 60))
    cand = enriquecer_velocidade(cand, fp, curva, ctx["ecom_locs"], janelas=janelas,
                                 ativo_ate=hoje, dias_ativo=dias_ativo)
    if cand.empty:
        st.warning(f"Os {total_bruto} candidatos encontrados nunca venderam full price. "
                   "Volte e afrouxe os filtros.")
        if st.button("← Produto"):
            st.session_state["etapa"] = 1
            st.rerun()
        return

    st.subheader(f"Candidatos a espelho ({len(cand)}) — curva sazonal: {nivel}")
    ocultos = total_bruto - len(cand)
    notas = []
    if form.get("grade"):
        notas.append(f"só espelhos que venderam a grade {rotulo_grade(set(form['grade']))}")
    if form.get("cores"):
        notas.append("cor mantida" if "cor_grupo" in soft else "cor afrouxada (poucos candidatos)")
    if ocultos:
        notas.append(f"{ocultos} sem histórico de venda ocultado(s)")
    notas.append("manga/comprimento/fit são apenas consulta")
    st.caption(". ".join(n.capitalize() for n in notas) +
               ". Marque os espelhos que representam a venda esperada do produto novo.")

    tot = totais_por_sku()
    cand = cand.merge(tot, on="cod_sku_pai", how="left")
    cand["aprov_real"] = (100 * (cand["unidades"] / cand["unid_total"]).clip(upper=1.0))
    grades = grades_por_modelo(pp)
    skus = cand["cod_sku_pai"].tolist()

    def _marcar_todos():
        for s in skus:
            st.session_state[f"esp_{s}"] = st.session_state["sel_todos_esp"]

    st.checkbox("Selecionar todos", key="sel_todos_esp", on_change=_marcar_todos)

    marcados_prev = set(st.session_state.get("espelhos_marcados") or [])
    marcados = {sku for _, linha in cand.iterrows()
                if _cartao_espelho(linha, grades, marcados_prev)
                for sku in [linha["cod_sku_pai"]]}
    st.session_state["espelhos_marcados"] = sorted(marcados)

    b1, b2, _ = st.columns([1.2, 2.2, 3])
    if b1.button("← Produto", width="stretch"):
        st.session_state["etapa"] = 1
        st.rerun()
    plural = "" if len(marcados) == 1 else "s"
    if b2.button(f"Projetar aposta ({len(marcados)} espelho{plural}) →", type="primary",
                 width="stretch", disabled=not marcados):
        _projetar(cfg, pp, fp, cand, curva, ctx, sorted(marcados), horizonte, janelas,
                  hoje, dias_ativo, desde, fim)
        st.session_state["etapa"] = 3
        st.rerun()


# --------------------------------------------------------------------------- #
# Projeção (cálculo — motor de sempre)
# --------------------------------------------------------------------------- #
def _projetar(cfg, pp, fp, cand, curva, ctx, escolhidos, horizonte, janelas,
              hoje, dias_ativo, desde, fim) -> None:
    form = st.session_state["formulario"]
    vels = [velocidade_por_loja_desaz(fp, s, curva, ctx["ecom_locs"], janela=janelas.get(s),
                                      ativo_ate=hoje, dias_ativo=dias_ativo)
            for s in escolhidos]
    vels = [v for v in vels if v]
    if not vels:
        st.error("Os espelhos escolhidos não têm histórico de venda no escopo Souq.")
        st.stop()
    ap = projetar_aposta(vels, curva, pd.Timestamp(form["dt_entrada"]), ctx["n_lojas_alvo"],
                         horizonte_semanas=horizonte,
                         aproveitamento=form["aproveitamento_pct"] / 100.0,
                         reserva_cd_pct=form["reserva_pct"] / 100.0)

    skus = [v.cod_sku_pai for v in vels]
    fisico = ~fp["sk_localidade"].isin(ctx["ecom_locs"])
    fp_esp_fisico = fp[fp["cod_sku_pai"].isin(skus) & fisico]
    # participação por loja suavizada com o segmento subgrupo+tecido+fit
    fits = sorted(set(cand.loc[cand["cod_sku_pai"].isin(skus), "desc_fit"].dropna())
                  if "desc_fit" in cand.columns else set())
    pool = pool_suavizacao(pp, subgrupo=form["subgrupo"], tecido=form["tecido"],
                           fits=fits or None, desde_colecao=desde)
    fp_pool_fisico = fp[fp["cod_sku_pai"].isin(pool) & fisico]
    part_espelhos = participacao_lojas(fp_esp_fisico)
    participacoes = participacao_lojas(fp_pool_fisico) or part_espelhos
    n_pool = int(fp_pool_fisico["cod_sku_pai"].nunique())

    curva_tam = curva_tamanhos(fp[fp["cod_sku_pai"].isin(skus)], pp, col_tamanho="tamanho_grupo")
    grade_sel = form.get("grade") or []
    if grade_sel:
        curva_tam = {t: p for t, p in curva_tam.items() if t in set(grade_sel)}
        piso = min(curva_tam.values()) / 2 if curva_tam else 1.0
        for t in grade_sel:
            curva_tam.setdefault(t, piso)
        curva_tam = {t: curva_tam[t] for t in grade_sel if t in curva_tam}

    nomes = cand.drop_duplicates("cod_sku_pai").set_index("cod_sku_pai")["desc_item"].to_dict()
    contribuicoes = [(str(nomes.get(v.cod_sku_pai) or v.cod_sku_pai), v.vel_por_loja_desaz)
                     for v in sorted(vels, key=lambda x: -x.vel_por_loja_desaz)]

    ref = f"{form['sku_ref']} · " if form.get("sku_ref") else ""
    projecao = {
        "resumo": (f"{ref}{form['subgrupo']}/{form['tecido']} · R${form['preco']:.0f} · "
                   f"faixa {form.get('faixa')} · {form['colecao']}"),
        "aposta_total": ap.aposta_sugerida,
        "reserva_cd_pct": form["reserva_pct"] / 100.0,
        "participacoes_hist": participacoes,
        "curva_tamanhos": curva_tam,
        "velocidades_loja": velocidade_de_cada_loja(fp, skus, curva, ctx["ecom_locs"]),
        "espelhos": skus,
        "suavizacao": {"n_modelos": n_pool, "fits": fits},
        "lojas_com_espelho_proprio": sorted(part_espelhos),
        "contribuicoes": contribuicoes,
        "inputs": {
            "sku_ref": form.get("sku_ref"), "subgrupo": form["subgrupo"],
            "tecido": form["tecido"], "cores": form.get("cores"), "grade": grade_sel,
            "preco": form["preco"], "dt_entrada": form["dt_entrada"],
            "colecao": form["colecao"], "aproveitamento": form["aproveitamento_pct"] / 100.0,
            "horizonte_semanas": horizonte, "faixa": form.get("faixa"),
            "grupo_faixa": form.get("grupo_faixa"), "fim_periodo": f"{fim:%d/%m/%Y}",
        },
        "resultado": {
            "venda_projetada": ap.venda_projetada, "venda_ecom": ap.venda_ecom,
            "aposta_sugerida": ap.aposta_sugerida, "reserva_cd": ap.reserva_cd,
            "semanas_equivalentes": ap.semanas_equivalentes,
            "vel_por_loja_desaz": ap.vel_por_loja_desaz,
        },
        "avisos_projecao": list(ap.avisos),
    }
    st.session_state["projecao"] = projecao
    st.session_state.pop("distribuicao", None)

    try:
        from core import historico

        historico.salvar(projecao["resumo"], projecao)
        st.session_state["flash_salvo"] = True
    except Exception:
        st.session_state["flash_salvo"] = False


# --------------------------------------------------------------------------- #
# Etapa 3 — Projeção (exibição)
# --------------------------------------------------------------------------- #
def _etapa_projecao() -> None:
    proj = st.session_state["projecao"]
    res = proj.get("resultado") or {}
    ins = proj.get("inputs") or {}
    st.caption(f"Projeção: {proj['resumo']} · {len(proj.get('espelhos') or [])} espelho(s)")

    k1, k2, k3, k4 = st.columns(4)
    estilo.kpi(k1, "Aposta total", f"{res.get('aposta_sugerida', proj['aposta_total']):.0f}",
               "unidades", escuro=True)
    estilo.kpi(k2, "Venda projetada", f"{res.get('venda_projetada', 0):.0f}",
               f"{res.get('semanas_equivalentes', 0):.1f} semanas-equivalentes")
    estilo.kpi(k3, "Reserva CD", f"{res.get('reserva_cd', 0):.0f}",
               f"{100 * proj.get('reserva_cd_pct', 0):.0f}% da aposta")
    estilo.kpi(k4, "Fim saudável", ins.get("fim_periodo") or "—",
               f"coleção {ins.get('colecao') or '—'}")
    st.markdown("")
    for aviso in proj.get("avisos_projecao") or []:
        st.info(aviso)
    suav = proj.get("suavizacao") or {}
    if suav.get("n_modelos"):
        fits = suav.get("fits") or []
        st.caption(f"Participação por loja suavizada com {suav['n_modelos']} modelos do "
                   "segmento" + (f" (fit: {', '.join(fits)})" if fits else "") + ".")
    if st.session_state.get("flash_salvo"):
        st.caption(":green[Cenário salvo no Histórico ✓]")

    if proj.get("curva_tamanhos"):
        st.subheader("Curva de tamanhos")
        estilo.barras_tamanho(proj["curva_tamanhos"],
                              float(res.get("aposta_sugerida", proj["aposta_total"])))
    if proj.get("contribuicoes"):
        st.subheader("Contribuição dos espelhos")
        estilo.barras_contribuicao(proj["contribuicoes"])

    st.markdown("")
    b1, b2, _ = st.columns([1.2, 1.6, 3.2])
    if b1.button("← Espelhos", width="stretch"):
        st.session_state["etapa"] = 2
        st.rerun()
    if b2.button("Distribuir →", type="primary", width="stretch"):
        st.session_state["etapa"] = 4
        st.rerun()


# --------------------------------------------------------------------------- #
def render() -> None:
    cfg = load_config()
    pp = produtos_prep()
    fp = vendas_fp()

    etapa = int(st.session_state.get("etapa", 1))
    form = st.session_state.get("formulario") or {}
    proj = st.session_state.get("projecao")
    if etapa >= 3 and not proj:
        etapa = 1
    if etapa == 2 and not form:
        etapa = 1

    t1, t2 = st.columns([2.2, 4], vertical_alignment="bottom")
    t1.title("Nova aposta")
    contexto = _contexto_form(form) if etapa > 1 else ""
    if contexto:
        t2.caption(f"Etapa {etapa} de 4 · {contexto}")

    _stepper(etapa, tem_form=bool(form), tem_proj=bool(proj))

    if etapa == 1:
        _etapa_produto(cfg, pp)
    elif etapa == 2:
        _etapa_espelhos(cfg, pp, fp)
    elif etapa == 3:
        _etapa_projecao()
    else:
        st.caption(f"Projeção: {proj['resumo']}")
        distribuicao.secao(proj)
        if st.button("← Projeção"):
            st.session_state["etapa"] = 3
            st.rerun()

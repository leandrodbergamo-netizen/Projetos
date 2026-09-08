"""Nova aposta — fluxo único em 3 etapas (redesign Souq).

Produto → Espelhos → Projeção, com stepper no topo. A etapa 3 só destrava
depois de projetar; voltar não perde nada (formulário, seleção de espelhos e
projeção ficam no session_state). Na Projeção, Perfil/Clima dimensionam a
aposta pelo parque escolhido e "Salvar aposta" grava UM registro no Histórico
e encerra o ciclo — a DISTRIBUIÇÃO parte da aba Histórico.
"""
from datetime import date

import pandas as pd
import streamlit as st

from app import estilo
from app.dados_app import (contexto_lojas, opcoes, opcoes_por_relevancia,
                           produtos_prep, totais_por_sku, vendas_fp)
from core.config_utils import load_config
from core.dados import (colecoes_projetaveis, fim_periodo_saudavel, lojas_alvo_souq,
                        opcoes_perfil_clima, participacao_lojas, semanas_ate)
from core.espelho import (candidatos_espelho, curva_tamanhos_grade,
                          enriquecer_velocidade, grades_por_modelo,
                          janelas_full_price, pool_suavizacao, projetar_aposta,
                          velocidade_por_loja_desaz)
from core.sazonalidade import curva_por
from core.taxonomia import faixas_do_subgrupo, ordem_tamanhos, rotulo_grade

ETAPAS = ["① Produto", "② Espelhos", "③ Projeção"]
TODOS = "TODOS"


def _foto(url):
    u = str(url) if url is not None else ""
    return u if u.lower().endswith((".jpg", ".jpeg", ".png", ".webp")) else None


@st.dialog("Foto do espelho", width="large")
def _foto_ampliada(url: str, nome: str) -> None:
    """Modal com a foto grande; fecha no ✕ (ou clicando fora)."""
    st.markdown(f"**{nome}**")
    st.image(url, width="stretch")


def _stepper(etapa: int, tem_form: bool, tem_proj: bool) -> None:
    livres = [True, tem_form, tem_proj]
    cols = st.columns(len(ETAPAS))
    for i, (col, rotulo) in enumerate(zip(cols, ETAPAS)):
        n = i + 1
        if col.button(rotulo, key=f"etapa_btn_{n}", width="stretch",
                      type="primary" if etapa == n else "secondary",
                      disabled=not livres[i]):
            st.session_state["etapa"] = n
            st.rerun()
    st.markdown("")


def _rotulo_faixas(faixas) -> str:
    return "/".join(faixas) if faixas else "—"


def _contexto_form(form: dict) -> str:
    if not form:
        return ""
    ref = f"{form['sku_ref']} · " if form.get("sku_ref") else ""
    return (f"{ref}{form['subgrupo']}/{form['tecido']} · "
            f"{_rotulo_faixas(form.get('faixas'))} · {form['colecao']}")


# --------------------------------------------------------------------------- #
# Etapa 1 — Produto
# --------------------------------------------------------------------------- #
def _etapa_produto(cfg, pp) -> None:
    if st.session_state.get("flash_ciclo"):
        st.success(st.session_state.pop("flash_ciclo"))
    st.caption("Descreva o produto novo. O sistema busca espelhos comparáveis e "
               "projeta a aposta até o fim do período saudável.")
    form = st.session_state.get("formulario") or {}

    # aposta nova começa SEM preenchimento: subgrupo, tecido e faixas vazios
    # (voltando de uma etapa posterior, os valores do formulário são mantidos)
    c1, c2, c3 = st.columns(3)
    with c1:
        ops_sub = opcoes("desc_sub_grupo_wbg")
        subgrupo = st.selectbox("Subgrupo", ops_sub,
                                index=ops_sub.index(form["subgrupo"]) if form.get("subgrupo") in ops_sub else None,
                                placeholder="Escolha o subgrupo…")
        sku_ref = st.text_input("SKU pai / estilo (opcional)", value=form.get("sku_ref", ""),
                                placeholder="04.26.__.___.___",
                                help="Referência livre do produto novo — identifica o cenário no Histórico.").strip()
    with c2:
        ops_tec = opcoes_por_relevancia("grupo_material")
        tecido = st.selectbox("Tecido (matéria-prima)", ops_tec,
                              index=ops_tec.index(form["tecido"]) if form.get("tecido") in ops_tec else None,
                              placeholder="Escolha o tecido…")
        cores = st.multiselect("Cor", opcoes_por_relevancia("cor_grupo"),
                               default=form.get("cores") or [],
                               help="Ordenadas por nº de modelos. Vazio = todas as cores; "
                                    "o filtro afrouxa sozinho se faltar espelho. Digite para buscar.")
    with c3:
        reguas = faixas_do_subgrupo(subgrupo) if subgrupo else None
        ops_fx = (sorted(reguas["faixa"].dropna().unique().tolist())
                  if reguas is not None and len(reguas) else ["P1", "P2", "P3", "P4"])
        faixas_sel = st.multiselect(
            "Faixas de preço", ops_fx,
            default=[f for f in (form.get("faixas") or []) if f in ops_fx],
            help="Uma ou mais faixas. Cada produto é classificado na régua da "
                 "PRÓPRIA construção (P4 de malha ≠ P4 de tecido plano em R$) — "
                 "os intervalos aparecem abaixo ao escolher o subgrupo.")
        dt_padrao = pd.Timestamp(form["dt_entrada"]).date() if form.get("dt_entrada") else date.today()
        dt_entrada = st.date_input("Data de entrada em loja", value=dt_padrao, format="DD/MM/YYYY",
                                   help="Premissa dt_envio + 7 dias; posiciona a janela sazonal.")

    if reguas is not None and len(reguas):
        linhas_regua = []
        for grupo_c, gdf in reguas.groupby("grupo"):
            partes = " · ".join(f"{r.faixa} {r.de:.0f}–{r.ate:.0f}" for r in gdf.itertuples())
            linhas_regua.append(f"**{grupo_c}**: {partes}")
        st.caption("Réguas do subgrupo (R$) — " + " &nbsp;|&nbsp; ".join(linhas_regua) +
                   ". Mudou o arquivo de faixas? Reinicie o app.")

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
        help="A grade NÃO filtra os espelhos: define as colunas da matriz de "
             "distribuição e a curva de tamanhos (36≡XPP … 46≡GG). Tamanhos que "
             "os espelhos não venderam são projetados pelo segmento.")

    pronto = subgrupo is not None and tecido is not None and bool(faixas_sel)
    fim = fim_periodo_saudavel(colecao, cfg.get("fim_periodo_verao", "02/01"),
                               cfg.get("fim_periodo_inverno", "14/06"))
    if pd.Timestamp(dt_entrada) > pd.Timestamp(fim):
        st.warning("A data de entrada é depois do fim do período desta coleção. Confira a coleção.")

    b, resto = st.columns([1.6, 4])
    if b.button("Buscar espelhos →", type="primary", width="stretch", disabled=not pronto):
        st.session_state["formulario"] = {
            "subgrupo": subgrupo, "tecido": tecido, "cores": cores,
            "faixas": list(faixas_sel),
            "sku_ref": sku_ref, "colecao": colecao, "dt_entrada": str(dt_entrada),
            "aproveitamento_pct": int(aproveitamento), "reserva_pct": int(reserva),
            "grade": grade_sel,
        }
        st.session_state["etapa"] = 2
        st.rerun()
    if pronto:
        resto.caption(f"{subgrupo} · {tecido} · {_rotulo_faixas(faixas_sel)} · "
                      f"grade {rotulo_grade(set(grade_sel)) if grade_sel else '—'} · "
                      f"fim saudável {fim:%d/%m/%Y}")
    else:
        resto.caption("Preencha **subgrupo, tecido e faixas de preço** para buscar os espelhos.")


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
            c2.markdown(f'<img class="foto-espelho" src="{foto}">', unsafe_allow_html=True)
            if c2.button("🔍", key=f"zoom_{sku}", help="Ampliar a foto", type="tertiary"):
                _foto_ampliada(foto, nome)
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
    estilo.banner([("faixas de preço", _rotulo_faixas(form.get("faixas"))),
                   ("fim do período saudável", f"{fim:%d/%m/%Y}"),
                   ("horizonte", f"{horizonte} semanas"),
                   ("lojas-alvo", str(ctx["n_lojas_alvo"]))])

    hoje = pd.Timestamp(date.today())
    dias_ativo = int(cfg.get("dias_para_considerar_ativo", 60))
    # candidatos+velocidades memoizados por formulário: cada clique de checkbox
    # rerenderiza a página e, sem isto, recalculava o funil inteiro
    chave_cache = repr((form, desde, dias_ativo, str(hoje.date())))
    cache = st.session_state.get("_espelhos_cache") or {}
    if cache.get("chave") != chave_cache:
        with st.spinner("Buscando espelhos e calculando velocidades…"):
            cand, soft = candidatos_espelho(
                pp, subgrupo=form["subgrupo"], faixas=form.get("faixas"),
                tecido=form["tecido"], cor_grupo=form.get("cores") or None,
                desde_colecao=desde)
            curva, nivel = curva_por(fp, subgrupo=form["subgrupo"], material=form["tecido"],
                                     min_amostra=int(cfg.get("min_amostra_curva", 800)))
            total_bruto = len(cand)
            janelas = janelas_full_price(pp)
            if not cand.empty:
                cand = enriquecer_velocidade(cand, fp, curva, ctx["ecom_locs"],
                                             janelas=janelas, ativo_ate=hoje,
                                             dias_ativo=dias_ativo)
        cache = {"chave": chave_cache, "cand": cand, "soft": soft, "curva": curva,
                 "nivel": nivel, "total_bruto": total_bruto, "janelas": janelas}
        st.session_state["_espelhos_cache"] = cache
    cand, soft, curva = cache["cand"], cache["soft"], cache["curva"]
    nivel, total_bruto, janelas = cache["nivel"], cache["total_bruto"], cache["janelas"]

    if total_bruto == 0:
        st.warning("Nenhum candidato a espelho com esses filtros. Volte e adicione "
                   "faixas de preço ou afrouxe a cor.")
        if st.button("← Produto"):
            st.session_state["etapa"] = 1
            st.rerun()
        return
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
        with st.spinner("Projetando a aposta…"):
            _calcular_base(cfg, pp, fp, cand, curva, ctx, sorted(marcados), horizonte,
                           janelas, hoje, dias_ativo, desde, fim)
        st.session_state["etapa"] = 3
        st.rerun()


# --------------------------------------------------------------------------- #
# Projeção (cálculo — motor de sempre)
# --------------------------------------------------------------------------- #
def _calcular_base(cfg, pp, fp, cand, curva, ctx, escolhidos, horizonte, janelas,
                   hoje, dias_ativo, desde, fim) -> None:
    """Parte PESADA da projeção (roda na transição 2→3): velocidades dos
    espelhos, participações, curva de tamanhos e contribuições. Fica em
    `projecao_base` (objetos Python, nunca vai ao payload); o dimensionamento
    pelo parque é leve e roda na etapa 3 a cada mudança de Perfil/Clima."""
    form = st.session_state["formulario"]
    vels = [velocidade_por_loja_desaz(fp, s, curva, ctx["ecom_locs"], janela=janelas.get(s),
                                      ativo_ate=hoje, dias_ativo=dias_ativo)
            for s in escolhidos]
    vels = [v for v in vels if v]
    if not vels:
        st.error("Os espelhos escolhidos não têm histórico de venda no escopo Souq.")
        st.stop()

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

    grade_sel = form.get("grade") or []
    curva_tam, curva_origem, avisos_curva = curva_tamanhos_grade(
        fp, pp, skus, grade_sel, subgrupo=form["subgrupo"], tecido=form["tecido"],
        fits=fits or None, desde_colecao=desde)

    nomes = cand.drop_duplicates("cod_sku_pai").set_index("cod_sku_pai")["desc_item"].to_dict()
    contribuicoes = [(str(nomes.get(v.cod_sku_pai) or v.cod_sku_pai), v.vel_por_loja_desaz)
                     for v in sorted(vels, key=lambda x: -x.vel_por_loja_desaz)]

    st.session_state["projecao_base"] = {
        "vels": vels, "curva": curva, "horizonte": horizonte, "fim": fim,
        "skus": skus, "fits": fits, "n_pool": n_pool,
        "participacoes": participacoes, "part_espelhos": part_espelhos,
        "curva_tam": curva_tam, "curva_origem": curva_origem,
        "avisos_curva": avisos_curva, "contribuicoes": contribuicoes,
    }
    st.session_state.pop("distribuicao", None)
    _dimensionar(_parque_sel("parque_perfis"), _parque_sel("parque_climas"))


def _parque_sel(chave: str):
    """Seleção de Perfil/Clima do widget → None (todas) ou lista."""
    sel = st.session_state.get(chave) or [TODOS]
    return None if (TODOS in sel or not sel) else list(sel)


def _dimensionar(perfis=None, climas=None):
    """Parte LEVE da projeção: dimensiona a aposta pelo parque Perfil/Clima e
    monta o payload v2. A venda física escala com o nº de lojas do parque; o
    Ecom entra integral (não é loja física). Retorna None se o parque é vazio."""
    base = st.session_state["projecao_base"]
    form = st.session_state["formulario"]
    n = len(lojas_alvo_souq(perfis=perfis, climas=climas))
    if n == 0:
        return None
    ap = projetar_aposta(base["vels"], base["curva"], pd.Timestamp(form["dt_entrada"]), n,
                         horizonte_semanas=base["horizonte"],
                         aproveitamento=form["aproveitamento_pct"] / 100.0,
                         reserva_cd_pct=form["reserva_pct"] / 100.0)
    fim = base["fim"]
    ref = f"{form['sku_ref']} · " if form.get("sku_ref") else ""
    projecao = {
        "versao": 2,
        "resumo": (f"{ref}{form['subgrupo']}/{form['tecido']} · "
                   f"{_rotulo_faixas(form.get('faixas'))} · {form['colecao']}"),
        "aposta_total": ap.aposta_sugerida,
        "aposta_final": ap.aposta_sugerida,
        "parque": {"perfis": perfis, "climas": climas, "n_lojas_alvo": n},
        "reserva_cd_pct": form["reserva_pct"] / 100.0,
        "participacoes_hist": base["participacoes"],
        "participacoes_espelhos": base["part_espelhos"],
        "curva_tamanhos": base["curva_tam"],
        "curva_origem": base["curva_origem"],
        # o teto de cobertura deriva desta média × participação da loja — medir a
        # velocidade em janelas individuais por loja invertia o ranking (loja
        # grande de janela longa parecia lenta e era travada pelo teto)
        "vel_media_loja": ap.vel_por_loja_desaz,
        "espelhos": base["skus"],
        "suavizacao": {"n_modelos": base["n_pool"], "fits": base["fits"]},
        "lojas_com_espelho_proprio": sorted(base["part_espelhos"]),
        "contribuicoes": base["contribuicoes"],
        "inputs": {
            "sku_ref": form.get("sku_ref"), "subgrupo": form["subgrupo"],
            "tecido": form["tecido"], "cores": form.get("cores"),
            "grade": form.get("grade") or [],
            "faixas": form.get("faixas"), "dt_entrada": form["dt_entrada"],
            "colecao": form["colecao"], "aproveitamento": form["aproveitamento_pct"] / 100.0,
            "horizonte_semanas": base["horizonte"], "fim_periodo": f"{fim:%d/%m/%Y}",
        },
        "resultado": {
            "venda_projetada": ap.venda_projetada, "venda_ecom": ap.venda_ecom,
            "aposta_sugerida": ap.aposta_sugerida, "reserva_cd": ap.reserva_cd,
            "semanas_equivalentes": ap.semanas_equivalentes,
            "vel_por_loja_desaz": ap.vel_por_loja_desaz,
        },
        "avisos_projecao": list(ap.avisos) + base["avisos_curva"],
    }
    st.session_state["projecao"] = projecao
    return projecao


# --------------------------------------------------------------------------- #
# Etapa 3 — Projeção (parque + aposta final + salvar)
# --------------------------------------------------------------------------- #
def _etapa_projecao() -> None:
    base = st.session_state.get("projecao_base")
    form = st.session_state.get("formulario") or {}
    ao_vivo = bool(base and form)

    if ao_vivo:
        # REDUTORES DE APOSTA: a aposta é dimensionada só pelas lojas dos
        # perfis/climas escolhidos; a distribuição herda o mesmo parque.
        disp = opcoes_perfil_clima()
        c1, c2 = st.columns(2)
        c1.multiselect("Perfil Econômico", [TODOS] + disp["perfis"],
                       default=st.session_state.get("parque_perfis") or [TODOS],
                       key="parque_perfis",
                       help="Redutor de aposta: só as lojas destes perfis dimensionam "
                            "a compra — e são as únicas que recebem na distribuição.")
        c2.multiselect("Clima", [TODOS] + disp["climas"],
                       default=st.session_state.get("parque_climas") or [TODOS],
                       key="parque_climas",
                       help="Redutor de aposta: idem, pelo clima da loja.")
        proj = _dimensionar(_parque_sel("parque_perfis"), _parque_sel("parque_climas"))
        if proj is None:
            st.warning("Nenhuma loja ativa com esse Perfil/Clima — afrouxe a seleção.")
            return
    else:
        proj = st.session_state["projecao"]
        st.caption("Cenário sem a base de cálculo nesta sessão (recarregado). Os valores "
                   "são os projetados; para mudar o parque, volte à etapa ② e projete "
                   "de novo.")

    res = proj.get("resultado") or {}
    ins = proj.get("inputs") or {}
    parque = proj.get("parque") or {}
    st.caption(f"Projeção: {proj['resumo']} · {len(proj.get('espelhos') or [])} espelho(s)")

    k1, k2, k3, k4, k5 = st.columns(5)
    estilo.kpi(k1, "Aposta total", f"{res.get('aposta_sugerida', proj['aposta_total']):.0f}",
               "unidades", escuro=True)
    estilo.kpi(k2, "Venda projetada", f"{res.get('venda_projetada', 0):.0f}",
               f"{res.get('semanas_equivalentes', 0):.1f} semanas-equivalentes")
    estilo.kpi(k3, "Reserva CD", f"{res.get('reserva_cd', 0):.0f}",
               f"{100 * proj.get('reserva_cd_pct', 0):.0f}% da aposta")
    estilo.kpi(k4, "Lojas-alvo", f"{parque.get('n_lojas_alvo') or '—'}",
               "parque desta aposta")
    estilo.kpi(k5, "Fim saudável", ins.get("fim_periodo") or "—",
               f"coleção {ins.get('colecao') or '—'}")
    st.markdown("")
    for aviso in proj.get("avisos_projecao") or []:
        st.info(aviso)
    suav = proj.get("suavizacao") or {}
    if suav.get("n_modelos"):
        fits = suav.get("fits") or []
        st.caption(f"Participação por loja suavizada com {suav['n_modelos']} modelos do "
                   "segmento" + (f" (fit: {', '.join(fits)})" if fits else "") + ".")

    if proj.get("curva_tamanhos"):
        st.subheader("Curva de tamanhos")
        estilo.barras_tamanho(proj["curva_tamanhos"],
                              float(res.get("aposta_sugerida", proj["aposta_total"])))
        projetados = [t for t, o in (proj.get("curva_origem") or {}).items()
                      if o != "espelhos"]
        if projetados:
            st.caption(f"Tamanhos projetados pelo segmento (sem venda nos espelhos): "
                       f"{', '.join(projetados)}.")
    if proj.get("contribuicoes"):
        st.subheader("Contribuição dos espelhos")
        estilo.barras_contribuicao(proj["contribuicoes"])

    st.markdown("")
    if ao_vivo:
        sug = int(round(float(proj["aposta_total"])))
        sug_ant = st.session_state.get("_sug_anterior")
        if "aposta_final_edit" not in st.session_state:
            st.session_state["aposta_final_edit"] = sug
        elif (sug_ant is not None and sug != sug_ant
              and st.session_state["aposta_final_edit"] == sug_ant):
            # o parque mudou e o comercial não tinha editado: acompanha a sugerida
            st.session_state["aposta_final_edit"] = sug
        st.session_state["_sug_anterior"] = sug
        af, _ = st.columns([1.6, 4])
        aposta_final = af.number_input(
            "Aposta final (un)", min_value=0, step=5, key="aposta_final_edit",
            help="O modelo sugere, o comercial decide — é este valor que vai ao "
                 "Histórico e à distribuição.")
        if int(aposta_final) != sug:
            af.caption(f"Modelo sugeriu **{sug} un**.")
        proj["aposta_final"] = float(aposta_final)
        st.caption("Ainda não salvo — **Salvar aposta no Histórico** encerra o ciclo; "
                   "a distribuição parte da aba Histórico.")

    b1, b2, _ = st.columns([1.4, 2.2, 2.4])
    if b1.button("← Espelhos", width="stretch"):
        st.session_state["etapa"] = 2
        st.rerun()
    if ao_vivo and b2.button("Salvar aposta no Histórico", type="primary", width="stretch"):
        try:
            from core import historico

            with st.spinner("Salvando no Histórico…"):
                historico.salvar(proj["resumo"], proj)
            salvou = True
        except Exception:
            salvou = False
        if salvou:
            for k in ("projecao", "projecao_base", "distribuicao", "sel_todos_esp",
                      "registro_id", "parque_perfis", "parque_climas",
                      "aposta_final_edit", "_sug_anterior", "_espelhos_cache"):
                st.session_state.pop(k, None)
            for k in [k for k in st.session_state if str(k).startswith("esp_")]:
                st.session_state.pop(k, None)
            st.session_state["formulario"] = {}
            st.session_state["espelhos_marcados"] = []
            st.session_state["etapa"] = 1
            st.session_state["flash_ciclo"] = ("Aposta salva no Histórico ✓ — "
                                               "distribua pela aba Histórico.")
            st.rerun()
        else:
            st.error("Não foi possível salvar no Histórico. Tente de novo.")


# --------------------------------------------------------------------------- #
def render() -> None:
    cfg = load_config()
    with st.spinner("Carregando bases de produtos e vendas…"):
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
    contexto = ""
    if etapa > 1:
        # com o formulário já limpo (pós-projeção), o contexto vem da projeção
        contexto = _contexto_form(form) or (proj["resumo"] if proj else "")
    if contexto:
        t2.caption(f"Etapa {etapa} de {len(ETAPAS)} · {contexto}")

    _stepper(etapa, tem_form=bool(form), tem_proj=bool(proj))

    if etapa == 1:
        _etapa_produto(cfg, pp)
    elif etapa == 2:
        _etapa_espelhos(cfg, pp, fp)
    else:
        _etapa_projecao()

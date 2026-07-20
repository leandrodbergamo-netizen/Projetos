"""Nova Aposta — simulador de reunião.

Fluxo: características do produto novo -> tabela de candidatos a espelho (com
foto) -> seleção -> projeção da aposta (velocidade desazonalizada + sazonalidade
+ Ecom) -> envia participações/curva/velocidades para a aba Distribuição.

Os parâmetros gerais (aproveitamento, fim de período, tetos) ficam em
**Configurações**; aqui só entra a premissa de reserva CD, que é da aposta.
"""
from datetime import date

import pandas as pd
import streamlit as st

from app.dados_app import (contexto_lojas, opcoes, opcoes_por_relevancia,
                           produtos_prep, totais_por_sku, vendas_fp)
from core.config_utils import load_config
from core.dados import (colecoes_projetaveis, curva_tamanhos, fim_periodo_saudavel,
                        participacao_lojas, semanas_ate)
from core.espelho import (candidatos_espelho, enriquecer_velocidade, grades_por_modelo,
                          janelas_full_price, pool_suavizacao, projetar_aposta,
                          velocidade_de_cada_loja, velocidade_por_loja_desaz)
from core.regra_distribuicao import participacao_com_loja_nova
from core.sazonalidade import curva_por
from core.taxonomia import faixa_preco, ordem_tamanhos, rotulo_grade


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


def render() -> None:
    st.title("Nova Aposta")
    st.caption("Selecione as características do produto novo, escolha os espelhos e projete a aposta.")

    cfg = load_config()
    pp = produtos_prep()
    fp = vendas_fp()

    # ------------------------------------------------------------------ inputs
    c1, c2, c3 = st.columns(3)
    with c1:
        subgrupo = st.selectbox("Subgrupo", opcoes("desc_sub_grupo_wbg"))
        sku_ref = st.text_input(
            "SKU pai / estilo (opcional)",
            help="Referência livre do produto novo — identifica o cenário no Histórico.").strip()
    with c2:
        tecido = st.selectbox("Tecido (matéria-prima)", opcoes_por_relevancia("grupo_material"))
        cores = st.multiselect("Cor", opcoes("cor_grupo"),
                               help="Vazio = todas as cores. Selecione uma ou mais para restringir.")
    with c3:
        preco = st.number_input("Preço sugerido (R$)", min_value=0.0, value=498.0, step=10.0)
        dt_entrada = st.date_input("Data de entrada em loja", value=date.today(),
                                   format="DD/MM/YYYY",
                                   help="Premissa dt_envio + 7 dias; posiciona a janela sazonal.")

    c4, c5, c6 = st.columns(3)
    with c4:
        opcoes_col = colecoes_projetaveis(date.today().year)
        # default = primeira coleção ainda em aberto; as já encerradas continuam
        # na lista (dá para reprojetar o passado), mas não são o padrão.
        padrao = next((i for i, c in enumerate(opcoes_col)
                       if fim_periodo_saudavel(c, cfg.get("fim_periodo_verao", "02/01"),
                                               cfg.get("fim_periodo_inverno", "14/06")) >= dt_entrada), 0)
        colecao = st.selectbox("Coleção que está sendo apostada", opcoes_col, index=padrao,
                               help="Define o fim do período saudável e, com ele, o horizonte da projeção.")
    with c5:
        aproveitamento = st.number_input(
            "Aproveitamento (%)", 10, 100, int(round(100 * float(cfg.get("aproveitamento", 0.70)))), 5,
            help="Fração da aposta que se espera vender a full price no período.") / 100.0
    with c6:
        reserva_pct = st.number_input(
            "Reserva CD (%)", 0, 50, int(round(100 * float(cfg.get("reserva_cd_pct", 0.20)))), 1,
            help="Parcela da aposta que fica no CD para reposição.") / 100.0

    todos_tam = ordem_tamanhos()
    grade_padrao = [t for t in todos_tam if t in {"38|PP", "40|P", "42|M", "44|G", "46|GG"}]
    grade_sel = st.multiselect(
        "Grade de tamanhos da aposta", todos_tam, default=grade_padrao,
        help="Filtro: só entram como espelho os modelos que venderam TODOS os tamanhos "
             "da grade. Letra e numeração são equivalentes (36≡XPP, 38≡PP, 40≡P, 42≡M, "
             "44≡G, 46≡GG). A grade também define as colunas da matriz de distribuição.")

    # horizonte = da entrada até o fim saudável da coleção
    fim = fim_periodo_saudavel(colecao, cfg.get("fim_periodo_verao", "02/01"),
                               cfg.get("fim_periodo_inverno", "14/06"))
    horizonte = semanas_ate(dt_entrada, fim)
    desde = float(cfg.get("desde_colecao", 2022.0))
    # a construção (grupo) saiu da tela: inferida do subgrupo+tecido só para a faixa
    grupo_faixa = _grupo_predominante(pp, subgrupo, tecido, desde=desde)
    faixa_info = faixa_preco(grupo_faixa, subgrupo, preco)
    fx = faixa_info["faixa"]
    ctx = contexto_lojas()

    st.info(f"Faixa de preço **{fx or '—'}**  ·  fim do período saudável **{fim:%d/%m/%Y}**  ·  "
            f"horizonte **{horizonte} semanas**  ·  lojas-alvo **{ctx['n_lojas_alvo']}**")
    if pd.Timestamp(dt_entrada) > pd.Timestamp(fim):
        st.warning("A data de entrada é depois do fim do período desta coleção. Confira a coleção escolhida.")

    # -------------------------------------------------------------- candidatos
    cand, soft = candidatos_espelho(
        pp, subgrupo=subgrupo, faixa=fx, tecido=tecido,
        cor_grupo=cores or None, grade=grade_sel or None,
        desde_colecao=desde,
    )
    curva, nivel = curva_por(fp, subgrupo=subgrupo, material=tecido)
    if cand.empty:
        st.warning("Nenhum candidato a espelho com esses filtros. Reduza a grade de "
                   "tamanhos, afrouxe a cor ou ajuste o preço.")
        return

    total_bruto = len(cand)
    janelas = janelas_full_price(pp)
    hoje = pd.Timestamp(date.today())
    dias_ativo = int(cfg.get("dias_para_considerar_ativo", 60))
    cand = enriquecer_velocidade(cand, fp, curva, ctx["ecom_locs"], janelas=janelas,
                                 ativo_ate=hoje, dias_ativo=dias_ativo)
    if cand.empty:
        st.warning(f"Os {total_bruto} candidatos encontrados nunca venderam full price — "
                   "não servem de espelho. Afrouxe os filtros.")
        return

    st.subheader(f"Candidatos a espelho ({len(cand)}) — curva sazonal: {nivel}")
    ocultos = total_bruto - len(cand)
    filtros = []
    filtros.append("cor mantida" if "cor_grupo" in soft else ("cor afrouxada" if cores else "sem filtro de cor"))
    if grade_sel:
        filtros.append(f"só espelhos que venderam a grade {rotulo_grade(set(grade_sel))}")
    st.caption(
        " · ".join(filtros).capitalize()
        + (f" · {ocultos} sem histórico de venda ocultado(s)" if ocultos else "")
        + " · manga/comprimento/fit são apenas consulta. Marque os espelhos a usar."
    )

    # aproveitamento realizado = unidades FP ÷ unidades vendidas em qualquer condição
    tot = totais_por_sku()
    cand = cand.merge(tot, on="cod_sku_pai", how="left")
    aprov_real = (cand["unidades"] / cand["unid_total"]).clip(upper=1.0)
    grades = grades_por_modelo(pp)

    sel_todos = st.checkbox("Selecionar todos", value=False)
    tabela = pd.DataFrame({
        "Usar": sel_todos,
        "foto": cand["url"].map(_foto) if "url" in cand.columns else None,
        "desc_item": cand.get("desc_item"),
        "cod_sku_pai": cand["cod_sku_pai"],
        "coleção": cand.get("desc_colecao"),
        "envio": cand.get("dt_envio"),
        "tecido": cand.get("grupo_material"),
        "grade": cand["cod_sku_pai"].map(lambda s: rotulo_grade(grades.get(s))),
        "cor": cand.get("cor_grupo"),
        "preço": cand.get("preco"),
        "manga": cand.get("desc_manga"),
        "comprimento": cand.get("desc_comprimento"),
        "fit": cand.get("desc_fit"),
        "unid_hist": cand["unidades"],
        "aprov. real": (100 * aprov_real).round(0),
        "n_lojas": cand["n_lojas"],
        "vel/loja": cand["vel_loja_desaz"],
    })
    editado = st.data_editor(
        tabela, hide_index=True, width="stretch", key="editor_espelhos",
        row_height=100,
        column_config={
            "Usar": st.column_config.CheckboxColumn("Usar", default=False),
            "foto": st.column_config.ImageColumn("Foto", width="medium"),
            "envio": st.column_config.DateColumn("Envio", format="DD/MM/YYYY"),
            "preço": st.column_config.NumberColumn("Preço", format="R$ %.0f"),
            "aprov. real": st.column_config.NumberColumn(
                "Aprov. real", format="%.0f%%",
                help="Unidades vendidas a full price ÷ total vendido (todas as condições)."),
            "vel/loja": st.column_config.NumberColumn("Vel/loja", format="%.2f"),
        },
        disabled=[c for c in tabela.columns if c != "Usar"],
    )
    escolhidos = editado[editado["Usar"]]["cod_sku_pai"].tolist()

    # ---------------------------------------------------------------- projetar
    if st.button("Projetar aposta", type="primary", disabled=not escolhidos):
        vels = [velocidade_por_loja_desaz(fp, s, curva, ctx["ecom_locs"], janela=janelas.get(s),
                                          ativo_ate=hoje, dias_ativo=dias_ativo)
                for s in escolhidos]
        vels = [v for v in vels if v]
        if not vels:
            st.error("Os espelhos escolhidos não têm histórico de venda no escopo Souq.")
            return
        ap = projetar_aposta(vels, curva, pd.Timestamp(dt_entrada), ctx["n_lojas_alvo"],
                             horizonte_semanas=horizonte,
                             aproveitamento=aproveitamento,
                             reserva_cd_pct=reserva_pct)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Venda projetada", f"{ap.venda_projetada:.0f}")
        m2.metric("Aposta sugerida", f"{ap.aposta_sugerida:.0f}")
        m3.metric("Reserva CD", f"{ap.reserva_cd:.0f}")
        m4.metric("Semanas-equiv.", f"{ap.semanas_equivalentes:.1f}")
        for aviso in ap.avisos:
            st.warning(aviso)

        # insumos da distribuição: participação (com loja nova) + curva de tamanhos
        # + velocidade de cada loja (alimenta o teto de cobertura)
        skus = [v.cod_sku_pai for v in vels]
        fisico = ~fp["sk_localidade"].isin(ctx["ecom_locs"])
        fp_esp_fisico = fp[fp["cod_sku_pai"].isin(skus) & fisico]
        # participação por loja suavizada: todos os modelos do segmento
        # subgrupo+tecido+fit (fits dos espelhos escolhidos). Poucos espelhos dão
        # uma curva de loja ruidosa; o segmento inteiro é estável. A aposta e a
        # curva de tamanhos seguem vindo só dos espelhos.
        fits = sorted(set(cand.loc[cand["cod_sku_pai"].isin(skus), "desc_fit"].dropna())
                      if "desc_fit" in cand.columns else set())
        pool = pool_suavizacao(pp, subgrupo=subgrupo, tecido=tecido,
                               fits=fits or None, desde_colecao=desde)
        fp_pool_fisico = fp[fp["cod_sku_pai"].isin(pool) & fisico]
        participacoes = participacao_lojas(fp_pool_fisico) or participacao_lojas(fp_esp_fisico)
        n_pool = int(fp_pool_fisico["cod_sku_pai"].nunique())
        st.caption(f"Participação por loja suavizada com **{n_pool} modelos** do segmento "
                   f"{subgrupo}/{tecido}" + (f" (fit: {', '.join(fits)})" if fits else "") + ".")
        # curva por bucket unificado (36≡XPP...), restrita à grade da aposta.
        # Tamanho da grade sem venda nos espelhos entra com peso mínimo para não
        # ficar de fora da matriz (a grade foi decisão de compra).
        curva_tam = curva_tamanhos(fp[fp["cod_sku_pai"].isin(skus)], pp,
                                   col_tamanho="tamanho_grupo")
        if grade_sel:
            curva_tam = {t: p for t, p in curva_tam.items() if t in set(grade_sel)}
            piso = min(curva_tam.values()) / 2 if curva_tam else 1.0
            for t in grade_sel:
                curva_tam.setdefault(t, piso)

        ref = f"{sku_ref} · " if sku_ref else ""
        projecao = {
            "resumo": f"{ref}{subgrupo}/{tecido} · R${preco:.0f} · faixa {fx} · {colecao}",
            "aposta_total": ap.aposta_sugerida,
            "reserva_cd_pct": reserva_pct,
            "participacoes_hist": participacoes,
            "curva_tamanhos": curva_tam,
            "velocidades_loja": velocidade_de_cada_loja(fp, skus, curva, ctx["ecom_locs"]),
            "espelhos": skus,
            "suavizacao": {"n_modelos": n_pool, "fits": fits},
        }
        st.session_state["projecao"] = projecao

        # grava o cenário no histórico (inputs + resultado + insumos da distribuição)
        try:
            from core import historico

            historico.salvar(projecao["resumo"], {
                **projecao,
                "inputs": {
                    "sku_ref": sku_ref, "subgrupo": subgrupo, "tecido": tecido,
                    "cores": cores, "grade": grade_sel, "preco": preco,
                    "dt_entrada": str(dt_entrada), "colecao": colecao,
                    "aproveitamento": aproveitamento, "horizonte_semanas": horizonte,
                    "faixa": fx, "grupo_faixa": grupo_faixa,
                },
                "resultado": {
                    "venda_projetada": ap.venda_projetada, "venda_ecom": ap.venda_ecom,
                    "aposta_sugerida": ap.aposta_sugerida, "reserva_cd": ap.reserva_cd,
                    "semanas_equivalentes": ap.semanas_equivalentes,
                    "vel_por_loja_desaz": ap.vel_por_loja_desaz,
                },
            })
            salvo = " Cenário salvo no Histórico."
        except Exception:
            salvo = " (não foi possível salvar no Histórico.)"
        st.success("Projeção pronta. Abra a aba **Distribuição** para ver a matriz "
                   "loja × tamanho." + salvo)

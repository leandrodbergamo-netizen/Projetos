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
                           produtos_prep, vendas_fp)
from core.config_utils import load_config
from core.dados import (colecoes_projetaveis, curva_tamanhos, fim_periodo_saudavel,
                        participacao_lojas, semanas_ate)
from core.espelho import (candidatos_espelho, enriquecer_velocidade, janelas_full_price,
                          projetar_aposta, velocidade_de_cada_loja,
                          velocidade_por_loja_desaz)
from core.regra_distribuicao import participacao_com_loja_nova
from core.sazonalidade import curva_por
from core.taxonomia import faixa_preco

GRUPOS = ["TECIDO PLANO", "MALHA", "TRICOT", "JEANS"]


def _foto(url):
    u = str(url) if url is not None else ""
    return u if u.lower().endswith((".jpg", ".jpeg", ".png", ".webp")) else None


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
        grupo = st.selectbox("Grupo (construção)", GRUPOS)
    with c2:
        tecido = st.selectbox("Tecido (matéria-prima)", opcoes_por_relevancia("grupo_material"))
        cores = st.multiselect("Cor", opcoes("cor_grupo"),
                               help="Vazio = todas as cores. Selecione uma ou mais para restringir.")
    with c3:
        preco = st.number_input("Preço sugerido (R$)", min_value=0.0, value=498.0, step=10.0)
        dt_entrada = st.date_input("Data de entrada em loja", value=date.today(),
                                   format="DD/MM/YYYY",
                                   help="Premissa dt_envio + 7 dias; posiciona a janela sazonal.")

    c4, c5 = st.columns(2)
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
        reserva_pct = st.number_input("Reserva CD (%)", 0.0, 0.5,
                                      float(cfg.get("reserva_cd_pct", 0.20)), 0.01,
                                      help="Única premissa da aposta; o resto está em Configurações.")

    # horizonte = da entrada até o fim saudável da coleção
    fim = fim_periodo_saudavel(colecao, cfg.get("fim_periodo_verao", "02/01"),
                               cfg.get("fim_periodo_inverno", "14/06"))
    horizonte = semanas_ate(dt_entrada, fim)
    faixa_info = faixa_preco(grupo, subgrupo, preco)
    fx = faixa_info["faixa"]
    ctx = contexto_lojas()

    st.info(f"Faixa de preço **{fx or '—'}**  ·  fim do período saudável **{fim:%d/%m/%Y}**  ·  "
            f"horizonte **{horizonte} semanas**  ·  lojas-alvo **{ctx['n_lojas_alvo']}**")
    if pd.Timestamp(dt_entrada) > pd.Timestamp(fim):
        st.warning("A data de entrada é depois do fim do período desta coleção. Confira a coleção escolhida.")

    # -------------------------------------------------------------- candidatos
    cand, soft = candidatos_espelho(
        pp, subgrupo=subgrupo, grupo=grupo, faixa=fx, tecido=tecido,
        cor_grupo=cores or None, desde_colecao=float(cfg.get("desde_colecao", 2022.0)),
    )
    curva, nivel = curva_por(fp, subgrupo=subgrupo, material=tecido)
    if cand.empty:
        st.warning("Nenhum candidato a espelho com esses filtros. Afrouxe a cor/tecido ou ajuste o preço.")
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
    st.caption(
        f"{'Filtro de cor mantido' if soft else 'Sem filtro de cor'}"
        + (f" · {ocultos} sem histórico de venda ocultado(s)" if ocultos else "")
        + " · manga/comprimento/fit são apenas consulta. Marque os espelhos a usar."
    )

    sel_todos = st.checkbox("Selecionar todos", value=False)
    tabela = pd.DataFrame({
        "Usar": sel_todos,
        "foto": cand["url"].map(_foto) if "url" in cand.columns else None,
        "desc_item": cand.get("desc_item"),
        "cod_sku_pai": cand["cod_sku_pai"],
        "coleção": cand.get("desc_colecao"),
        "cor": cand.get("cor_grupo"),
        "preço": cand.get("preco"),
        "manga": cand.get("desc_manga"),
        "comprimento": cand.get("desc_comprimento"),
        "fit": cand.get("desc_fit"),
        "unid_hist": cand["unidades"],
        "n_lojas": cand["n_lojas"],
        "vel/loja": cand["vel_loja_desaz"],
    })
    editado = st.data_editor(
        tabela, hide_index=True, width="stretch", key="editor_espelhos",
        column_config={
            "Usar": st.column_config.CheckboxColumn("Usar", default=False),
            "foto": st.column_config.ImageColumn("Foto"),
            "preço": st.column_config.NumberColumn("Preço", format="R$ %.0f"),
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
                             aproveitamento=float(cfg.get("aproveitamento", 0.70)),
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
        fp_esp_fisico = fp[fp["cod_sku_pai"].isin(skus) & ~fp["sk_localidade"].isin(ctx["ecom_locs"])]
        st.session_state["projecao"] = {
            "resumo": f"{subgrupo}/{grupo}/{tecido} · R${preco:.0f} · faixa {fx} · {colecao}",
            "aposta_total": ap.aposta_sugerida,
            "reserva_cd_pct": reserva_pct,
            "participacoes_hist": participacao_lojas(fp_esp_fisico),
            "curva_tamanhos": curva_tamanhos(fp[fp["cod_sku_pai"].isin(skus)], pp,
                                             col_tamanho="desc_tamanho"),
            "velocidades_loja": velocidade_de_cada_loja(fp, skus, curva, ctx["ecom_locs"]),
            "espelhos": skus,
        }
        st.success("Projeção pronta. Abra a aba **Distribuição** para ver a matriz loja × tamanho.")

"""Distribuição — matriz loja × tamanho.

Usa a aposta/participações/velocidades calculadas na aba Nova Aposta. O parque-alvo
pode ser restringido por Perfil Econômico e Clima; lojas novas (sem histórico do
espelho) herdam a participação média das lojas com mesmo Perfil+Clima. Ecom entra
na aposta, mas não é destino físico.

Tetos da distribuição inicial (Configurações): cobertura máxima em semanas por
loja e máximo de peças do mesmo SKU-tamanho por loja.
"""
import pandas as pd
import streamlit as st

from core.config_utils import load_config
from core.dados import cluster_por_loja, lojas_alvo_souq, opcoes_perfil_clima
from core.regra_distribuicao import distribuir, participacao_com_loja_nova

TODOS = "TODOS"


def _mostra_resultado(resultado, lojas_df, reserva_planejada=None, aposta_total=None):
    m1, m2, m3, m4 = st.columns(4)
    # a garantia de grade pode consumir a reserva do CD: o delta mostra quanto
    delta = None
    if reserva_planejada is not None and abs(resultado.reserva_cd - reserva_planejada) >= 0.5:
        delta = f"{resultado.reserva_cd - reserva_planejada:.0f} un vs planejado"
    pct = f" ({100 * resultado.reserva_cd / aposta_total:.0f}%)" if aposta_total else ""
    m1.metric("Reserva CD" + pct, f"{resultado.reserva_cd:.0f}", delta=delta,
              delta_color="inverse" if delta else "off")
    m2.metric("Disponível lojas", f"{resultado.disponivel_lojas:.0f}")
    m3.metric("Distribuído", f"{resultado.total_distribuido()}")
    m4.metric("Sobra p/ CD", f"{resultado.sobra_para_cd}")
    for aviso in resultado.avisos:
        st.info(aviso)

    st.subheader("Matriz loja × tamanho")
    matriz = pd.DataFrame(resultado.matriz).T.fillna(0).astype(int)
    if matriz.empty:
        st.dataframe(matriz, width="stretch")
        return
    matriz["TOTAL"] = matriz.sum(axis=1)
    matriz = matriz[matriz["TOTAL"] > 0].sort_values("TOTAL", ascending=False)
    # troca o código da loja pelo nome, com Perfil/Clima ao lado
    nomes = {str(float(r["sk_localidade"])): f'{r["desc_nome"]} ({r["Perfil"]}/{r["Temperatura"]})'
             for _, r in lojas_df.iterrows()}
    matriz.index = [nomes.get(i, i) for i in matriz.index]
    st.dataframe(matriz, width="stretch")
    st.session_state["ultima_distribuicao"] = matriz


def render() -> None:
    st.title("Distribuição")
    st.caption("Reserva CD · participação por loja (loja nova herda de Perfil+Clima) · "
               "teto de cobertura · teto por SKU-tamanho. Ecom entra na aposta, não na matriz física.")

    proj = st.session_state.get("projecao")
    if not proj:
        st.info("Nenhuma projeção ainda. Vá à aba **Nova Aposta**, escolha os espelhos e clique em "
                "**Projetar aposta**.")
        return

    cfg = load_config()
    st.write(f"Projeção atual: **{proj['resumo']}**")

    # ----------------------------------------------- parque-alvo (Perfil/Clima)
    disp = opcoes_perfil_clima()
    c1, c2 = st.columns(2)
    perfis = c1.multiselect("Perfil Econômico", [TODOS] + disp["perfis"], default=[TODOS])
    climas = c2.multiselect("Clima", [TODOS] + disp["climas"], default=[TODOS])
    # "TODOS" (ou seleção vazia) = sem restrição
    perfis = None if (TODOS in perfis or not perfis) else perfis
    climas = None if (TODOS in climas or not climas) else climas

    lojas_df = lojas_alvo_souq(perfis=perfis, climas=climas)
    if lojas_df.empty:
        st.warning("Nenhuma loja ativa com esse Perfil/Clima.")
        return

    lojas_alvo = [str(float(x)) for x in lojas_df["sk_localidade"]]
    part = participacao_com_loja_nova(proj["participacoes_hist"], lojas_alvo, cluster_por_loja())
    novas = [l for l in lojas_alvo if l not in proj["participacoes_hist"]]

    m1, m2, m3 = st.columns(3)
    m1.metric("Aposta total", f"{proj['aposta_total']:.0f}")
    m2.metric("Lojas-alvo", f"{len(lojas_alvo)}")
    m3.metric("Novas (extrapoladas)", f"{len(novas)}")

    cobertura = float(cfg.get("cobertura_maxima_semanas", 6))
    max_tam = int(cfg.get("max_por_tamanho_loja", 4))
    n_tam = len([t for t, p in (proj["curva_tamanhos"] or {}).items() if p > 0])
    garantir = st.checkbox(
        "Garantir ao menos 1 peça por tamanho", value=False,
        help=f"Piso universal: TODAS as lojas-alvo recebem 1 de cada um dos {n_tam} tamanhos "
             "({n} peças no mínimo). O piso é atendido primeiro — reduz o rateio das demais "
             "e, se faltar, consome a reserva do CD (o indicador mostra a reserva efetiva).".format(n=n_tam))
    st.caption(f"Tetos (Configurações): máx. **{cobertura:.0f} semanas** de cobertura por loja e "
               f"máx. **{max_tam} peças** do mesmo SKU-tamanho por loja.")

    if st.button("Distribuir", type="primary"):
        resultado = distribuir(
            aposta_total=proj["aposta_total"],
            participacoes=part,
            curva_tamanhos=proj["curva_tamanhos"],
            reserva_cd_pct=proj.get("reserva_cd_pct", 0.20),
            velocidades_semanais=proj.get("velocidades_loja") or None,
            cobertura_max_semanas=cobertura,
            max_por_tamanho_loja=max_tam,
            garantir_grade_completa=garantir,
        )
        reserva_planejada = proj["aposta_total"] * proj.get("reserva_cd_pct", 0.20)
        _mostra_resultado(resultado, lojas_df, reserva_planejada=reserva_planejada,
                          aposta_total=proj["aposta_total"])

"""Distribuição — seção embutida na aba Nova Aposta (matriz loja × tamanho).

Usa a aposta/participações/velocidades da projeção atual. O parque-alvo pode ser
restringido por Perfil Econômico e Clima; loja nova usa a loja espelho do
`config/lojas_espelho.yaml` (ex.: Casa Jardins = 75% do Iguatemi SP) e, sem
regra, herda a média do cluster Perfil+Clima. Ecom entra na aposta, mas não é
destino físico. O resultado fica na tela até a próxima projeção.
"""
import pandas as pd
import streamlit as st

from core.config_utils import load_config
from core.dados import (cluster_por_loja, espelhos_loja_nova, lojas_alvo_souq,
                        opcoes_perfil_clima)
from core.regra_distribuicao import distribuir, participacao_com_loja_nova

TODOS = "TODOS"


def _mostra_resultado(resultado, lojas_df, reserva_planejada=None, aposta_total=None):
    acrescimo = getattr(resultado, "acrescimo_garantia", 0)
    m1, m2, m3, m4 = st.columns(4)
    aposta_final = (aposta_total or 0) + acrescimo
    m1.metric("Aposta final", f"{aposta_final:.0f}",
              delta=f"+{acrescimo} un pela grade garantida" if acrescimo else None)
    pct = f" ({100 * resultado.reserva_cd / aposta_total:.0f}%)" if aposta_total else ""
    m2.metric("Reserva CD" + pct, f"{resultado.reserva_cd:.0f}")
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


def secao(proj: dict) -> None:
    """Renderiza a seção de distribuição para a projeção atual."""
    st.subheader("Distribuição")
    st.caption("Participação por loja (loja nova usa a loja espelho ou o cluster "
               "Perfil+Clima) · teto de cobertura · teto por SKU-tamanho. "
               "Ecom entra na aposta, não na matriz física.")

    cfg = load_config()

    # ----------------------------------------------- parque-alvo (Perfil/Clima)
    disp = opcoes_perfil_clima()
    c1, c2, c3 = st.columns(3)
    perfis = c1.multiselect("Perfil Econômico", [TODOS] + disp["perfis"], default=[TODOS])
    climas = c2.multiselect("Clima", [TODOS] + disp["climas"], default=[TODOS])
    max_tam = int(c3.number_input(
        "Máx. peças por SKU-tamanho/loja", 1, 50, int(cfg.get("max_por_tamanho_loja", 4)),
        help="Teto por célula da matriz loja × tamanho. O excedente volta ao CD."))
    # "TODOS" (ou seleção vazia) = sem restrição
    perfis = None if (TODOS in perfis or not perfis) else perfis
    climas = None if (TODOS in climas or not climas) else climas

    lojas_df = lojas_alvo_souq(perfis=perfis, climas=climas)
    if lojas_df.empty:
        st.warning("Nenhuma loja ativa com esse Perfil/Clima.")
        return

    lojas_alvo = [str(float(x)) for x in lojas_df["sk_localidade"]]
    espelhos = espelhos_loja_nova()
    ldp = proj.get("lojas_com_espelho_proprio")
    com_dado = set(ldp) if ldp is not None else None
    part = participacao_com_loja_nova(
        proj["participacoes_hist"], lojas_alvo, cluster_por_loja(),
        lojas_espelho=espelhos, com_dado_proprio=com_dado)
    novas = [l for l in lojas_alvo if l not in proj["participacoes_hist"]]

    # quais lojas estão usando a regra de loja espelho nesta distribuição
    usando_espelho = []
    for loja, (esp, fator, nome_nova, nome_esp) in espelhos.items():
        if loja not in lojas_alvo or esp not in proj["participacoes_hist"]:
            continue
        tem_proprio = (loja in com_dado) if com_dado is not None \
            else (loja in proj["participacoes_hist"])
        if not tem_proprio:
            usando_espelho.append(f"{nome_nova} ← {fator:.0%} de {nome_esp}")
    if usando_espelho:
        st.caption("Lojas novas por loja espelho: " + " · ".join(usando_espelho) + ".")

    m1, m2, m3 = st.columns(3)
    m1.metric("Aposta total", f"{proj['aposta_total']:.0f}")
    m2.metric("Lojas-alvo", f"{len(lojas_alvo)}")
    m3.metric("Novas (extrapoladas)", f"{len(novas)}")

    cobertura = float(cfg.get("cobertura_maxima_semanas", 6))
    n_tam = len([t for t, p in (proj["curva_tamanhos"] or {}).items() if p > 0])
    garantir = st.checkbox(
        "Garantir ao menos 1 peça por tamanho", value=False,
        help=f"TODAS as lojas-alvo recebem 1 de cada um dos {n_tam} tamanhos. As peças "
             "que faltarem são SOMADAS à aposta (não reduzem o rateio das demais lojas "
             "nem a reserva do CD); um aviso mostra o acréscimo.")
    st.caption(f"Teto de cobertura (Configurações): máx. **{cobertura:.0f} semanas** "
               "da velocidade da própria loja.")

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
        st.session_state["distribuicao"] = {"resumo": proj["resumo"], "resultado": resultado}

    # resultado persiste na tela (some se a projeção mudar)
    d = st.session_state.get("distribuicao")
    if d and d.get("resumo") == proj["resumo"]:
        _mostra_resultado(d["resultado"], lojas_df,
                          reserva_planejada=proj["aposta_total"] * proj.get("reserva_cd_pct", 0.20),
                          aposta_total=proj["aposta_total"])

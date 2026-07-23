"""Distribuição — seção embutida na aba Nova Aposta (matriz loja × tamanho).

Usa a aposta/participações/velocidades da projeção atual. O parque-alvo pode ser
restringido por Perfil Econômico e Clima; loja nova usa a loja espelho do
`config/lojas_espelho.yaml` (ex.: Casa Jardins = 75% do Iguatemi SP) e, sem
regra, herda a média do cluster Perfil+Clima. Ecom entra na aposta, mas não é
destino físico. O resultado fica na tela até a próxima projeção.
"""
import pandas as pd
import streamlit as st

from app import estilo
from core.config_utils import load_config
from core.dados import (cluster_por_loja, espelhos_loja_nova, lojas_alvo_souq,
                        opcoes_perfil_clima)
from core.regra_distribuicao import distribuir, participacao_com_loja_nova

TODOS = "TODOS"


def _mostra_resultado(resultado, lojas_df, proj, aposta_total=None, chave_editor="0"):
    acrescimo = getattr(resultado, "acrescimo_garantia", 0)
    m1, m2, m3, m4 = st.columns(4)
    aposta_final = (aposta_total or 0) + acrescimo
    estilo.kpi(m1, "Aposta final", f"{aposta_final:.0f}",
               f"+{acrescimo} un pela grade garantida" if acrescimo else "unidades")
    pct = f"{100 * resultado.reserva_cd / aposta_total:.0f}% da aposta" if aposta_total else ""
    estilo.kpi(m2, "Reserva CD", f"{resultado.reserva_cd:.0f}", pct)
    estilo.kpi(m3, "Distribuído", f"{resultado.total_distribuido()}",
               "unidades nas lojas", escuro=True)
    estilo.kpi(m4, "Sobra p/ CD", f"{resultado.sobra_para_cd}", "não distribuído")
    st.markdown("")
    for aviso in resultado.avisos:
        st.info(aviso)

    st.subheader("Matriz loja × tamanho")
    st.caption("As células são **editáveis**. Edite quantas quiser e clique em "
               "**Aplicar edições** — os totais recalculam de uma vez só.")
    if st.session_state.get("flash_matriz"):
        st.caption(f":green[{st.session_state.pop('flash_matriz')}]")
    matriz = pd.DataFrame(resultado.matriz).T.fillna(0).astype(int)
    if matriz.empty:
        st.dataframe(matriz, width="stretch")
        return
    # todas as lojas-alvo aparecem (a zerada pode ser editada para cima),
    # ordenadas da maior para a menor; nome no lugar do código
    matriz = matriz.loc[matriz.sum(axis=1).sort_values(ascending=False).index]
    nomes = {str(float(r["sk_localidade"])): f'{r["desc_nome"]} ({r["Perfil"]}/{r["Temperatura"]})'
             for _, r in lojas_df.iterrows()}
    matriz.index = [nomes.get(i, i) for i in matriz.index]
    # o form segura os reruns: as edições só são processadas no clique
    with st.form(f"form_matriz_{chave_editor}"):
        editada = st.data_editor(
            matriz, width="stretch", key=f"editor_matriz_{chave_editor}",
            column_config={c: st.column_config.NumberColumn(c, min_value=0, step=1, format="%d")
                           for c in matriz.columns})
        st.form_submit_button("Aplicar edições", type="primary")

    tot_editado = int(editada.to_numpy().sum())
    tot_modelo = int(resultado.total_distribuido())
    delta = tot_editado - tot_modelo
    c1, c2, _ = st.columns([1.4, 1.4, 2])
    c1.metric("Distribuído (após edição)", f"{tot_editado}",
              delta=f"{delta:+d} un vs modelo" if delta else None)
    c2.metric("Aposta final (após edição)", f"{aposta_final + delta:.0f}")
    with st.expander("Totais da matriz editada"):
        tt = editada.copy()
        tt["TOTAL"] = tt.sum(axis=1)
        tt.loc["TOTAL"] = tt.sum(axis=0)
        st.dataframe(tt, width="stretch")
    st.session_state["ultima_distribuicao"] = editada

    b1, b2, _ = st.columns([1.8, 1.8, 2])
    if b1.button("↺ Recarregar sugestão do modelo"):
        d = st.session_state.get("distribuicao") or {}
        d["rodada"] = int(d.get("rodada", 0)) + 1
        st.session_state["flash_matriz"] = "Sugestão do modelo recarregada ✓"
        st.rerun()
    if b2.button("Salvar distribuição no Histórico"):
        try:
            from core import historico

            matriz_dict = {str(i): {str(c): int(v) for c, v in linha.items()}
                           for i, linha in editada.iterrows()}
            historico.salvar(proj["resumo"] + " · distribuição", {
                **proj,
                "distribuicao_editada": matriz_dict,
                "aposta_final": float(aposta_final + delta),
                "distribuido_editado": tot_editado,
            })
            st.session_state["flash_matriz"] = "Distribuição salva no Histórico ✓"
        except Exception:
            st.session_state["flash_matriz"] = "Não foi possível salvar no Histórico."
        st.rerun()


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
    sugerida = float(proj["aposta_total"])
    # o modelo sugere, o comercial decide: a aposta é editável e a distribuição
    # usa o valor editado (ex.: modelo 90, comercial aposta 120)
    aposta_usada = float(m1.number_input(
        "Aposta a distribuir (un)", 0, None, int(round(sugerida)), 5,
        key=f"aposta_edit_{proj['resumo']}",
        help="Editável — o modelo sugere, o comercial decide. A distribuição usa este valor."))
    if round(aposta_usada) != round(sugerida):
        m1.caption(f"Modelo sugeriu **{sugerida:.0f} un**.")
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

    if st.button(f"Distribuir {aposta_usada:.0f} un em {len(lojas_alvo)} lojas",
                 type="primary"):
        resultado = distribuir(
            aposta_total=aposta_usada,
            participacoes=part,
            curva_tamanhos=proj["curva_tamanhos"],
            reserva_cd_pct=proj.get("reserva_cd_pct", 0.20),
            velocidades_semanais=proj.get("velocidades_loja") or None,
            cobertura_max_semanas=cobertura,
            max_por_tamanho_loja=max_tam,
            garantir_grade_completa=garantir,
        )
        rodada = int(st.session_state.get("_dist_rodada", 0)) + 1
        st.session_state["_dist_rodada"] = rodada
        st.session_state["distribuicao"] = {"resumo": proj["resumo"], "resultado": resultado,
                                            "aposta_usada": aposta_usada, "rodada": rodada}

    # resultado persiste na tela (some se a projeção mudar); a chave do editor
    # muda a cada Distribuir para as edições de célula não vazarem entre rodadas
    d = st.session_state.get("distribuicao")
    if d and d.get("resumo") == proj["resumo"]:
        _mostra_resultado(d["resultado"], lojas_df, proj,
                          aposta_total=d.get("aposta_usada", proj["aposta_total"]),
                          chave_editor=str(d.get("rodada", 0)))

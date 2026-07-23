"""Configurações — premissas gerais em cartões, com salvamento automático.

O que é premissa da própria aposta (aproveitamento, reserva CD, teto por
SKU-tamanho) é editado no fluxo da aposta; aqui ficam as regras estáveis.
"""
import streamlit as st

from core.config_utils import load_config, save_config
from core.dados import espelhos_loja_nova


def render() -> None:
    st.title("Configurações")
    st.caption("Premissas gerais do app — **as alterações são salvas automaticamente**. "
               "Aproveitamento, reserva CD e teto por SKU-tamanho são editados na própria aposta.")
    cfg = load_config()

    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        st.subheader("Fim de período saudável")
        st.caption("Até quando a coleção deve estar vendida — define o horizonte da projeção.")
        a, b = st.columns(2)
        fim_verao = a.text_input("VERÃO (dd/mm)", str(cfg.get("fim_periodo_verao", "02/01")))
        fim_inverno = b.text_input("INVERNO (dd/mm)", str(cfg.get("fim_periodo_inverno", "14/06")))
    with c2, st.container(border=True):
        st.subheader("Distribuição")
        st.caption("A reserva CD sugerida ao abrir uma aposta — é ela que garante a "
                   "reposição (não há teto de cobertura por loja).")
        reserva_cd_pct = st.number_input(
            "Reserva CD padrão (%)", 0, 50,
            int(round(100 * float(cfg.get("reserva_cd_pct", 0.20)))), 5) / 100.0

    c3, c4 = st.columns(2)
    with c3, st.container(border=True):
        st.subheader("Escopo e sazonalidade")
        st.caption("Qual histórico entra na conta e quando a curva recua de nível.")
        a, b = st.columns(2)
        min_amostra = a.number_input("Amostra mín. da curva (un)", 100, 5000,
                                     int(cfg.get("min_amostra_curva", 800)), 100)
        desde_colecao = b.number_input("Coleções desde (rank)", 2018.0, 2030.0,
                                       float(cfg.get("desde_colecao", 2022.0)), 0.5,
                                       help="Inverno 2022 = 2022.0; Verão 2022-2023 = 2022.5")
    with c4, st.container(border=True):
        st.subheader("Lojas espelho (novas)")
        st.caption("Loja nova sem venda dos espelhos usa a participação da loja espelho.")
        regras = espelhos_loja_nova()
        if regras:
            for _, (_, fator, nome_nova, nome_esp) in sorted(regras.items(), key=lambda x: x[1][2]):
                st.markdown(f"**{nome_nova}** ← {fator:.0%} de {nome_esp}")
        else:
            st.markdown("_Nenhuma regra configurada._")
        st.caption("Editável em `config/lojas_espelho.yaml`.")

    # salvamento automático: qualquer mudança vai direto para o config
    novo = {
        "reserva_cd_pct": reserva_cd_pct,
        "fim_periodo_verao": fim_verao.strip(),
        "fim_periodo_inverno": fim_inverno.strip(),
        "min_amostra_curva": int(min_amostra),
        "desde_colecao": desde_colecao,
    }
    if any(cfg.get(k) != v for k, v in novo.items()):
        cfg.update(novo)
        save_config(cfg)
        st.toast("Parâmetros salvos.", icon="✅")

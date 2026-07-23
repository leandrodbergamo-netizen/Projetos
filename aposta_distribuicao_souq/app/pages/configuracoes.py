"""Configurações — premissas gerais em cartões, com salvamento automático.

O que é premissa da própria aposta (aproveitamento, reserva CD, teto por
SKU-tamanho) é editado no fluxo da aposta; aqui ficam as regras estáveis.
"""
from datetime import date

import streamlit as st

from core.config_utils import load_config, save_config
from core.dados import espelhos_loja_nova, rank_colecao

_MARCA_CARD = '<span class="cfg-card"></span>'   # ativa o fundo cinza (estilo.py)


def _opcoes_colecao() -> list[str]:
    """Nomes de coleção de Inverno 2022 até hoje (para o corte de escopo)."""
    ops = []
    for ano in range(2022, date.today().year + 1):
        ops.append(f"INVERNO {ano}")
        ops.append(f"VERÃO {ano}-{ano + 1}")
    return ops


def render() -> None:
    st.title("Configurações")
    st.caption("Premissas gerais do app — **as alterações são salvas automaticamente**. "
               "Aproveitamento, reserva CD e teto por SKU-tamanho são editados na própria aposta.")
    cfg = load_config()

    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        st.markdown(_MARCA_CARD, unsafe_allow_html=True)
        st.subheader("Fim de período saudável")
        st.caption("Até quando a coleção deve estar vendida — define o horizonte da projeção.")
        a, b = st.columns(2)
        fim_verao = a.text_input("VERÃO (dd/mm)", str(cfg.get("fim_periodo_verao", "02/01")))
        fim_inverno = b.text_input("INVERNO (dd/mm)", str(cfg.get("fim_periodo_inverno", "14/06")))
    with c2, st.container(border=True):
        st.markdown(_MARCA_CARD, unsafe_allow_html=True)
        st.subheader("Distribuição")
        st.caption("A reserva CD sugerida ao abrir uma aposta — é ela que garante a "
                   "reposição (não há teto de cobertura por loja).")
        reserva_cd_pct = st.number_input(
            "Reserva CD padrão (%)", 0, 50,
            int(round(100 * float(cfg.get("reserva_cd_pct", 0.20)))), 5) / 100.0

    c3, c4 = st.columns(2)
    with c3, st.container(border=True):
        st.markdown(_MARCA_CARD, unsafe_allow_html=True)
        st.subheader("Escopo e sazonalidade")
        st.caption("Qual histórico entra na conta e quando a curva recua de nível.")
        a, b = st.columns(2)
        min_amostra = a.number_input("Amostra mín. da curva (un)", 100, 5000,
                                     int(cfg.get("min_amostra_curva", 800)), 100)
        ops_col = _opcoes_colecao()
        atual = float(cfg.get("desde_colecao", 2022.0))
        idx = next((i for i, c in enumerate(ops_col) if rank_colecao(c) == atual), 0)
        desde_nome = b.selectbox("Considerar coleções desde", ops_col, index=idx,
                                 key="cfg_desde_colecao",
                                 help="Só coleções a partir desta entram como espelho.")
        desde_colecao = float(rank_colecao(desde_nome))
    with c4, st.container(border=True):
        st.markdown(_MARCA_CARD, unsafe_allow_html=True)
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

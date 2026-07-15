import streamlit as st
from pathlib import Path

from app.pages import nova_aposta, distribuicao, historico, configuracoes, auditoria

st.set_page_config(page_title="Aposta & Distribuição — Souq Roupa", page_icon="🧵", layout="wide")

PAGES = {
    "Nova Aposta": nova_aposta,
    "Distribuição": distribuicao,
    "Histórico": historico,
    "Configurações": configuracoes,
    "Auditoria": auditoria,
}

st.sidebar.title("Aposta & Distribuição")
st.sidebar.caption("Souq Roupa")
selection = st.sidebar.radio("Navegação", list(PAGES.keys()))

from app.dados_app import botao_recarregar  # noqa: E402  (após set_page_config)

st.sidebar.divider()
botao_recarregar()

page = PAGES[selection]
page.render()

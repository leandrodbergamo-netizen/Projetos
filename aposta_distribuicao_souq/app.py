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

# Navegação em blocos (botões de largura cheia); o ativo fica destacado.
if "pagina" not in st.session_state:
    st.session_state.pagina = next(iter(PAGES))
for nome in PAGES:
    ativo = st.session_state.pagina == nome
    if st.sidebar.button(nome, key=f"nav_{nome}", width="stretch",
                         type="primary" if ativo else "secondary"):
        st.session_state.pagina = nome
        st.rerun()
selection = st.session_state.pagina

from app.dados_app import botao_recarregar  # noqa: E402  (após set_page_config)

st.sidebar.divider()
botao_recarregar()

page = PAGES[selection]
try:
    page.render()
except Exception as erro:
    from core import fonte

    if not fonte.usa_supabase():
        raise
    # Na nuvem o Streamlit censura a mensagem da exceção; st.error não é
    # censurado, então mostramos aqui o diagnóstico (sem a senha).
    st.error(
        "Falha ao ler os dados do Supabase.\n\n"
        f"**Conexão em uso:** `{fonte.diagnostico()}`\n\n"
        f"**Erro:** `{str(erro)[:300]}`\n\n"
        "Se `usuario_tem_ref_do_projeto=False`, o usuário do Secret está sem o "
        "sufixo `.<ref-do-projeto>` — o pooler responde *tenant/user not found*."
    )
    st.stop()

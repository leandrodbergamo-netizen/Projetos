import streamlit as st
from pathlib import Path

from app import estilo
from app.pages import nova_aposta, historico, configuracoes, auditoria

st.set_page_config(page_title="Aposta & Distribuição — Souq Roupa", page_icon="🧵", layout="wide")
estilo.aplicar()

# A distribuição vive dentro da própria aba de aposta (operação fluida).
PAGES = {
    "Nova Aposta": nova_aposta,
    "Histórico": historico,
    "Configurações": configuracoes,
    "Auditoria": auditoria,
}

st.sidebar.markdown('<div class="marca-souq">Souq</div>'
                    '<div class="marca-sub">Aposta &amp; Distribuição</div>',
                    unsafe_allow_html=True)

# Navegação em blocos (botões de largura cheia); o ativo fica destacado.
if st.session_state.get("pagina") not in PAGES:
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

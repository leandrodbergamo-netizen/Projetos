import streamlit as st

from core.config_utils import load_config, save_config


def render() -> None:
    st.title("Configurações")
    st.write("Premissas gerais do app. **As alterações são salvas automaticamente.**")
    cfg = load_config()

    st.subheader("Aposta")
    st.caption("Aproveitamento e reserva CD são editados na própria aba Nova Aposta.")
    reserva_cd_pct = st.number_input(
        "Reserva CD padrão (%)", 0, 50,
        int(round(100 * float(cfg.get("reserva_cd_pct", 0.20)))), 5,
        help="Valor inicial sugerido na aba Nova Aposta.") / 100.0

    st.subheader("Fim de período saudável")
    st.caption("Define até quando a coleção deve estar vendida — é o que determina o horizonte da projeção.")
    c3, c4 = st.columns(2)
    fim_verao = c3.text_input("Coleções de VERÃO (dd/mm)", str(cfg.get("fim_periodo_verao", "02/01")))
    fim_inverno = c4.text_input("Coleções de INVERNO (dd/mm)", str(cfg.get("fim_periodo_inverno", "14/06")))

    st.subheader("Tetos da distribuição inicial")
    st.caption("O máx. de peças por SKU-tamanho é editado na própria seção de "
               "Distribuição (aba Nova Aposta).")
    cobertura = st.number_input(
        "Cobertura máxima por loja (semanas)", 1.0, 26.0,
        float(cfg.get("cobertura_maxima_semanas", 6)), 1.0,
        help="Nenhuma loja recebe mais que N semanas da sua própria velocidade de venda.")

    st.subheader("Escopo e sazonalidade")
    c7, c8 = st.columns(2)
    min_amostra = c7.number_input("Amostra mínima da curva (un)", 100, 5000,
                                  int(cfg.get("min_amostra_curva", 800)), 100,
                                  help="Abaixo disso, a curva cai para um nível mais genérico.")
    desde_colecao = c8.number_input("Considerar coleções desde (rank)", 2018.0, 2030.0,
                                    float(cfg.get("desde_colecao", 2022.0)), 0.5,
                                    help="Inverno 2022 = 2022.0; Verão 2022-2023 = 2022.5")

    # salvamento automático: qualquer mudança vai direto para o config
    novo = {
        "reserva_cd_pct": reserva_cd_pct,
        "fim_periodo_verao": fim_verao.strip(),
        "fim_periodo_inverno": fim_inverno.strip(),
        "cobertura_maxima_semanas": cobertura,
        "min_amostra_curva": int(min_amostra),
        "desde_colecao": desde_colecao,
    }
    if any(cfg.get(k) != v for k, v in novo.items()):
        cfg.update(novo)
        save_config(cfg)
        st.toast("Parâmetros salvos.", icon="✅")

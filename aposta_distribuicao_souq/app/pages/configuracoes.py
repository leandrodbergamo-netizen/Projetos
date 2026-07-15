import streamlit as st

from core.config_utils import load_config, save_config


def render() -> None:
    st.title("Configurações")
    st.write("Parâmetros do app (persistem em config/parametros.yaml).")
    cfg = load_config()

    c1, c2 = st.columns(2)
    with c1:
        aproveitamento = st.number_input("Aproveitamento", 0.0, 1.0,
                                          float(cfg.get("aproveitamento", 0.70)), 0.01)
        reserva_cd_pct = st.number_input("Reserva CD (%)", 0.0, 1.0,
                                         float(cfg.get("reserva_cd_pct", 0.20)), 0.01)
        horizonte = st.number_input("Horizonte (semanas)", 4, 52,
                                    int(cfg.get("horizonte_semanas", 12)))
    with c2:
        min_amostra = st.number_input("Amostra mínima da curva (un)", 100, 5000,
                                      int(cfg.get("min_amostra_curva", 800)), 100)
        desde_colecao = st.number_input("Considerar coleções desde (rank)", 2018.0, 2030.0,
                                        float(cfg.get("desde_colecao", 2022.0)), 0.5,
                                        help="Inverno 2022 = 2022.0; Verão 2022-2023 = 2022.5")

    if st.button("Salvar parâmetros"):
        cfg.update({
            "aproveitamento": aproveitamento,
            "reserva_cd_pct": reserva_cd_pct,
            "horizonte_semanas": int(horizonte),
            "min_amostra_curva": int(min_amostra),
            "desde_colecao": desde_colecao,
        })
        save_config(cfg)
        st.success("Parâmetros salvos.")

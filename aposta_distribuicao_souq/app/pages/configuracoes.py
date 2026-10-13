"""Configurações — premissas gerais em cartões, com salvamento automático.

O que é premissa da própria aposta (aproveitamento, reserva CD, teto por
SKU-tamanho) é editado no fluxo da aposta; aqui ficam as regras estáveis:
horizonte, reserva padrão, escopo, elasticidade de crescimento e o parque de
lojas ativas com as lojas espelho. Com banco configurado, tudo isto é
compartilhado pelo time (tabela `aposta_parametros`).
"""
from datetime import date

import pandas as pd
import streamlit as st

from app.dados_app import (aceleracao_lojas, crescimento_padrao_pct, invalidar_lojas,
                           salvar_aceleracao)
from core import aceleracao as acel
from core.config_utils import load_config, onde_grava, save_config
from core.dados import espelhos_loja_nova, lojas_souq, rank_colecao

_MARCA_CARD = '<span class="cfg-card"></span>'   # ativa o fundo cinza (estilo.py)
_SEM_ESPELHO = "—"
_CHAVE_EDITOR_LOJAS = "cfg_lojas_editor"


def _opcoes_colecao() -> list[str]:
    """Nomes de coleção de Inverno 2022 até hoje (para o corte de escopo)."""
    ops = []
    for ano in range(2022, date.today().year + 1):
        ops.append(f"INVERNO {ano}")
        ops.append(f"VERÃO {ano}-{ano + 1}")
    return ops


def _pct(valor, padrao: int) -> int:
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return padrao
    return padrao if v != v else int(round(v))


# --------------------------------------------------------------------------- #
# Lojas ativas + lojas espelho
# --------------------------------------------------------------------------- #
def _card_lojas(cfg: dict, padrao_cresc: int) -> tuple[list[str], dict, dict]:
    """Editor do parque: quem está ativa hoje, qual loja espelho usa e o crescimento.

    Devolve (lojas_inativas, lojas_espelho, aceleracao) no formato gravado:
    - `lojas_inativas`: lista de sk ('122.0') desligadas aqui (além das fechadas na base);
    - `lojas_espelho`: {sk_nova: {"espelho": sk|None, "fator": 0.75}} só onde difere do
      `config/lojas_espelho.yaml` (None = regra do YAML desligada);
    - `aceleracao`: {sk: %} com 100 = histórico, gravado por `core/aceleracao` (tabela
      própria) só para lojas fora do padrão (`padrao_cresc`). Na tela aparece como
      crescimento: 0 = histórico, +20 = vende 20% a mais, -100 = não vende (sai do
      parque e da matriz); loja sem ajuste mostra o padrão.
    """
    lj = lojas_souq(incluir_ecom=False).copy()
    lj["sk"] = [str(float(x)) for x in lj["sk_localidade"]]
    lj["nome"] = lj["desc_nome"].astype(str)
    lj = lj.sort_values("nome")
    fechadas = lj[lj["dt_fechamento"].notna()]
    abertas = lj[lj["dt_fechamento"].isna()]

    inativas_cfg = {str(x) for x in (cfg.get("lojas_inativas") or [])}
    regras = espelhos_loja_nova(cfg=cfg)                       # YAML + sobreposição salva
    regras_yaml = espelhos_loja_nova(cfg={"lojas_espelho": {}})  # só o YAML
    nome_por_sk = dict(zip(abertas["sk"], abertas["nome"]))
    sk_por_nome = {v: k for k, v in nome_por_sk.items()}

    tab = pd.DataFrame({
        "sk": abertas["sk"].values,
        "Loja": abertas["nome"].values,
        "Perfil": abertas["Perfil"].values if "Perfil" in abertas.columns else "",
        "Clima": abertas["Temperatura"].values if "Temperatura" in abertas.columns else "",
        "Abertura": pd.to_datetime(abertas["dt_abertura"], errors="coerce").dt.strftime("%d/%m/%Y").values,
    })
    tab["Ativa"] = [sk not in inativas_cfg for sk in tab["sk"]]
    tab["Loja espelho"] = [nome_por_sk.get(regras[sk][0], _SEM_ESPELHO) if sk in regras else _SEM_ESPELHO
                           for sk in tab["sk"]]
    tab["% da loja espelho"] = [int(round(100 * regras[sk][1])) if sk in regras else 100
                                for sk in tab["sk"]]
    acel_atual = aceleracao_lojas()
    pct_padrao = acel.PCT_NEUTRO + padrao_cresc
    tab["Crescimento (%)"] = [_pct(acel_atual.get(sk, pct_padrao), pct_padrao) - acel.PCT_NEUTRO
                              for sk in tab["sk"]]

    n_ativas = int(tab["Ativa"].sum())
    n_esp = int((tab["Loja espelho"] != _SEM_ESPELHO).sum())
    n_cresc = int((tab["Crescimento (%)"] != padrao_cresc).sum())
    st.caption(f"**{n_ativas}** lojas ativas de {len(tab)} abertas na base · {n_esp} com loja "
               f"espelho · {n_cresc} fora do crescimento padrão ({padrao_cresc:+d}%). "
               "**Ativa** desmarcada tira a loja "
               "do modelo. **Loja espelho**: enquanto a loja não tiver venda própria dos "
               "espelhos da aposta, recebe *% da loja espelho* × participação da loja indicada. "
               "**Crescimento**: % sobre a venda que a loja teria (própria ou via espelho); "
               "vale para todas as apostas, na projeção e no rateio.")
    editado = st.data_editor(
        tab, hide_index=True, width="stretch", key=_CHAVE_EDITOR_LOJAS,
        height=min(38 + 35 * len(tab), 600),
        disabled=["Loja", "Perfil", "Clima", "Abertura"],
        column_order=["Loja", "Perfil", "Clima", "Abertura", "Ativa", "Loja espelho",
                      "% da loja espelho", "Crescimento (%)"],
        column_config={
            "sk": None,
            "Loja": st.column_config.TextColumn("Loja", width="medium"),
            "Perfil": st.column_config.TextColumn("Perfil", width="small"),
            "Clima": st.column_config.TextColumn("Clima", width="small"),
            "Abertura": st.column_config.TextColumn("Abertura", width="small"),
            "Ativa": st.column_config.CheckboxColumn("Ativa", width="small",
                                                     help="Entra na projeção e na distribuição."),
            "Loja espelho": st.column_config.SelectboxColumn(
                "Loja espelho", options=[_SEM_ESPELHO] + sorted(nome_por_sk.values()),
                help="Usada enquanto a loja não tiver venda própria dos espelhos."),
            "% da loja espelho": st.column_config.NumberColumn(
                "% da loja espelho", min_value=0, max_value=200, step=5, format="%d%%",
                help="Quanto da participação da loja espelho a loja nova recebe (75 = 75%)."),
            "Crescimento (%)": st.column_config.NumberColumn(
                "Crescimento (%)", min_value=-100, max_value=200, step=5, format="%+d%%",
                help=f"Padrão {padrao_cresc:+d}% · 0 = histórico · +20 = vende 20% a mais · "
                     "-100 = não vende (sai do parque)."),
        })
    if len(fechadas):
        st.caption("Fechadas na base (fora do modelo): " + " · ".join(
            f"{r['nome']} ({pd.Timestamp(r['dt_fechamento']):%m/%Y})" for _, r in fechadas.iterrows()) + ".")

    # o que mudou nesta rodada (vai no toast, para edição acidental não passar despercebida)
    mudancas = []
    for col in ("Ativa", "Loja espelho", "% da loja espelho", "Crescimento (%)"):
        for nome, antes, depois in zip(tab["Loja"], tab[col], editado[col]):
            if str(antes) != str(depois):
                mudancas.append(f"{nome}: {col} {antes} → {depois}")
    st.session_state["_cfg_lojas_mudancas"] = mudancas
    inativas = sorted(sk for sk, ativa in zip(editado["sk"], editado["Ativa"]) if not bool(ativa))
    sobreposicao: dict = {}
    for sk, esp_nome, fator in zip(editado["sk"], editado["Loja espelho"], editado["% da loja espelho"]):
        esp_sk = sk_por_nome.get(esp_nome) if esp_nome and esp_nome != _SEM_ESPELHO else None
        if esp_sk == sk:
            esp_sk = None                       # loja espelho de si mesma não faz sentido
        desejado = (esp_sk, round(_pct(fator, 100) / 100.0, 4)) if esp_sk else (None, None)
        base = regras_yaml.get(sk)
        atual = (base[0], round(float(base[1]), 4)) if base else (None, None)
        if desejado != atual:
            sobreposicao[sk] = {"espelho": desejado[0], "fator": desejado[1] if desejado[0] else None}
    aceleracao = acel.normalizar({sk: acel.PCT_NEUTRO + _pct(c, padrao_cresc)
                                  for sk, c in zip(editado["sk"], editado["Crescimento (%)"])},
                                 padrao=pct_padrao)
    return inativas, sobreposicao, aceleracao


# --------------------------------------------------------------------------- #
def render() -> None:
    st.title("Configurações")
    st.caption("Premissas gerais do app — **as alterações são salvas automaticamente** "
               f"{onde_grava()}. Aproveitamento, reserva CD e teto por SKU-tamanho são "
               "editados na própria aposta.")
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
        st.subheader("Elasticidade de crescimento")
        st.caption("Crescimento esperado sobre a venda projetada pelos espelhos, para toda "
                   "aposta: **0%** = repete o histórico · **+10%** = aposta 10% acima · "
                   "negativo reduz. Multiplica a venda física e o Ecom; o crescimento por "
                   "loja (tabela abaixo) entra por cima, loja a loja.")
        elasticidade_pct = int(st.number_input(
            "Elasticidade (%)", -50, 200, _pct(cfg.get("elasticidade_pct", 0), 0), 5,
            help="Venda projetada × (1 + elasticidade)."))

    with st.container(border=True):
        st.markdown(_MARCA_CARD, unsafe_allow_html=True)
        st.subheader("Lojas ativas, lojas espelho e crescimento por loja")
        a, _ = st.columns([1.4, 4])
        padrao_cresc = int(a.number_input(
            "Crescimento padrão (%)", -100, 200, crescimento_padrao_pct(), 5, format="%d",
            help="Vale para toda loja sem ajuste próprio na coluna Crescimento, inclusive "
                 "loja nova que entrar depois. 0 = repete o histórico."))
        lojas_inativas, lojas_espelho, aceleracao = _card_lojas(cfg, padrao_cresc)
        if padrao_cresc == crescimento_padrao_pct() and aceleracao != aceleracao_lojas():
            with st.spinner("Salvando…"):
                salvar_aceleracao(aceleracao, padrao_pct=acel.PCT_NEUTRO + padrao_cresc)
            st.toast("Salvo: " + " · ".join(st.session_state.get("_cfg_lojas_mudancas") or
                                            ["crescimento por loja"]), icon="✅")
            st.rerun()
        b, _ = st.columns([1.8, 4])
        if b.button("Restaurar padrão das lojas", key="cfg_lojas_reset",
                    help="Todas ativas, lojas espelho do YAML e crescimento no padrão.",
                    disabled=not (cfg.get("lojas_inativas") or cfg.get("lojas_espelho")
                                  or aceleracao_lojas())):
            cfg.update(lojas_inativas=[], lojas_espelho={})
            with st.spinner("Restaurando…"):
                save_config(cfg)
                salvar_aceleracao({})
            invalidar_lojas()
            st.session_state.pop(_CHAVE_EDITOR_LOJAS, None)
            st.toast("Lojas restauradas ao padrão.", icon="✅")
            st.rerun()
        st.caption("Regras de loja espelho de partida: `config/lojas_espelho.yaml`; o que "
                   "você mudar aqui prevalece sobre o arquivo.")

    # salvamento automático: qualquer mudança vai direto para o config
    novo = {
        "reserva_cd_pct": reserva_cd_pct,
        "fim_periodo_verao": fim_verao.strip(),
        "fim_periodo_inverno": fim_inverno.strip(),
        "min_amostra_curva": int(min_amostra),
        "desde_colecao": desde_colecao,
        "elasticidade_pct": elasticidade_pct,
        "crescimento_padrao_pct": padrao_cresc,
        "lojas_inativas": lojas_inativas,
        "lojas_espelho": lojas_espelho,
    }
    cfg.setdefault("elasticidade_pct", 0)
    cfg.setdefault("crescimento_padrao_pct", 0)
    cfg.setdefault("lojas_inativas", [])
    cfg.setdefault("lojas_espelho", {})
    if any(cfg.get(k) != v for k, v in novo.items()):
        mudou_lojas = (cfg.get("lojas_inativas") != lojas_inativas
                       or cfg.get("lojas_espelho") != lojas_espelho
                       or cfg.get("crescimento_padrao_pct") != padrao_cresc)
        cfg.update(novo)
        with st.spinner("Salvando…"):
            save_config(cfg)
        detalhe = st.session_state.get("_cfg_lojas_mudancas") if mudou_lojas else None
        st.toast("Salvo: " + " · ".join(detalhe) if detalhe else "Parâmetros salvos.", icon="✅")
        if mudou_lojas:
            invalidar_lojas()
            st.rerun()   # contadores e seleções refletem o salvo

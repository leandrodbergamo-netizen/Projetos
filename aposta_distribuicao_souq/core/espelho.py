"""Seleção de espelhos e projeção de aposta a partir das bases reais.

Fluxo:
1. `preparar_produtos` enriquece o cadastro (tecido/cor/faixa).
2. `candidatos_espelho` lista produtos comparáveis (match sem data; hard =
   subgrupo+faixas+tecido; soft relaxável = cor).
3. `velocidade_por_loja_desaz` mede a velocidade do espelho **nas mesmas lojas**
   e desazonaliza pela janela em que ele vendeu.
4. `projetar_aposta` extrapola a velocidade por-loja para o parque-alvo, re-
   sazonaliza pela janela de entrada do produto novo e dimensiona a aposta.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from core.dados import datas_liquidacao, rank_colecao
from core.regra_distribuicao import reservar_cd
from core.sazonalidade import fator_janela, semanas_equivalentes
from core.taxonomia import (agrupar_cor, agrupar_material, agrupar_tamanho,
                            faixa_preco_series, normalizar_subgrupo)

# Colunas exibidas na tabela de candidatos. Manga/comprimento/fit entram como
# informação de CONSULTA (ajudam o comprador a escolher), não como filtro: o eta²
# delas sobre a velocidade é ~0 (ver docs/relevancia_variaveis.md).
COLS_EXIBE = [
    "url", "desc_item", "cod_produto", "cod_sku_pai", "desc_colecao",
    "grupo_material", "desc_cor", "cor_grupo", "faixa", "preco", "dt_envio",
    "desc_manga", "desc_comprimento", "desc_fit",
]


# --------------------------------------------------------------------------- #
# Preparação do cadastro
# --------------------------------------------------------------------------- #
def preparar_produtos(produtos: pd.DataFrame, apenas_roupa: bool = True) -> pd.DataFrame:
    """Enriquiquece o cadastro com tecido (grupo_material), cor_grupo, faixa e
    rank de coleção. Faixa depende de grupo+subgrupo+preço (arquivo oficial)."""
    df = produtos.copy()
    if apenas_roupa and "desc_linha" in df.columns:
        df = df[df["desc_linha"] == "ROUPA"]
    # grão vendável: cod_sku_pai com 5 segmentos (modelo+cor) — é o que casa com as
    # vendas. Linhas "header" (4 seg, sem tamanho) são descartadas.
    seg = df["cod_sku_pai"].astype(str).str.count(r"\.") + 1
    df = df[seg >= 5]
    # CANCELADO nunca foi produzido (98% sem venda, sem foto): não pode ser espelho.
    if "desc_status_produto" in df.columns:
        df = df[df["desc_status_produto"].astype(str).str.upper() != "CANCELADO"]
    df["desc_sub_grupo_wbg"] = df["desc_sub_grupo_wbg"].map(normalizar_subgrupo)
    df["grupo_material"] = [
        agrupar_material(g, m) for g, m in zip(df.get("desc_grupo_wgb"), df.get("desc_material"))
    ]
    df["cor_grupo"] = [agrupar_cor(c) for c in df.get("desc_cor")]
    # bucket unificado de tamanho: '36' e 'XPP' viram ambos '36|XPP'
    df["tamanho_grupo"] = df["desc_tamanho"].map(agrupar_tamanho)
    df["rank_colecao"] = df.get("desc_colecao").map(rank_colecao)
    # preço de referência: tabela, com fallback para o descontado
    df["preco"] = df["preco_tabela"]
    if "preco_descontado" in df.columns:
        df["preco"] = df["preco"].fillna(df["preco_descontado"])
    df["faixa"] = faixa_preco_series(
        df["desc_grupo_wgb"], df["desc_sub_grupo_wbg"], df["preco"]
    ).values
    # Janela full price: da entrada em loja (dt_envio + 7, premissa de lead time)
    # até entrar em liquidação. É o denominador correto da velocidade — inclui as
    # semanas em que o produto estava exposto e NÃO vendeu.
    df["dt_entrada_loja"] = pd.to_datetime(df["dt_envio"], errors="coerce") + pd.Timedelta(days=7)
    df["dt_liquidacao"] = df["cod_sku_pai"].map(datas_liquidacao())
    return df


def preparar_vendas(vendas_fp: pd.DataFrame, produtos_prep: pd.DataFrame) -> pd.DataFrame:
    """Alinha as vendas ao cadastro pela chave confiável `sk_produto`.

    Sobrescreve `cod_sku_pai` (convenção do cadastro) e anexa grupo_material,
    cor_grupo e subgrupo do produto — as bases usam formatos distintos de
    cod_sku_pai, então a junção por sk_produto é a única correta.
    """
    chave = produtos_prep.drop_duplicates("sk_produto").set_index("sk_produto")
    df = vendas_fp.copy()
    sk = df["sk_produto"]
    df["cod_sku_pai"] = sk.map(chave["cod_sku_pai"])
    df["grupo_material"] = sk.map(chave["grupo_material"])
    df["cor_grupo"] = sk.map(chave["cor_grupo"])
    if "desc_sub_grupo_wbg" in chave.columns:
        df["subgrupo"] = sk.map(chave["desc_sub_grupo_wbg"]).fillna(df.get("subgrupo"))
    return df


# --------------------------------------------------------------------------- #
# Candidatos a espelho
# --------------------------------------------------------------------------- #
def candidatos_espelho(
    produtos_prep: pd.DataFrame,
    *,
    subgrupo: str,
    grupo: Optional[str] = None,
    faixas=None,
    tecido: Optional[str] = None,
    cor_grupo=None,
    desde_colecao: float = 2022.0,
    relaxar: bool = True,
    min_candidatos: int = 5,
) -> tuple[pd.DataFrame, list[str]]:
    """Retorna (candidatos, filtros_soft_aplicados).

    Hard: subgrupo + faixas + tecido + coleção >= desde. Coleção fora do
    escopo (PERENE/ALTO VERÃO/CANCELADO) tem rank NaN e cai fora sozinha.
    - `grupo` (construção) é opcional: o tecido já separa Tricot/Jeans/planos,
      então a aba de aposta não pergunta mais a construção ao usuário.
    - `faixas`: uma faixa ("P1") ou várias (["P1","P4"]); vazio/None = todas.
      Cada produto carrega `faixa` calculada na régua da PRÓPRIA construção
      (P4 de malha ≠ P4 de tecido plano em R$) — o rótulo é o posicionamento.
    A grade de tamanhos NÃO filtra espelhos: é insumo da distribuição (colunas
    da matriz e curva de tamanhos).
    Soft (afrouxado se faltar candidato): só a cor.
    - `cor_grupo`: uma cor ou lista (vazio/None = todas).
    Manga/comprimento/fit NÃO filtram — vão na tabela como consulta.
    Data NÃO é critério (só posiciona a janela sazonal).
    """
    df = produtos_prep
    hard = df["desc_sub_grupo_wbg"] == subgrupo
    if grupo is not None:
        hard &= df["desc_grupo_wgb"] == grupo
    hard &= df["rank_colecao"] >= desde_colecao
    alvo_faixas = [faixas] if isinstance(faixas, str) else list(faixas or [])
    if alvo_faixas:
        hard &= df["faixa"].isin(alvo_faixas)
    if tecido is not None:
        hard &= df["grupo_material"] == tecido
    base = df[hard]

    if isinstance(cor_grupo, str):
        cor_grupo = [cor_grupo]
    cores = list(cor_grupo) if cor_grupo else None

    # filtros soft como máscaras nomeadas; o primeiro da lista afrouxa primeiro
    softs: list[tuple[str, pd.Series]] = []
    if cores:
        softs.append(("cor_grupo", base["cor_grupo"].isin(cores)))

    usados = [nome for nome, _ in softs]

    def aplica(nomes):
        m = pd.Series(True, index=base.index)
        for nome, mask in softs:
            if nome in nomes:
                m &= mask
        return base[m]

    cand = aplica(usados)
    while relaxar and len(cand) < min_candidatos and usados:
        usados.pop(0)  # solta o filtro soft menos relevante primeiro (cor)
        cand = aplica(usados)

    cols = [c for c in COLS_EXIBE if c in cand.columns]
    return cand[cols].drop_duplicates("cod_sku_pai"), usados


def grades_por_modelo(produtos_prep: pd.DataFrame) -> dict:
    """{cod_sku_pai: conjunto de buckets de tamanho em que o modelo existiu}."""
    if "tamanho_grupo" not in produtos_prep.columns:
        return {}
    g = produtos_prep.dropna(subset=["tamanho_grupo"]).groupby("cod_sku_pai")["tamanho_grupo"]
    return g.apply(set).to_dict()


def pool_suavizacao(
    produtos_prep: pd.DataFrame,
    *,
    subgrupo: str,
    tecido: Optional[str] = None,
    fits=None,
    desde_colecao: float = 2022.0,
) -> set:
    """Modelos do mesmo subgrupo (+ tecido, + fit) para suavizar curvas.

    A participação por loja calculada só com os espelhos escolhidos é ruidosa
    (poucos modelos); a do segmento inteiro é estável. `tecido`/`fits` None =
    todos (afrouxam o segmento). A aposta segue vindo só dos espelhos — o pool
    alimenta o rateio entre lojas e a projeção de tamanhos faltantes.
    """
    df = produtos_prep
    m = df["desc_sub_grupo_wbg"] == subgrupo
    if tecido is not None:
        m &= df["grupo_material"] == tecido
    m &= df["rank_colecao"] >= desde_colecao
    if fits and "desc_fit" in df.columns:
        m &= df["desc_fit"].isin(list(fits))
    return set(df.loc[m, "cod_sku_pai"])


def curva_tamanhos_grade(
    vendas_fp: pd.DataFrame,
    produtos_prep: pd.DataFrame,
    skus_espelhos,
    grade,
    *,
    subgrupo: str,
    tecido: Optional[str] = None,
    fits=None,
    desde_colecao: float = 2022.0,
    col_tamanho: str = "tamanho_grupo",
) -> tuple[dict[str, float], dict[str, str], list[str]]:
    """Curva de tamanhos dos espelhos reconciliada com a grade da aposta.

    (a) Tamanho vendido pelos espelhos FORA da grade é cortado; a massa dele se
        redistribui na normalização do rateio (comportamento vigente).
    (b) Tamanho da grade SEM venda nos espelhos é projetado pelo segmento, do
        pool mais específico ao mais frouxo: subgrupo+tecido+fit →
        subgrupo+tecido → subgrupo. A calibração usa os tamanhos em comum —
        `escala = Σ curva[comuns] / Σ pool[comuns]` — para enxertar a proporção
        do pool na massa dos espelhos. Sem pool com o tamanho: piso = menor
        peso presente ÷ 2 (nunca zera um tamanho pedido).
    Espelhos sem venda em nenhum tamanho da grade → a curva do primeiro pool
    que cobrir entra direto (escala 1).
    Retorna (curva na ordem da grade, origem por tamanho, avisos). Origens:
    "espelhos" | "pool_fit" | "pool_tecido" | "pool_subgrupo" | "piso".
    """
    from core.dados import curva_tamanhos

    grade = list(grade or [])
    skus = set(skus_espelhos)
    bruta = curva_tamanhos(vendas_fp[vendas_fp["cod_sku_pai"].isin(skus)],
                           produtos_prep, col_tamanho=col_tamanho)
    if not grade:
        return bruta, {t: "espelhos" for t in bruta}, []

    curva = {t: bruta[t] for t in grade if bruta.get(t, 0) > 0}
    origem = {t: "espelhos" for t in curva}
    faltantes = [t for t in grade if t not in curva]

    niveis = []
    if fits:
        niveis.append(("pool_fit", {"tecido": tecido, "fits": fits}))
    if tecido is not None:
        niveis.append(("pool_tecido", {"tecido": tecido}))
    niveis.append(("pool_subgrupo", {}))

    for nome, kw in niveis:
        if not faltantes:
            break
        pool = pool_suavizacao(produtos_prep, subgrupo=subgrupo,
                               desde_colecao=desde_colecao, **kw)
        cpool = curva_tamanhos(vendas_fp[vendas_fp["cod_sku_pai"].isin(pool)],
                               produtos_prep, col_tamanho=col_tamanho)
        cpool = {t: p for t, p in cpool.items() if t in set(grade) and p > 0}
        if not cpool:
            continue
        comuns = [t for t in curva if t in cpool]
        if curva and not comuns:
            continue   # sem interseção não há como calibrar este nível
        escala = (sum(curva[t] for t in comuns) / sum(cpool[t] for t in comuns)) \
            if comuns else 1.0
        for t in [t for t in faltantes if t in cpool]:
            curva[t] = cpool[t] * escala
            origem[t] = nome
        faltantes = [t for t in faltantes if t not in curva]

    if faltantes:
        piso = min(curva.values()) / 2 if curva else 1.0
        for t in faltantes:
            curva[t] = piso
            origem[t] = "piso"

    curva = {t: curva[t] for t in grade}
    origem = {t: origem[t] for t in grade}

    avisos = []
    rotulos = {"pool_fit": "do segmento subgrupo+tecido+fit",
               "pool_tecido": "do segmento subgrupo+tecido",
               "pool_subgrupo": "do segmento do subgrupo"}
    for nome, rotulo in rotulos.items():
        tams = [t for t in grade if origem[t] == nome]
        if tams:
            avisos.append(f"Tamanho(s) {', '.join(tams)} sem venda nos espelhos: "
                          f"projetado(s) {rotulo}.")
    tams_piso = [t for t in grade if origem[t] == "piso"]
    if tams_piso:
        avisos.append(f"Tamanho(s) {', '.join(tams_piso)} sem histórico no segmento: "
                      "piso estatístico (menor peso ÷ 2).")
    return curva, origem, avisos


def janelas_full_price(produtos_prep: pd.DataFrame) -> dict:
    """{cod_sku_pai: (entrada em loja, entrada em liquidação)}.

    Qualquer ponta pode ser NaT: sem dt_envio, a velocidade usa a 1ª venda; sem
    liquidação (produto ainda a full price), usa a última venda.
    """
    cols = ["cod_sku_pai", "dt_entrada_loja", "dt_liquidacao"]
    if not all(c in produtos_prep.columns for c in cols):
        return {}
    d = produtos_prep[cols].drop_duplicates("cod_sku_pai")
    return {r.cod_sku_pai: (r.dt_entrada_loja, r.dt_liquidacao) for r in d.itertuples()}


def enriquecer_velocidade(
    candidatos: pd.DataFrame, vendas_fp: pd.DataFrame, curva: pd.DataFrame,
    ecom_locs: Optional[set] = None, apenas_com_venda: bool = True,
    janelas: Optional[dict] = None, ativo_ate=None, dias_ativo: int = 60,
) -> pd.DataFrame:
    """Anexa unidades/lojas/velocidade desazonalizada a cada candidato e ordena
    por unidades (mais vendidos primeiro).

    `apenas_com_venda` descarta quem nunca vendeu full price no escopo: sem
    histórico não há velocidade para projetar, então não serve como espelho
    (são, em geral, cadastros que nunca chegaram à loja).
    """
    janelas = janelas or {}
    linhas = []
    for sku in candidatos["cod_sku_pai"]:
        ve = velocidade_por_loja_desaz(vendas_fp, sku, curva, ecom_locs,
                                       janela=janelas.get(sku), ativo_ate=ativo_ate,
                                       dias_ativo=dias_ativo)
        linhas.append({
            "cod_sku_pai": sku,
            "unidades": ve.unidades if ve else 0,
            "n_lojas": ve.n_lojas if ve else 0,
            "semanas_fp": round(ve.semanas_ativas, 1) if ve else 0.0,
            "vel_loja_desaz": round(ve.vel_por_loja_desaz, 3) if ve else 0.0,
        })
    vel = pd.DataFrame(linhas)
    out = candidatos.merge(vel, on="cod_sku_pai", how="left")
    if apenas_com_venda:
        out = out[out["unidades"] > 0]
    return out.sort_values("unidades", ascending=False, ignore_index=True)


# --------------------------------------------------------------------------- #
# Velocidade desazonalizada do espelho (mesmas lojas)
# --------------------------------------------------------------------------- #
@dataclass
class VelocidadeEspelho:
    cod_sku_pai: str
    unidades: int                # total (físico + ecom)
    unidades_ecom: int
    n_lojas: int                 # lojas FÍSICAS onde o espelho vendeu ("mesmas lojas")
    semanas_ativas: float
    fator_janela: float          # índice médio da janela (100=neutro)
    vel_por_loja_desaz: float    # velocidade FÍSICA por loja, desazonalizada
    vel_ecom_desaz: float        # velocidade do Ecom (nó único), desazonalizada


def velocidade_por_loja_desaz(
    vendas_fp: pd.DataFrame, cod_sku_pai: str, curva: pd.DataFrame,
    ecom_locs: Optional[set] = None, col_loja: str = "sk_localidade",
    janela: Optional[tuple] = None, ativo_ate=None, dias_ativo: int = 60,
) -> Optional[VelocidadeEspelho]:
    """Velocidade desazonalizada de um espelho, separando física (por loja) e Ecom.

    Física escala com a frota (por-loja × nº de lojas); Ecom é um nó fixo que não
    escala. Ambas normalizadas para a semana média pela curva sazonal.

    `janela` = (entrada em loja, entrada em liquidação). Quando informada, ela
    **alarga** o período considerado: as semanas em que o produto estava exposto e
    **não** vendeu passam a entrar no denominador (sem ela, "da primeira à última
    venda" infla a velocidade de quem vendeu e parou).

    A janela nunca encurta o período nem descarta venda: se houve venda full price
    antes da entrada presumida (o `dt_envio + 7` é premissa) ou depois da
    liquidação (o status é do catálogo, a flag é da transação), vale a venda real.

    `ativo_ate` (hoje) fecha a janela dos produtos **sem** data de liquidação que
    ainda estão vendendo — 97% da safra corrente vendeu nos últimos 60 dias e
    segue a full price, então a janela vai até hoje (incluindo as semanas paradas).
    Quem não vende há mais de `dias_ativo` já saiu de circulação sem registro de
    liquidação: para esse, a janela para na última venda, senão a velocidade seria
    diluída por anos de prateleira que não existiram.
    """
    if vendas_fp.empty or "cod_sku_pai" not in vendas_fp.columns:
        return None
    sub = vendas_fp[vendas_fp["cod_sku_pai"] == cod_sku_pai].dropna(subset=["dt_transacao"])
    if sub.empty:
        return None

    dt0, dt1 = sub["dt_transacao"].min(), sub["dt_transacao"].max()
    tem_liquidacao = False
    if janela:
        ini, fim = janela
        if ini is not None and pd.notna(ini):
            dt0 = min(dt0, pd.Timestamp(ini))
        if fim is not None and pd.notna(fim):
            dt1 = max(dt1, pd.Timestamp(fim))
            tem_liquidacao = True
    if not tem_liquidacao and ativo_ate is not None:
        hoje = pd.Timestamp(ativo_ate)
        if (hoje - dt1).days <= dias_ativo:   # ainda vendendo => segue a full price
            dt1 = hoje

    ecom_locs = ecom_locs or set()
    is_ecom = sub[col_loja].isin(ecom_locs)
    fis, eco = sub[~is_ecom], sub[is_ecom]

    unid = int(sub["qtd_produto"].sum())
    unid_ecom = int(eco["qtd_produto"].sum())
    semanas = max((dt1 - dt0).days / 7 + 1, 1.0)
    n_lojas = int(fis[col_loja].nunique())
    f = fator_janela(curva, dt0, dt1) / 100.0
    if unid <= 0 or (n_lojas == 0 and unid_ecom == 0):
        return None

    vel_fis = (fis["qtd_produto"].sum() / semanas / n_lojas) if n_lojas else 0.0
    vel_eco = unid_ecom / semanas
    desaz = (lambda x: x / f) if f > 0 else (lambda x: x)
    return VelocidadeEspelho(
        cod_sku_pai=cod_sku_pai, unidades=unid, unidades_ecom=unid_ecom, n_lojas=n_lojas,
        semanas_ativas=semanas, fator_janela=f * 100.0,
        vel_por_loja_desaz=desaz(vel_fis), vel_ecom_desaz=desaz(vel_eco),
    )


def velocidade_de_cada_loja(
    vendas_fp: pd.DataFrame, cod_sku_pais: list, curva: pd.DataFrame,
    ecom_locs: Optional[set] = None, col_loja: str = "sk_localidade",
) -> dict:
    """Velocidade semanal desazonalizada **de cada loja** para os espelhos dados.

    Alimenta o teto de cobertura da distribuição: cada loja não pode receber
    mais que N semanas da sua própria velocidade. Lojas sem histórico dos
    espelhos ficam de fora do dict (o chamador decide o fallback).
    """
    sub = vendas_fp[vendas_fp["cod_sku_pai"].isin(cod_sku_pais)].dropna(subset=["dt_transacao"])
    if ecom_locs:
        sub = sub[~sub[col_loja].isin(ecom_locs)]
    if sub.empty:
        return {}
    fator = fator_janela(curva, sub["dt_transacao"].min(), sub["dt_transacao"].max()) / 100.0
    saida = {}
    for loja, g in sub.groupby(col_loja):
        dt0, dt1 = g["dt_transacao"].min(), g["dt_transacao"].max()
        semanas = max((dt1 - dt0).days / 7 + 1, 1.0)
        vel = g["qtd_produto"].sum() / semanas
        saida[str(float(loja))] = vel / fator if fator > 0 else vel
    return saida


# --------------------------------------------------------------------------- #
# Projeção da aposta
# --------------------------------------------------------------------------- #
@dataclass
class ApostaProjetada:
    vel_por_loja_desaz: float      # média ponderada dos espelhos (físico, unid/loja/semana)
    vel_ecom_desaz: float          # média ponderada (Ecom)
    n_lojas_alvo: int
    semanas_equivalentes: float
    venda_projetada: float         # total (físico + ecom)
    venda_ecom: float
    aposta_sugerida: float
    reserva_cd: float
    disponivel_lojas: float
    espelhos: list = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


def projetar_aposta(
    velocidades: list[VelocidadeEspelho],
    curva: pd.DataFrame,
    dt_entrada,
    n_lojas_alvo: int,
    *,
    horizonte_semanas: int = 12,
    aproveitamento: float = 0.70,
    reserva_cd_pct: float = 0.20,
    pesos: Optional[dict] = None,
) -> ApostaProjetada:
    """Dimensiona a aposta a partir dos espelhos selecionados.

    venda_projetada = vel_por_loja_desaz(média) × n_lojas_alvo × semanas_equiv.
    A extrapolação para lojas novas está no fator `n_lojas_alvo` (parque atual);
    a sazonalidade da janela de entrada, em `semanas_equivalentes`.
    """
    avisos: list[str] = []
    vs = [v for v in velocidades if v is not None]
    if not vs:
        raise ValueError("Nenhum espelho com histórico de venda para projetar.")
    pesos = pesos or {v.cod_sku_pai: 1.0 for v in vs}
    tot_peso = sum(pesos.get(v.cod_sku_pai, 1.0) for v in vs)
    vel_fis = sum(v.vel_por_loja_desaz * pesos.get(v.cod_sku_pai, 1.0) for v in vs) / tot_peso
    vel_eco = sum(v.vel_ecom_desaz * pesos.get(v.cod_sku_pai, 1.0) for v in vs) / tot_peso

    eqw = semanas_equivalentes(curva, dt_entrada, horizonte_semanas)
    venda_ecom = vel_eco * eqw
    venda = vel_fis * n_lojas_alvo * eqw + venda_ecom   # físico extrapolado + Ecom
    aposta = venda / aproveitamento if aproveitamento > 0 else venda
    reserva, disp = reservar_cd(aposta, reserva_cd_pct)

    if venda_ecom > 0:
        avisos.append(f"Inclui demanda de Ecom (~{venda_ecom:.0f} un) na aposta; Ecom não recebe na matriz física.")

    return ApostaProjetada(
        vel_por_loja_desaz=vel_fis, vel_ecom_desaz=vel_eco, n_lojas_alvo=n_lojas_alvo,
        semanas_equivalentes=eqw, venda_projetada=venda, venda_ecom=venda_ecom,
        aposta_sugerida=aposta, reserva_cd=reserva, disponivel_lojas=disp,
        espelhos=vs, avisos=avisos,
    )

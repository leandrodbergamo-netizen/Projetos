"""Seleção de espelhos e projeção de aposta a partir das bases reais.

Fluxo:
1. `preparar_produtos` enriquece o cadastro (tecido/cor/faixa).
2. `candidatos_espelho` lista produtos comparáveis (match sem data; hard =
   subgrupo+grupo+faixa+tecido; soft relaxável = cor/manga/comprimento/fit).
3. `velocidade_por_loja_desaz` mede a velocidade do espelho **nas mesmas lojas**
   e desazonaliza pela janela em que ele vendeu.
4. `projetar_aposta` extrapola a velocidade por-loja para o parque-alvo, re-
   sazonaliza pela janela de entrada do produto novo e dimensiona a aposta.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from core.dados import rank_colecao
from core.regra_distribuicao import reservar_cd
from core.sazonalidade import fator_janela, semanas_equivalentes
from core.taxonomia import agrupar_cor, agrupar_material, faixa_preco_series

# Colunas exibidas na tabela de candidatos. Manga/comprimento/fit entram como
# informação de CONSULTA (ajudam o comprador a escolher), não como filtro: o eta²
# delas sobre a velocidade é ~0 (ver docs/relevancia_variaveis.md).
COLS_EXIBE = [
    "url", "desc_item", "cod_produto", "cod_sku_pai", "desc_colecao",
    "grupo_material", "desc_cor", "cor_grupo", "faixa", "preco",
    "desc_manga", "desc_comprimento", "desc_fit",
]
# Único filtro afrouxável: cor é a variável mais preditiva (eta² 0,09).
SOFT_PADRAO = ["cor_grupo"]


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
    df["grupo_material"] = [
        agrupar_material(g, m) for g, m in zip(df.get("desc_grupo_wgb"), df.get("desc_material"))
    ]
    df["cor_grupo"] = [agrupar_cor(c) for c in df.get("desc_cor")]
    df["rank_colecao"] = df.get("desc_colecao").map(rank_colecao)
    # preço de referência: tabela, com fallback para o descontado
    df["preco"] = df["preco_tabela"]
    if "preco_descontado" in df.columns:
        df["preco"] = df["preco"].fillna(df["preco_descontado"])
    df["faixa"] = faixa_preco_series(
        df["desc_grupo_wgb"], df["desc_sub_grupo_wbg"], df["preco"]
    ).values
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
    grupo: str,
    faixa: Optional[str] = None,
    tecido: Optional[str] = None,
    cor_grupo: Optional[str] = None,
    desde_colecao: float = 2022.0,
    relaxar: bool = True,
    min_candidatos: int = 5,
    soft_ordem: Optional[list[str]] = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Retorna (candidatos, filtros_soft_aplicados).

    Hard: subgrupo + grupo + faixa + tecido + coleção >= desde. Coleção fora do
    escopo (PERENE/ALTO VERÃO/CANCELADO) tem rank NaN e cai fora sozinha.
    Soft: apenas cor, afrouxada se sobrarem menos de `min_candidatos`.
    Manga/comprimento/fit NÃO filtram — vão na tabela como consulta.
    Data NÃO é critério (só posiciona a janela sazonal).
    """
    df = produtos_prep
    hard = (df["desc_sub_grupo_wbg"] == subgrupo) & (df["desc_grupo_wgb"] == grupo)
    hard &= df["rank_colecao"] >= desde_colecao
    if faixa is not None:
        hard &= df["faixa"] == faixa
    if tecido is not None:
        hard &= df["grupo_material"] == tecido
    base = df[hard]

    soft_vals = {"cor_grupo": cor_grupo}
    ativos = [c for c in (soft_ordem or SOFT_PADRAO) if soft_vals.get(c) is not None and c in base.columns]

    def aplica(cols):
        m = pd.Series(True, index=base.index)
        for c in cols:
            m &= base[c] == soft_vals[c]
        return base[m]

    usados = list(ativos)
    cand = aplica(usados)
    while relaxar and len(cand) < min_candidatos and usados:
        usados.pop(0)  # solta o filtro soft menos relevante
        cand = aplica(usados)

    cols = [c for c in COLS_EXIBE if c in cand.columns]
    return cand[cols].drop_duplicates("cod_sku_pai"), usados


def enriquecer_velocidade(
    candidatos: pd.DataFrame, vendas_fp: pd.DataFrame, curva: pd.DataFrame,
    ecom_locs: Optional[set] = None,
) -> pd.DataFrame:
    """Anexa unidades/lojas/velocidade desazonalizada a cada candidato e ordena
    por unidades (mais vendidos primeiro). Candidato sem venda vai com 0."""
    linhas = []
    for sku in candidatos["cod_sku_pai"]:
        ve = velocidade_por_loja_desaz(vendas_fp, sku, curva, ecom_locs)
        linhas.append({
            "cod_sku_pai": sku,
            "unidades": ve.unidades if ve else 0,
            "n_lojas": ve.n_lojas if ve else 0,
            "vel_loja_desaz": round(ve.vel_por_loja_desaz, 3) if ve else 0.0,
        })
    vel = pd.DataFrame(linhas)
    out = candidatos.merge(vel, on="cod_sku_pai", how="left")
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
) -> Optional[VelocidadeEspelho]:
    """Velocidade desazonalizada de um espelho, separando física (por loja) e Ecom.

    Física escala com a frota (por-loja × nº de lojas); Ecom é um nó fixo que não
    escala. Ambas medidas nas "mesmas lojas" (janela em que o espelho vendeu) e
    normalizadas para a semana média pela curva sazonal.
    """
    if vendas_fp.empty or "cod_sku_pai" not in vendas_fp.columns:
        return None
    sub = vendas_fp[vendas_fp["cod_sku_pai"] == cod_sku_pai].dropna(subset=["dt_transacao"])
    if sub.empty:
        return None
    ecom_locs = ecom_locs or set()
    is_ecom = sub[col_loja].isin(ecom_locs)
    fis, eco = sub[~is_ecom], sub[is_ecom]

    unid = int(sub["qtd_produto"].sum())
    unid_ecom = int(eco["qtd_produto"].sum())
    dt0, dt1 = sub["dt_transacao"].min(), sub["dt_transacao"].max()
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
    moq: Optional[int] = None
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
    moq: Optional[int] = None,
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

    if moq is not None and aposta < moq:
        avisos.append(f"Aposta sugerida ({aposta:.0f}) abaixo do MOQ ({moq}). Avaliar pedido mínimo.")
    if venda_ecom > 0:
        avisos.append(f"Inclui demanda de Ecom (~{venda_ecom:.0f} un) na aposta; Ecom não recebe na matriz física.")

    return ApostaProjetada(
        vel_por_loja_desaz=vel_fis, vel_ecom_desaz=vel_eco, n_lojas_alvo=n_lojas_alvo,
        semanas_equivalentes=eqw, venda_projetada=venda, venda_ecom=venda_ecom,
        aposta_sugerida=aposta, reserva_cd=reserva, disponivel_lojas=disp,
        moq=moq, espelhos=vs, avisos=avisos,
    )

"""Taxonomia: agrupamento de matéria-prima (tecido), cor e faixa de preço.

Funções puras (sem estado global além de caches de leitura) para classificar
produtos da linha ROUPA/Souq. Os de-para de material e cor ficam em
`config/material_grupos.yaml` e `config/cor_grupos.yaml` (validáveis em reunião).
A faixa de preço vem do arquivo oficial "Faixas de Preço ROUPA".
"""
from __future__ import annotations

import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

from core.dados import dados_dir

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


# --------------------------------------------------------------------------- #
# Normalização
# --------------------------------------------------------------------------- #
def norm(s) -> str:
    """Maiúsculas, sem acento, espaços colapsados. None/NaN -> ''."""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return " ".join(s.upper().split())


# --------------------------------------------------------------------------- #
# Configs de agrupamento (cacheadas)
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def _cfg_material() -> dict:
    with (CONFIG_DIR / "material_grupos.yaml").open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache(maxsize=1)
def _cfg_cor() -> dict:
    with (CONFIG_DIR / "cor_grupos.yaml").open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache(maxsize=1)
def _cfg_subgrupo() -> dict:
    caminho = CONFIG_DIR / "subgrupos.yaml"
    if not caminho.exists():
        return {"sinonimos": {}}
    with caminho.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {"sinonimos": {}}


def _primeira_ocorrencia(texto: str, mapa: dict) -> Optional[str]:
    """Retorna o bucket da 1a chave (por posição) encontrada em `texto`."""
    achou, pos_min = None, None
    for kw, bucket in mapa.items():
        i = texto.find(kw)
        if i >= 0 and (pos_min is None or i < pos_min):
            pos_min, achou = i, bucket
    return achou


# --------------------------------------------------------------------------- #
# Subgrupo
# --------------------------------------------------------------------------- #
def normalizar_subgrupo(desc_sub_grupo_wbg):
    """Limpa espaços extras e resolve sinônimos do subgrupo.

    O cadastro tem 'JAQUETA ' e 'JAQUETA' (e 'BODY '/'BODY') como valores
    distintos, o que duplicava a opção na tela; e 'SHORTS' convive com 'SHORT'.
    Preserva acento e caixa do valor exibido (CALÇA continua CALÇA).
    """
    if not isinstance(desc_sub_grupo_wbg, str):
        return desc_sub_grupo_wbg
    limpo = " ".join(desc_sub_grupo_wbg.split())
    sinonimos = {norm(k): v for k, v in (_cfg_subgrupo().get("sinonimos") or {}).items()}
    return sinonimos.get(norm(limpo), limpo)


# --------------------------------------------------------------------------- #
# Tamanho (unifica grade em letra e numerária)
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def _cfg_tamanho() -> dict:
    caminho = CONFIG_DIR / "tamanhos.yaml"
    if not caminho.exists():
        return {"ordem": [], "mapa": {}}
    with caminho.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {"ordem": [], "mapa": {}}


def agrupar_tamanho(desc_tamanho) -> Optional[str]:
    """Bucket unificado do tamanho: '36' e 'XPP' caem ambos em '36|XPP'."""
    t = norm(desc_tamanho)
    if not t:
        return None
    mapa = {norm(k): v for k, v in _cfg_tamanho()["mapa"].items()}
    return mapa.get(t)


def ordem_tamanhos() -> list[str]:
    """Buckets de tamanho na ordem de exibição (menor -> maior; U ao final)."""
    return list(_cfg_tamanho()["ordem"])


def rotulo_grade(buckets) -> str:
    """Rótulo compacto de uma grade: contígua vira 'PP–GG'; senão lista tudo."""
    ordem = ordem_tamanhos()
    presentes = [b for b in ordem if b in set(buckets or [])]
    if not presentes:
        return "—"
    curto = [b.split("|")[-1] for b in presentes]
    idx = [ordem.index(b) for b in presentes]
    if idx == list(range(idx[0], idx[-1] + 1)) and len(presentes) > 1:
        return f"{curto[0]}–{curto[-1]}"
    return "/".join(curto)


# --------------------------------------------------------------------------- #
# Material (tecido)
# --------------------------------------------------------------------------- #
def agrupar_material(desc_grupo_wgb, desc_material) -> str:
    """Classifica a matéria-prima predominante do produto.

    Ordem: grupo TRICOT/JEANS -> "linho" -> 1a fibra citada -> fornecedor com
    composição informada -> termo de tecelagem pesquisado -> Outros.

    Fibra explícita no texto vence tudo. Fornecedor vem antes de tecelagem porque
    composição real vence inferência genérica (ex.: "CROCHE ZOE - BETA" é
    Poliéster pela composição da Beta, não Algodão pela regra do crochê).
    """
    cfg = _cfg_material()
    g, m = norm(desc_grupo_wgb), norm(desc_material)
    if "TRICOT" in g:
        return "Tricot"
    if "JEANS" in g:
        return "Jeans"
    if not m:
        return cfg["bucket_indefinido"]
    if "LINHO" in m:
        return "Linho"
    return (
        _primeira_ocorrencia(m, cfg["fibras"])
        or _primeira_ocorrencia(m, cfg.get("fornecedores") or {})
        or _primeira_ocorrencia(m, cfg["tecelagens"])
        or cfg["bucket_indefinido"]
    )


# --------------------------------------------------------------------------- #
# Cor
# --------------------------------------------------------------------------- #
_QUALIFICADORES = {"CLARO", "CLARA", "ESCURO", "ESCURA", "MEDIO", "MEDIA"}


def agrupar_cor(desc_cor) -> str:
    """Agrupa a cor conforme o de-para.

    1) match exato; 2) remove qualificador claro/escuro/médio e re-tenta;
    3) usa a cor-base do 1º token; 4) mantém a própria cor (Title case).
    O match exato tem prioridade para preservar exceções (ex.: AZUL MARINHO).
    """
    cfg = _cfg_cor()
    c = norm(desc_cor)
    if not c:
        return cfg["bucket_indefinido"]
    mapa = {norm(k): v for k, v in cfg["mapa"].items()}
    if c in mapa:
        return mapa[c]
    toks = [t for t in c.split() if t not in _QUALIFICADORES]
    base = " ".join(toks)
    if base in mapa:
        return mapa[base]
    if toks and toks[0] in mapa:
        return mapa[toks[0]]
    return str(desc_cor).strip().title()


# --------------------------------------------------------------------------- #
# Faixa de preço (arquivo oficial)
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def _tabela_faixas(caminho: Optional[str] = None) -> pd.DataFrame:
    """Faixas de preço já normalizadas. Na nuvem vem da tabela publicada."""
    from core import fonte

    if fonte.usa_supabase():
        return fonte.ler_tabela("faixas")

    base = dados_dir(caminho)
    arqs = sorted(base.glob("Faixas de Pre*.xlsx"))
    if not arqs:
        return pd.DataFrame(columns=["grupo", "subgrupo", "faixa", "moq", "de", "ate",
                                     "grupo_n", "subgrupo_n"])
    df = pd.read_excel(arqs[-1], sheet_name=0)  # aba revisada (1a)
    ren = {
        "Grupo": "grupo", "Subgrupo": "subgrupo", "Faixa de Preço": "faixa",
        "Faixa de Preço": "faixa", "MOQ": "moq", "De": "de", "Até": "ate", "Até": "ate",
    }
    df = df.rename(columns=ren)
    df["grupo_n"] = df["grupo"].map(norm)
    df["subgrupo_n"] = df["subgrupo"].map(norm)
    for c in ("de", "ate", "moq"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def faixa_preco(grupo, subgrupo, preco: float, caminho: Optional[str] = None) -> dict:
    """Faixa de preço (P1..P4) para (grupo, subgrupo, preço) segundo o arquivo.

    Retorna {faixa, moq, de, ate, encontrada}. Preço abaixo do menor 'De' cai na
    menor faixa; acima do maior 'Até', na maior. Sem linhas p/ grupo+subgrupo =>
    encontrada=False.
    """
    df = _tabela_faixas(caminho)
    sub = df[(df["grupo_n"] == norm(grupo)) & (df["subgrupo_n"] == norm(subgrupo))]
    sub = sub.dropna(subset=["de", "ate"]).sort_values("de")
    if sub.empty:
        return {"faixa": None, "moq": None, "de": None, "ate": None, "encontrada": False}
    linha = sub[(sub["de"] <= preco) & (preco <= sub["ate"])]
    if linha.empty:
        # clamp: abaixo do mínimo -> 1a faixa; acima do máximo -> última
        linha = sub.iloc[[0]] if preco < sub["de"].iloc[0] else sub.iloc[[-1]]
    r = linha.iloc[0]
    return {
        "faixa": r["faixa"], "moq": None if pd.isna(r["moq"]) else int(r["moq"]),
        "de": float(r["de"]), "ate": float(r["ate"]), "encontrada": True,
    }


def faixa_preco_series(grupos, subgrupos, precos, caminho: Optional[str] = None) -> pd.Series:
    """Versão vetorizada de `faixa_preco`: retorna a Série de faixas (P1..P4).

    Faz merge (grupo, subgrupo) e seleciona a linha cujo [de, ate] contém o preço;
    fora de qualquer faixa faz clamp na menor/maior. Muito mais rápido que iterar.
    """
    faixas = _tabela_faixas(caminho).dropna(subset=["de", "ate"])
    prod = pd.DataFrame({
        "_i": range(len(grupos)),
        "grupo_n": pd.Series(grupos).map(norm).values,
        "subgrupo_n": pd.Series(subgrupos).map(norm).values,
        "preco": pd.to_numeric(pd.Series(precos), errors="coerce").values,
    })
    if faixas.empty:
        return pd.Series([None] * len(prod), index=range(len(prod)))
    m = prod.merge(faixas[["grupo_n", "subgrupo_n", "faixa", "de", "ate"]],
                   on=["grupo_n", "subgrupo_n"], how="left")
    dentro = (m["preco"] >= m["de"]) & (m["preco"] <= m["ate"])
    # faixa exata quando dentro; senão clamp (menor de / maior ate) por produto
    m["_dist"] = 0.0
    fora = ~dentro & m["de"].notna()
    m.loc[fora, "_dist"] = (m.loc[fora, "de"] - m.loc[fora, "preco"]).abs().combine(
        (m.loc[fora, "preco"] - m.loc[fora, "ate"]).abs(), min)
    m["_rank"] = (~dentro).astype(int)  # 0 = dentro tem prioridade
    m = m.sort_values(["_i", "_rank", "_dist"])
    escolha = m.dropna(subset=["faixa"]).groupby("_i").first()["faixa"]
    return escolha.reindex(range(len(prod)))


# --------------------------------------------------------------------------- #
# Aplicação em DataFrame
# --------------------------------------------------------------------------- #
def classificar_produtos(produtos: pd.DataFrame) -> pd.DataFrame:
    """Adiciona colunas `grupo_material` e `cor_grupo` ao cadastro de produtos."""
    df = produtos.copy()
    df["grupo_material"] = [
        agrupar_material(g, m) for g, m in zip(df.get("desc_grupo_wgb"), df.get("desc_material"))
    ]
    df["cor_grupo"] = [agrupar_cor(c) for c in df.get("desc_cor")]
    return df

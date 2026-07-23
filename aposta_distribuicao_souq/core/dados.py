"""Camada de acesso e normalização das bases da Roupa.

Separa I/O (leitura de Excel, cache) das transformações de negócio (funções
puras sobre DataFrames, testáveis com dados sintéticos).

As bases ficam FORA do projeto, em `../dados` por padrão (configurável via
variável de ambiente APOSTA_DADOS_DIR ou parâmetro `caminho_dados` no config).
Excel é lento; após a 1ª leitura cacheia em parquet dentro de `.cache_dados/`.

Definições de negócio adotadas (documentadas; ajustáveis por parâmetro):
- Full price  = `flag_liquidacao == 0`.
- Vendas reais = `tipo_venda == 'venda'` (exclui 'troca'/devolução, qtd negativa).
- Velocidade  = unidades full price / semanas ativas (1ª à última venda FP).
"""
from __future__ import annotations

import math
import os
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

PROJ_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJ_ROOT / ".cache_dados"

ANOS_DISPONIVEIS = (2022, 2023, 2024, 2025, 2026)


# --------------------------------------------------------------------------- #
# Localização das bases
# --------------------------------------------------------------------------- #
def dados_dir(caminho: Optional[str] = None) -> Path:
    """Resolve a pasta de dados. Prioridade: arg > env > ../dados."""
    p = caminho or os.environ.get("APOSTA_DADOS_DIR") or (PROJ_ROOT.parent / "dados")
    return Path(p)


# --------------------------------------------------------------------------- #
# Cache parquet
# --------------------------------------------------------------------------- #
def _cache_parquet(nome: str, builder, forcar: bool = False) -> pd.DataFrame:
    CACHE_DIR.mkdir(exist_ok=True)
    destino = CACHE_DIR / f"{nome}.parquet"
    if destino.exists() and not forcar:
        return pd.read_parquet(destino)
    df = builder()
    try:
        df.to_parquet(destino, index=False)
    except Exception:
        pass  # cache é otimização; falha ao gravar não deve quebrar o app
    return df


# --------------------------------------------------------------------------- #
# Loaders (I/O)
# --------------------------------------------------------------------------- #
def carregar_produtos(caminho: Optional[str] = None, forcar: bool = False) -> pd.DataFrame:
    def build():
        p = dados_dir(caminho) / "Base_Produtos.xlsx"
        return pd.read_excel(p, sheet_name="Consulta1")

    return _cache_parquet("produtos", build, forcar)


def carregar_lojas(caminho: Optional[str] = None, forcar: bool = False) -> pd.DataFrame:
    """Cadastro de lojas. Na nuvem vem da tabela publicada (não há Excel lá)."""
    from core import fonte

    if fonte.usa_supabase():
        return fonte.ler_tabela("lojas")

    def build():
        p = dados_dir(caminho) / "Base_Lojas.xlsx"
        return pd.read_excel(p, sheet_name="Lojas")

    return _cache_parquet("lojas", build, forcar)


def carregar_status_produto(caminho: Optional[str] = None, forcar: bool = False) -> pd.DataFrame:
    """Log de mudanças de status do produto (quem mudou, quando, de/para).

    É o que permite saber **quando cada produto entrou em liquidação** e, com
    isso, fechar a janela em que ele esteve de fato a full price.
    """
    def build():
        base = dados_dir(caminho)
        arqs = sorted(base.glob("Base Status Produto*.xlsx"))
        if not arqs:
            return pd.DataFrame(columns=["Modelo", "Novo valor", "Data"])
        df = pd.read_excel(arqs[-1], sheet_name=0)
        df["Data"] = pd.to_datetime(df["Data"], errors="coerce")
        return df

    return _cache_parquet("status_produto", build, forcar)


def datas_liquidacao(caminho: Optional[str] = None) -> pd.Series:
    """Primeira data em que cada modelo (cod_sku_pai) entrou em LIQUIDAÇÃO.

    Índice = cod_sku_pai. Um produto pode entrar/sair de liquidação mais de uma
    vez; o que encerra a janela full price é a **primeira** entrada.
    """
    df = carregar_status_produto(caminho)
    if df.empty or "Novo valor" not in df.columns:
        return pd.Series(dtype="datetime64[ns]")
    liq = df[df["Novo valor"].astype(str).str.upper().str.startswith("LIQUIDA")]
    liq = liq.dropna(subset=["Modelo", "Data"])
    return liq.groupby("Modelo")["Data"].min()


def carregar_estoque(caminho: Optional[str] = None, forcar: bool = False) -> pd.DataFrame:
    def build():
        p = dados_dir(caminho) / "Base_Estoque.xlsx"
        return pd.read_excel(p, sheet_name="Consulta1")

    return _cache_parquet("estoque", build, forcar)


def carregar_vendas(
    anos: Optional[Iterable[int]] = None,
    caminho: Optional[str] = None,
    forcar: bool = False,
) -> pd.DataFrame:
    """Concatena as bases de vendas dos anos pedidos (default: todos)."""
    anos = tuple(anos) if anos else ANOS_DISPONIVEIS
    nome = "vendas_" + "_".join(str(a) for a in anos)

    def build():
        base = dados_dir(caminho)
        partes = []
        for ano in anos:
            arq = base / f"Base_{ano}.xlsx"
            if arq.exists():
                partes.append(pd.read_excel(arq, sheet_name="Base_Vendas"))
        if not partes:
            return pd.DataFrame()
        df = pd.concat(partes, ignore_index=True)
        df["dt_transacao"] = pd.to_datetime(df["dt_transacao"], errors="coerce")
        return df

    return _cache_parquet(nome, build, forcar)


# --------------------------------------------------------------------------- #
# Transformações puras (testáveis sem I/O)
# --------------------------------------------------------------------------- #
def filtrar_full_price(
    vendas: pd.DataFrame,
    linhas: Optional[Iterable[str]] = ("ROUPA",),
    canais: Optional[Iterable[int]] = None,
) -> pd.DataFrame:
    """Mantém apenas vendas full price reais (exclui liquidação e trocas).

    `linhas`=None não filtra por linha; `canais`=None não filtra por canal.
    """
    df = vendas
    df = df[df["flag_liquidacao"] == 0]
    df = df[df["tipo_venda"] == "venda"]
    if linhas is not None and "linha" in df.columns:
        df = df[df["linha"].isin(list(linhas))]
    if canais is not None and "cod_canal" in df.columns:
        df = df[df["cod_canal"].isin(list(canais))]
    return df


def velocidade_por_produto(
    vendas_fp: pd.DataFrame,
    chave: str = "cod_sku_pai",
) -> pd.DataFrame:
    """Velocidade semanal full price por produto (modelo).

    Velocidade = unidades / semanas ativas, onde semanas ativas =
    (última - primeira venda FP em dias)/7 + 1, com piso de 1 semana.
    Retorna colunas: [chave, unidades, dt_inicio, dt_fim, semanas_ativas,
    velocidade_semanal].
    """
    if vendas_fp.empty:
        return pd.DataFrame(
            columns=[chave, "unidades", "dt_inicio", "dt_fim", "semanas_ativas", "velocidade_semanal"]
        )
    g = vendas_fp.groupby(chave).agg(
        unidades=("qtd_produto", "sum"),
        dt_inicio=("dt_transacao", "min"),
        dt_fim=("dt_transacao", "max"),
    )
    dias = (g["dt_fim"] - g["dt_inicio"]).dt.days.clip(lower=0)
    g["semanas_ativas"] = (dias / 7 + 1).clip(lower=1)
    g["velocidade_semanal"] = g["unidades"] / g["semanas_ativas"]
    return g.reset_index()


def curva_tamanhos(
    vendas_fp: pd.DataFrame,
    produtos: pd.DataFrame,
    filtro: Optional[dict] = None,
    col_tamanho: str = "desc_tamanho",
) -> dict[str, float]:
    """Curva histórica de tamanhos (participação por tamanho), normalizada.

    Junta vendas ao cadastro de produtos por `sk_produto` para obter o tamanho.
    `filtro` = dict de {coluna_produto: valor} para restringir (ex.: grupo).
    Ignora tamanhos nulos. Retorna {} se não houver base suficiente.
    """
    if vendas_fp.empty or produtos.empty:
        return {}
    cols = ["sk_produto", col_tamanho] + list((filtro or {}).keys())
    cols = [c for c in dict.fromkeys(cols) if c in produtos.columns]
    prod = produtos[cols].drop_duplicates("sk_produto")
    df = vendas_fp.merge(prod, on="sk_produto", how="inner")
    if filtro:
        for col, val in filtro.items():
            if col in df.columns:
                df = df[df[col] == val]
    df = df[df[col_tamanho].notna()]
    if df.empty:
        return {}
    agg = df.groupby(col_tamanho)["qtd_produto"].sum()
    agg = agg[agg > 0]
    total = agg.sum()
    if total <= 0:
        return {}
    return {str(t): float(q / total) for t, q in agg.items()}


def participacao_lojas(
    vendas_fp: pd.DataFrame,
    filtro: Optional[dict] = None,
    col_loja: str = "sk_localidade",
) -> dict[str, float]:
    """Participação de cada loja nas vendas full price (normalizada)."""
    df = vendas_fp
    if filtro:
        for col, val in (filtro or {}).items():
            if col in df.columns:
                df = df[df[col] == val]
    if df.empty:
        return {}
    agg = df.groupby(col_loja)["qtd_produto"].sum()
    agg = agg[agg > 0]
    total = agg.sum()
    if total <= 0:
        return {}
    return {str(l): float(q / total) for l, q in agg.items()}


# --------------------------------------------------------------------------- #
# Escopo Souq (linha ROUPA + lojas Souq/Ecom) e coleções
# --------------------------------------------------------------------------- #
def lojas_souq(caminho: Optional[str] = None, incluir_ecom: bool = True) -> pd.DataFrame:
    """Lojas da marca Souq (físicas + Ecom). Exclui IDA, Outlet e TSM."""
    lj = carregar_lojas(caminho)
    df = lj[lj["Marca"].astype(str).str.upper() == "SOUQ"].copy()
    if not incluir_ecom:
        df = df[~df["canal"].astype(str).str.contains("ecom", case=False, na=False)]
    return df


def lojas_alvo_souq(
    caminho: Optional[str] = None,
    perfis: Optional[Iterable[str]] = None,
    climas: Optional[Iterable[str]] = None,
) -> pd.DataFrame:
    """Lojas físicas Souq ativas (sem Ecom, sem loja fechada) — destino da
    distribuição física.

    `perfis` (Perfil Econômico) e `climas` (Temperatura) restringem o parque-alvo;
    None/vazio = todas.
    """
    lj = lojas_souq(caminho, incluir_ecom=False)
    lj = lj[lj["dt_fechamento"].isna()]
    if perfis:
        lj = lj[lj["Perfil"].isin(list(perfis))]
    if climas:
        lj = lj[lj["Temperatura"].isin(list(climas))]
    return lj


def cluster_por_loja(caminho: Optional[str] = None) -> dict:
    """Mapa sk_localidade (str, ex '122.0') -> (Perfil Econômico, Clima).

    É a chave usada para extrapolar a participação de loja nova. A tupla permite
    afrouxar para só o Perfil quando a combinação exata não existir no parque
    (ex.: não há loja Perfil AB com clima Frio)."""
    lj = carregar_lojas(caminho)
    return {
        str(float(r["sk_localidade"])): (r.get("Perfil"), r.get("Temperatura"))
        for _, r in lj.iterrows()
    }


def opcoes_perfil_clima(caminho: Optional[str] = None) -> dict:
    """Valores disponíveis de Perfil Econômico e Clima nas lojas Souq ativas."""
    lj = lojas_alvo_souq(caminho)
    return {
        "perfis": sorted(lj["Perfil"].dropna().unique().tolist()),
        "climas": sorted(lj["Temperatura"].dropna().unique().tolist()),
    }


def espelhos_loja_nova(caminho: Optional[str] = None) -> dict:
    """De-para de loja nova -> loja espelho, de `config/lojas_espelho.yaml`.

    Retorna {sk_nova: (sk_espelho, fator, nome_nova, nome_espelho)} com as chaves
    no formato das participações ('484.0'). Regra do negócio: loja nova sem venda
    dos espelhos selecionados recebe fator × participação da loja espelho
    (ex.: Casa Jardins = 75% do Iguatemi SP). Nome que não bater com a base de
    lojas é ignorado em silêncio (o YAML é editável pelo negócio).
    """
    import yaml

    arq = PROJ_ROOT / "config" / "lojas_espelho.yaml"
    if not arq.exists():
        return {}
    with arq.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}

    lj = lojas_souq(caminho, incluir_ecom=False)
    por_nome = {str(r["desc_nome"]).strip().casefold(): (str(float(r["sk_localidade"])), str(r["desc_nome"]))
                for _, r in lj.iterrows()}

    saida = {}
    for nome_nova, regra in cfg.items():
        nova = por_nome.get(str(nome_nova).strip().casefold())
        esp = por_nome.get(str(regra.get("espelho", "")).strip().casefold())
        if nova and esp:
            saida[nova[0]] = (esp[0], float(regra.get("fator", 1.0)), nova[1], esp[1])
    return saida


def localidades_ecom(caminho: Optional[str] = None) -> set:
    """sk_localidade do(s) canal(is) Ecommerce da Souq (entram na aposta,
    mas não são destino físico de distribuição)."""
    lj = lojas_souq(caminho, incluir_ecom=True)
    ecom = lj[lj["canal"].astype(str).str.contains("ecom", case=False, na=False)]
    return {float(x) for x in ecom["sk_localidade"]}


def escopo_souq(
    vendas: pd.DataFrame,
    caminho: Optional[str] = None,
    incluir_ecom: bool = True,
    linhas: Optional[Iterable[str]] = ("ROUPA",),
) -> pd.DataFrame:
    """Restringe vendas ao escopo Souq: linha ROUPA + lojas Souq (+Ecom opc.)."""
    locs = {float(x) for x in lojas_souq(caminho, incluir_ecom)["sk_localidade"]}
    df = vendas
    if linhas is not None and "linha" in df.columns:
        df = df[df["linha"].isin(list(linhas))]
    return df[df["sk_localidade"].astype(float).isin(locs)]


# Coleções fora do escopo do app: PERENE e ALTO VERÃO são sujeira de cadastro
# (definição do negócio) e CANCELADO não é venda. Todas recebem rank None e são
# descartadas por `filtrar_colecoes`.
_COLECOES_IGNORADAS = ("PERENE", "ALTO VERAO", "CANCELAD")


def rank_colecao(colecao) -> Optional[float]:
    """Chave cronológica de uma coleção. Ex.: INVERNO 2023 -> 2023.0;
    VERÃO 2023-2024 -> 2023.5. Coleções fora do escopo -> None."""
    import re
    import unicodedata

    if colecao is None or (isinstance(colecao, float) and pd.isna(colecao)):
        return None
    s = unicodedata.normalize("NFKD", str(colecao)).encode("ascii", "ignore").decode().upper()
    if any(t in s for t in _COLECOES_IGNORADAS):
        return None
    anos = [int(a) for a in re.findall(r"(20\d{2})", s)]
    if not anos:
        return None
    if "INVERNO" in s:
        return float(anos[0])
    if "VERAO" in s:  # inclui ALTO VERÃO
        if len(anos) >= 2:
            return float(min(anos)) + 0.5
        return float(anos[0]) - 0.5  # verão de ano único: temporada terminando no ano
    return float(anos[0])


def colecoes_projetaveis(ano_base: int, adiante: int = 3) -> list[str]:
    """Coleções que se pode apostar, da mais próxima para a mais distante.

    Gera os rótulos (INVERNO YYYY / VERÃO YYYY-YYYY+1) em vez de ler do cadastro,
    porque a coleção-alvo normalmente **ainda não existe** na base quando a
    aposta é feita (ex.: INVERNO 2027).
    """
    saida = []
    for ano in range(ano_base, ano_base + adiante + 1):
        saida.append((float(ano), f"INVERNO {ano}"))
        saida.append((ano + 0.5, f"VERÃO {ano}-{ano + 1}"))
    return [nome for _, nome in sorted(saida)]


def fim_periodo_saudavel(colecao: str, fim_verao: str = "02/01",
                         fim_inverno: str = "14/06") -> Optional[date]:
    """Data em que a coleção deve estar saudavelmente encerrada.

    Premissa do negócio: VERÃO termina em 02/01 do ano seguinte ao de início
    (VERÃO 2026-2027 -> 02/01/2027) e INVERNO em 14/06 do próprio ano
    (INVERNO 2027 -> 14/06/2027). É o que define o horizonte da projeção.
    """
    rank = rank_colecao(colecao)
    if rank is None:
        return None
    dia_v, mes_v = (int(x) for x in fim_verao.split("/"))
    dia_i, mes_i = (int(x) for x in fim_inverno.split("/"))
    if float(rank).is_integer():           # INVERNO YYYY -> rank = YYYY
        return date(int(rank), mes_i, dia_i)
    return date(int(rank) + 1, mes_v, dia_v)  # VERÃO YYYY-YYYY+1 -> rank = YYYY.5


def semanas_ate(dt_entrada, dt_fim, minimo: int = 1, maximo: int = 52) -> int:
    """Semanas inteiras entre a entrada em loja e o fim do período (>= `minimo`)."""
    d0, d1 = pd.Timestamp(dt_entrada), pd.Timestamp(dt_fim)
    semanas = int(math.ceil((d1 - d0).days / 7))
    return max(minimo, min(semanas, maximo))


def filtrar_colecoes(
    df: pd.DataFrame,
    desde: float = 2022.0,
    col: str = "desc_colecao",
) -> pd.DataFrame:
    """Mantém coleções com rank >= `desde` (default Inverno 2022 em diante).

    Rank None (PERENE, ALTO VERÃO, CANCELADO, coleção ilegível) é sempre
    descartado — comparação com NaN dá False.
    """
    if col not in df.columns:
        return df
    return df[df[col].map(rank_colecao) >= desde]

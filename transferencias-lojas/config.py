"""Parâmetros de negócio e configuração do app de remanejamento entre lojas."""
import os
import unicodedata
from datetime import date
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Raiz do projeto (onde ficam as bases .xlsx e a pasta data/).
RAIZ = Path(__file__).resolve().parent

# --- Regras de negócio (ajustáveis pela barra lateral do app) ---------------

# Uma loja doadora só pode ceder um item que esteja parado há, no mínimo,
# este número de semanas contadas a partir da data de recebimento em loja.
SEMANAS_SEM_VENDA_MIN = 3

# Uma loja doadora não pode atender mais do que este número de lojas distintas
# em uma mesma rodada de sugestões.
MAX_LOJAS_POR_DOADORA = 5

# Janela (em dias) usada para medir a "probabilidade de venda" pela venda
# histórica do SKU pai em cada loja.
JANELA_VENDAS_DIAS = 90

# --- Limites de transferência por grupo (peças por SKU filho) ---------------
# Quantidade MÁXIMA que pode ser transferida de um SKU filho para uma loja
# receptora, conforme o grupo do produto.
GRUPO_LIMITES = {
    "Home": 10,
    "Acessórios": 4,
    "Roupa": 2,
}
# Limite usado quando o grupo do produto não for reconhecido.
LIMITE_GRUPO_PADRAO = 2

# Regra de grade (doadora): se ela ficaria com menos deste % dos tamanhos do pai,
# envia TODO o estoque daquele filho (ignora o limite de peças do grupo).
PCT_GRADE_MIN = 0.40

# Template da URL da foto do produto (preencha com o padrão do seu site/CDN).
# Campos disponíveis: {sku_pai}, {sku_filho}. Vazio -> painel sem imagem.
URL_FOTO_TEMPLATE = os.getenv("URL_FOTO_TEMPLATE", "")

# De-para entre a coluna desc_linha (Base_Produtos) e o grupo de regra acima.
# Linhas fora deste mapa (ex.: BAZAR MATRIZ) são EXCLUÍDAS do remanejamento.
MAPA_LINHA_GRUPO = {
    "HOME": "Home",
    "ACESSÓRIO": "Acessórios",
    "ACESSORIO": "Acessórios",
    "ACESSORIO IDA": "Acessórios",
    "ROUPA": "Roupa",
    "ROUPA IDA": "Roupa",
    "PRAIA IDA": "Roupa",
}

# Status de estoque (desc_status_produto, Base_Estoque) que PODEM ser remanejados.
# OUTLET e demais (CANCELADO, RECOMPRA, etc.) ficam de fora.
STATUS_ESTOQUE_PERMITIDOS = {"NOVIDADE", "PERENE", "LIQUIDAÇÃO", "MIGRADO"}

# Marcas de loja excluídas como doadora e como receptora (ex.: Outlet Alexânia).
EXCLUIR_MARCAS_LOJA = {"OUTLET"}

# --- Exceções por loja ------------------------------------------------------
# Lojas que NÃO cedem peças (fora da lista de doadoras) e lojas que NÃO
# recebem peças (fora das receptoras). Nomes como em Base_Lojas (desc_nome);
# a comparação ignora acentos e maiúsculas. Também editável no app (popover
# de parâmetros da aba Sugestões).
# Natal: problema de emissão de NF desde ~10/07/2026 — vendas não entram na
# base e todo o estoque "parece parado". Retirar daqui quando normalizar.
LOJAS_NAO_DOAM: set[str] = {"Souq Natal Shopping"}
LOJAS_NAO_RECEBEM: set[str] = set()


def norm_loja(nome) -> str:
    """Nome de loja normalizado para comparação (sem acento, minúsculo)."""
    s = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())

# Lead time (dias) entre dt_envio (Base_Produtos) e a chegada do item na loja.
# Premissa inicial enquanto não há histórico de estoque salvo.
LEADTIME_DIAS = 7

# --- Sazonalidade -----------------------------------------------------------
# Matéria-prima predominante: 1ª palavra-chave que aparece em desc_material
# (esquerda->direita = mais predominante). Sem material -> usa total do grupo.
MATERIAS_PRIMAS = [
    "ALGODÃO", "LINHO", "VISCOSE", "SEDA", "LÃ", "POLIÉSTER", "POLIAMIDA",
    "ELASTANO", "ACRÍLICO", "NYLON", "COURO", "CERÂMICA", "PORCELANA",
    "CRISTAL", "VIDRO", "LATÃO", "METAL", "AÇO", "RESINA", "ACETATO",
    "MADEIRA", "BAMBU", "PALHA", "JUTA", "PAPEL", "POLIPROPILENO", "PVC", "ABS",
]
CURVA_SAZONAL = RAIZ / "data" / "curva_sazonal.parquet"

# --- Cobertura --------------------------------------------------------------
# Janela (semanas) da média recente de venda do SKU pai por loja.
COBERTURA_SEMANAS_HIST = 8
# Horizonte (semanas) da previsão para o cálculo de cobertura.
COBERTURA_HORIZONTE_SEMANAS = 4
# Mín. de dias de histórico de estoque (na janela) para usar "dias com estoque"
# como denominador da velocidade (tira o efeito ruptura). Abaixo disso, usa a
# janela de calendário (dt_envio+leadtime) como hoje.
COBERTURA_MIN_DIAS_HIST = 14


def materia_prima_de(desc_material):
    """Matéria-prima predominante (1ª palavra-chave por posição no texto)."""
    if desc_material is None or str(desc_material).strip().lower() in ("", "nan", "none"):
        return "Não informado"
    txt = str(desc_material).upper()
    achados = [(txt.find(mp), mp) for mp in MATERIAS_PRIMAS if mp in txt]
    if not achados:
        return "Outros"
    return min(achados)[1]


import re as _re


def colecao_chave(colecao) -> float:
    """Chave de recência da coleção (maior = mais recente).

    INVERNO A -> A+0.5 ; VERÃO A-B -> B ; VERÃO A -> A ; ALTO VERÃO A B -> B.
    Coleções sem ano (PERENE, CANCELADO, vazio) -> -infinito (vão para o fim).
    """
    if colecao is None:
        return float("-inf")
    txt = str(colecao).upper()
    anos = [int(a) for a in _re.findall(r"19\d{2}|20\d{2}", txt)]
    if not anos:
        return float("-inf")
    if "INVERNO" in txt:
        return anos[0] + 0.5
    # VERÃO / ALTO VERÃO: usa o ano final (maior dos anos citados).
    return float(max(anos))


def colecoes_ordenadas(valores) -> list:
    """Lista de coleções distintas ordenada por recência (mais recente primeiro)."""
    unicas = {str(v) for v in valores if v is not None and str(v).strip().lower() not in ("", "nan")}
    return sorted(unicas, key=colecao_chave, reverse=True)


# --- Fonte de dados ---------------------------------------------------------

# "excel" -> lê as bases reais (.xlsx) na raiz do projeto (padrão).
# "mock"  -> dados de exemplo gerados em memória (roda sem nenhuma base).
FONTE_DADOS = os.getenv("FONTE_DADOS", "excel")

# Pasta com as bases reais (.xlsx). Padrão: Projetos\dados (um nível acima do
# projeto). Sobreponível via variável de ambiente PASTA_BASES.
PASTA_BASES = Path(os.getenv("PASTA_BASES", str(RAIZ.parent / "dados")))

ARQ_ESTOQUE = PASTA_BASES / "Base_Estoque.xlsx"
ARQ_LOJAS = PASTA_BASES / "Base_Lojas.xlsx"
ARQ_PRODUTOS = PASTA_BASES / "Base_Produtos.xlsx"
# Bases de vendas por ano (a do ano corrente é atualizada diariamente).
ARQS_VENDAS = [
    PASTA_BASES / "Base_2022.xlsx", PASTA_BASES / "Base_2023.xlsx",
    PASTA_BASES / "Base_2024.xlsx", PASTA_BASES / "Base_2025.xlsx",
    PASTA_BASES / "Base_2026.xlsx",
]

# Localidades do CD consideradas "estoque disponível para repor a loja".
# Se o item existir aqui (qtde>0), NÃO sugerimos transferência entre lojas.
CD_LOCALIDADES_DISPONIVEIS = ["CDES Vendas SOUQ Atacado_Ecomm_Varejo"]

# Histórico diário de estoque (para tirar o efeito ruptura no cálculo de giro
# e aproximar a data de recebimento). Acumulado em Parquet particionado por mês
# (data/hist_estoque/AAAA-MM.parquet), gravando só linhas com qtde > 0.
PASTA_HIST = RAIZ / "data" / "hist_estoque"
HIST_ESTOQUE = RAIZ / "data" / "hist_estoque.parquet"  # legado (migração)

# Cache diário dos dados já transformados (abre em segundos após a 1ª carga).
PASTA_CACHE = RAIZ / "data" / "cache"

# Data de referência ("hoje") usada nos cálculos de tempo parado.
# Em produção, deixe vazio para usar a data atual.
DATA_REFERENCIA = os.getenv("DATA_REFERENCIA", "")


def data_referencia() -> date:
    if DATA_REFERENCIA:
        return date.fromisoformat(DATA_REFERENCIA)
    return date.today()


def grupo_de_linha(desc_linha):
    """Mapeia desc_linha (Base_Produtos) para o grupo de regra (Home/Acessórios/Roupa).

    Retorna None para linhas fora do mapa (ex.: BAZAR MATRIZ) -> excluídas.
    """
    if desc_linha is None:
        return None
    return MAPA_LINHA_GRUPO.get(str(desc_linha).strip().upper())


def limite_do_grupo(grupo: str) -> int:
    return GRUPO_LIMITES.get(grupo, LIMITE_GRUPO_PADRAO)

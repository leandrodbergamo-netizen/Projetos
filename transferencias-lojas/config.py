"""Parâmetros de negócio e configuração do app de remanejamento entre lojas."""
import os
from datetime import date
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Raiz do projeto (onde ficam as bases .xlsx e a pasta data/).
RAIZ = Path(__file__).resolve().parent

# --- Regras de negócio (ajustáveis pela barra lateral do app) ---------------

# Uma loja doadora só pode ceder um item que esteja parado há, no mínimo,
# este número de semanas contadas a partir da data de recebimento em loja.
SEMANAS_SEM_VENDA_MIN = 2

# Uma loja doadora não pode atender mais do que este número de lojas distintas
# em uma mesma rodada de sugestões.
MAX_LOJAS_POR_DOADORA = 4

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


def materia_prima_de(desc_material):
    """Matéria-prima predominante (1ª palavra-chave por posição no texto)."""
    if desc_material is None or str(desc_material).strip().lower() in ("", "nan", "none"):
        return "Não informado"
    txt = str(desc_material).upper()
    achados = [(txt.find(mp), mp) for mp in MATERIAS_PRIMAS if mp in txt]
    if not achados:
        return "Outros"
    return min(achados)[1]


# --- Fonte de dados ---------------------------------------------------------

# "excel" -> lê as bases reais (.xlsx) na raiz do projeto (padrão).
# "mock"  -> dados de exemplo gerados em memória (roda sem nenhuma base).
FONTE_DADOS = os.getenv("FONTE_DADOS", "excel")

# Arquivos das bases reais (na raiz do projeto).
ARQ_ESTOQUE = RAIZ / "Base_Estoque.xlsx"
ARQ_LOJAS = RAIZ / "Base_Lojas.xlsx"
ARQ_PRODUTOS = RAIZ / "Base_Produtos.xlsx"
# Bases de vendas por ano (a do ano corrente é atualizada diariamente).
ARQS_VENDAS = [
    RAIZ / "Base_2022.xlsx", RAIZ / "Base_2023.xlsx", RAIZ / "Base_2024.xlsx",
    RAIZ / "Base_2025.xlsx", RAIZ / "Base_2026.xlsx",
]

# Localidades do CD consideradas "estoque disponível para repor a loja".
# Se o item existir aqui (qtde>0), NÃO sugerimos transferência entre lojas.
CD_LOCALIDADES_DISPONIVEIS = ["CDES Vendas SOUQ Atacado_Ecomm_Varejo"]

# Histórico diário de estoque (para tirar o efeito ruptura no cálculo de giro
# e aproximar a data de recebimento). Vai sendo acumulado a cada refresh.
HIST_ESTOQUE = RAIZ / "data" / "hist_estoque.parquet"

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

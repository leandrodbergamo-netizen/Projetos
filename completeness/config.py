# -*- coding: utf-8 -*-
"""Parâmetros e localização das fontes da auditoria de completeness do catálogo Souq.

Nada aqui executa I/O na importação: o app na nuvem importa este módulo sem ter
nenhuma base .xlsx por perto. As funções pasta_* só falham quando chamadas.
"""
from __future__ import annotations

import datetime
import glob
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:      # o app na nuvem lê tudo de st.secrets
    pass

RAIZ = Path(__file__).resolve().parent

# Data de referência ("hoje") das gravações. Vazio = data atual.
DATA_REFERENCIA = os.getenv("DATA_REFERENCIA", "")


def hoje() -> str:
    return DATA_REFERENCIA or datetime.date.today().isoformat()


# --- Arquivos gerados -------------------------------------------------------
HIST = RAIZ / "historico.csv"
HIST_DISP = RAIZ / "historico_disponibilidade.csv"
DETALHE_ATUAL = RAIZ / "detalhe_atual.csv"
DISP_ATUAL = RAIZ / "disponibilidade_atual.csv"
DATA_JS = RAIZ / "data.js"
CACHE_CATALOGO = RAIZ / "_cache_catalogo.json"
RESUMO_JSON = RAIZ / "data" / "resumo.json"
# Miniaturas dentro de static/ para o Streamlit servi-las direto no modo local
# (enableStaticServing). Na nuvem elas vêm do bucket, por URL assinada.
PASTA_THUMBS = RAIZ / "static" / "thumbs"
URL_THUMBS_LOCAL = "app/static/thumbs"
PASTA_LOGS = RAIZ / "logs"

# --- Fontes externas --------------------------------------------------------
CATALOGO_URL = "https://www.souqstore.com.br/products.json?limit=250&page={page}"
MAX_PAGINAS = 60

# Piso de sanidade: coleta abaixo disso não grava nada (evita zerar a série).
MIN_PRODUTOS_COLETA = 100

ARQ_EXCECOES = "SOUQ_CONTROLE DESABILITADOS .xlsx"

# Padrão das pastas de coleção do Marketing (atalhos do OneDrive). Varre TODAS
# as coleções que estiverem sincronizadas — as novas e as antigas de Outlet.
PADRAO_PASTA_FOTOS = "Marketing - COLEÇÃO *"


def pasta_dados() -> str:
    """Pasta com as bases (Base_Produtos.xlsx, Base_Estoque.xlsx).

    Ordem: SOUQ_DADOS_DIR > Projetos\\dados > mounts do sandbox > pasta-mãe.
    """
    cands = [os.environ.get("SOUQ_DADOS_DIR"),
             str(RAIZ.parent / "dados"),
             r"C:\Users\LeandroDias\Projetos\dados",
             *glob.glob("/sessions/*/mnt/dados"),
             str(RAIZ.parent)]
    for c in cands:
        if c and os.path.exists(os.path.join(c, "Base_Produtos.xlsx")):
            return c
    raise FileNotFoundError("Base_Produtos.xlsx não encontrada; defina SOUQ_DADOS_DIR")


def pasta_produto() -> str | None:
    """Pasta 'Produto' (OneDrive Ecommerce) com a planilha de SKUs exceção."""
    cands = [os.environ.get("SOUQ_PRODUTO_DIR"),
             r"C:\Users\LeandroDias\OneDrive - wbgretail.com.br\Ecommerce - Ecommerce"
             r"\1 Ecom - Documentos\2026\Produto",
             *glob.glob("/sessions/*/mnt/Produto")]
    for c in cands:
        if c and os.path.exists(os.path.join(c, ARQ_EXCECOES)):
            return c
    return None


def pastas_fotos() -> list[str]:
    """Pastas de coleção do Marketing com as fotos de e-commerce (por SKU).

    SOUQ_FOTOS_DIR aponta uma pasta específica; sem ela, varre o OneDrive
    procurando toda pasta que casa com PADRAO_PASTA_FOTOS.
    """
    forcada = os.environ.get("SOUQ_FOTOS_DIR")
    if forcada and os.path.isdir(forcada):
        return [forcada]
    achadas: list[str] = []
    for raiz in [r"C:\Users\LeandroDias\OneDrive - wbgretail.com.br", "/sessions"]:
        if not os.path.isdir(raiz):
            continue
        for padrao in (PADRAO_PASTA_FOTOS, f"*/mnt/{PADRAO_PASTA_FOTOS}"):
            achadas += [p for p in glob.glob(os.path.join(raiz, padrao)) if os.path.isdir(p)]
    # Fallback: layout antigo do sandbox (Marketing*MONDO sem "COLEÇÃO").
    if not achadas:
        achadas = [p for p in glob.glob("/sessions/*/mnt/Marketing*MONDO") if os.path.isdir(p)]
    return sorted(set(achadas))


# --- Regras de negócio (NÃO alterar sem quebrar a série histórica) -----------

# Os 14 campos auditados no catálogo do site.
FLAGS = ['Descrição', 'Descrição Estruturada', 'Composição/Material', 'Cor', 'Medidas',
         'Ocasião de Uso', 'Imagem (≥1)', 'Imagens (≥3)', 'Alt-text Imagens',
         'Tipo de Produto', 'Tags', 'SKU', 'Peso', 'Preço']

# Campos coletados mas fora do cálculo da média de completeness.
FLAGS_FORA_DA_MEDIA = {'Alt-text Imagens'}

# Estoque mínimo (soma das localidades válidas) para o SKU pai ser candidato.
ESTOQUE_MIN_CANDIDATO = 2

# Localidades que não contam como estoque disponível para venda no site.
EXCL_LOCS = {'Souq Sp Iguatemi Sao Paul', 'CDES Defeitos', 'CDES Recebimento'}
CD_VENDAS = 'CDES Vendas SOUQ Atacado_Ecomm_Varejo'

# Primeira palavra do título no site -> subcategoria.
SUB = {
 'BLUSA': 'Blusas', 'BLUSAO': 'Blusas', 'CAMISA': 'Camisas', 'CAMISAO': 'Camisas', 'CAMISETA': 'Camisetas',
 'REGATA': 'Regatas', 'REGATAO': 'Regatas', 'TOP': 'Tops', 'CROPPED': 'Tops', 'BODY': 'Bodies',
 'CALCA': 'Calças', 'LEGGING': 'Calças', 'HOT': 'Shorts', 'HOTPANTS': 'Shorts', 'SHORTS': 'Shorts',
 'SHORT': 'Shorts', 'BERMUDA': 'Shorts',
 'SAIA': 'Saias', 'VESTIDO': 'Vestidos', 'KAFTAN': 'Kaftans', 'TUNICA': 'Kaftans',
 'MACACAO': 'Macacões', 'MACAQUINHO': 'Macacões',
 'CASACO': 'Casacos e Jaquetas', 'JAQUETA': 'Casacos e Jaquetas', 'BLAZER': 'Casacos e Jaquetas',
 'PARKA': 'Casacos e Jaquetas', 'COLETE': 'Casacos e Jaquetas', 'CARDIGAN': 'Casacos e Jaquetas',
 'CARDIGA': 'Casacos e Jaquetas', 'KIMONO': 'Casacos e Jaquetas',
 'MAIO': 'Praia', 'BIQUINI': 'Praia', 'SAIDA': 'Praia',
 'COLAR': 'Bijoux', 'BRINCO': 'Bijoux', 'PULSEIRA': 'Bijoux', 'BRACELETE': 'Bijoux', 'CHOKER': 'Bijoux',
 'ANEL': 'Bijoux', 'PINGENTE': 'Bijoux',
 'BOLSA': 'Bolsas e Necessaires', 'NECESSAIRE': 'Bolsas e Necessaires', 'MOCHILA': 'Bolsas e Necessaires',
 'MALA': 'Bolsas e Necessaires', 'CLUTCH': 'Bolsas e Necessaires', 'ESTOJO': 'Bolsas e Necessaires',
 'CARTEIRA': 'Carteiras e Chaveiros', 'PORTA': 'Carteiras e Chaveiros',
 'PORTA-MOEDA': 'Carteiras e Chaveiros', 'CHAVEIRO': 'Carteiras e Chaveiros',
 'LENCO': 'Lenços e Pashminas', 'PASHMINA': 'Lenços e Pashminas', 'ECHARPE': 'Lenços e Pashminas',
 'CHAPEU': 'Chapéus e Presilhas', 'VISEIRA': 'Chapéus e Presilhas', 'PRESILHA': 'Chapéus e Presilhas',
 'TIARA': 'Chapéus e Presilhas', 'BOINA': 'Chapéus e Presilhas', 'SCRUNCHIE': 'Chapéus e Presilhas',
 'FAIXA': 'Chapéus e Presilhas', 'FITA': 'Chapéus e Presilhas',
 'CINTO': 'Cintos', 'OCULOS': 'Outros Acessórios',
 'ALMOFADA': 'Têxtil Casa', 'CAPA': 'Têxtil Casa', 'MANTA': 'Têxtil Casa', 'TAPETE': 'Têxtil Casa',
 'ENCHIMENTO': 'Têxtil Casa',
 'TOALHA': 'Mesa Posta', 'GUARDANAPO': 'Mesa Posta', 'JOGO': 'Mesa Posta', 'SOUSPLAT': 'Mesa Posta',
 'ARGOLA': 'Mesa Posta', 'PRATO': 'Mesa Posta', 'BOWL': 'Mesa Posta', 'TACA': 'Mesa Posta',
 'COPO': 'Mesa Posta', 'JARRA': 'Mesa Posta', 'BULE': 'Mesa Posta', 'XICARA': 'Mesa Posta',
 'TIGELA': 'Mesa Posta', 'TRAVESSA': 'Mesa Posta', 'PETISQUEIRA': 'Mesa Posta', 'BANDEJA': 'Mesa Posta',
 'TALHER': 'Mesa Posta', 'COLHER': 'Mesa Posta', 'INFUSOR': 'Mesa Posta', 'MARCADOR': 'Mesa Posta',
 'GALHETEIRO': 'Mesa Posta', 'LEITEIRA': 'Mesa Posta', 'ABRIDOR': 'Mesa Posta', 'GARRAFA': 'Mesa Posta',
 'VASO': 'Decoração', 'CACHEPOT': 'Decoração', 'DECORATIVO': 'Decoração', 'LUMINARIA': 'Decoração',
 'LUMIN': 'Decoração', 'CASTICAL': 'Decoração', 'VELA': 'Decoração', 'DIFUSOR': 'Decoração',
 'SABONETE': 'Decoração', 'CAIXA': 'Decoração', 'CESTA': 'Decoração', 'CESTO': 'Decoração',
 'ESCULTURA': 'Decoração', 'QUADRO': 'Decoração', 'ESPELHO': 'Decoração', 'PORTA-VELA': 'Decoração',
 'INCENSO': 'Decoração', 'KIT': 'Decoração', 'POTE': 'Decoração', 'PESO': 'Decoração',
 'LANTERNA': 'Decoração', 'ABAJUR': 'Decoração', 'LUPA': 'Decoração', 'OBJETO': 'Decoração',
 'HOME': 'Decoração',
 'CADERNO': 'Papelaria', 'AGENDA': 'Papelaria', 'LAPIS': 'Papelaria', 'CANETA': 'Papelaria',
}
ROUPA_SUBS = {'Blusas', 'Camisas', 'Camisetas', 'Regatas', 'Tops', 'Bodies', 'Calças', 'Shorts',
              'Saias', 'Vestidos', 'Kaftans', 'Macacões', 'Casacos e Jaquetas', 'Praia'}
ACESS_SUBS = {'Bijoux', 'Bolsas e Necessaires', 'Carteiras e Chaveiros', 'Lenços e Pashminas',
              'Chapéus e Presilhas', 'Cintos', 'Outros Acessórios'}
CASA_SUBS = ('Têxtil Casa', 'Mesa Posta', 'Decoração', 'Papelaria')

# --- Apresentação -----------------------------------------------------------

# Quebra de série: em 14/07/2026 entraram os filtros de SKU exceção e dt_envio
# (candidatos ~1686->~1495). Os gráficos começam nesta data para não comparar
# períodos com critérios diferentes.
DATA_INICIO_SERIE = "2026-07-14"

# --- Alertas ----------------------------------------------------------------
ALERTAS = {
    "coleta_min": 1500,           # produtos coletados no products.json
    # Limiar do guia. Hoje o nível real é ~1400 candidatos, então este piso só
    # dispara depois de uma queda de ~50% — vale subir para ~1300.
    "candidatos_min": 700,        # SKUs pai elegíveis (estoque >= 2)
    "sem_match_max": 100,         # produtos no site sem correspondência na Base_Produtos
    "queda_disp_pp": 5.0,         # queda de disponibilidade vs dia anterior (p.p.)
    "cd_min_foto_fora": 50,       # unidades no CD de item com foto e fora do site
}

# --- Nuvem (Supabase) -------------------------------------------------------
PREFIXO_TABELAS = "comp_"
BUCKET_THUMBS = os.getenv("SUPABASE_BUCKET", "comp-thumbs")


def numero(v, casas: int = 0) -> str:
    """Número no padrão brasileiro: 1.234 / 78,5 / −4,8."""
    import pandas as pd
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:,.{casas}f}".replace(",", "~").replace(".", ",").replace("~", ".")


def plural(n: int, singular: str, plural_: str | None = None) -> str:
    return f"{numero(n)} {singular if abs(n) == 1 else (plural_ or singular + 's')}"


def segredo(nome: str, padrao: str = "") -> str:
    """Configuração via variável de ambiente ou st.secrets (app na nuvem)."""
    v = os.getenv(nome)
    if v:
        return v
    try:
        import streamlit as st
        if nome in st.secrets:
            return str(st.secrets[nome])
    except Exception:
        pass
    return padrao


def fonte_dados() -> str:
    """'local' (PC, lê os CSVs da rotina) ou 'supabase' (nuvem, lê o Postgres)."""
    return segredo("FONTE_DADOS", "local").lower()

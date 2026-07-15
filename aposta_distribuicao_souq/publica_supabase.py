"""Publica os dados preparados no Supabase (Postgres) para o app na nuvem ler.

Roda NO SEU PC. Reconstrói as tabelas a partir das bases Excel (já no escopo
Souq, full price, com tecido/cor/faixa resolvidos) e grava no Postgres,
substituindo o conteúdo. O app no Streamlit Cloud lê dessas tabelas e só aplica
as regras — nenhum Excel vai para a nuvem.

As tabelas levam o prefixo `aposta_` para NÃO colidir com as do app de
transferências entre lojas, que vive no mesmo banco e tem uma tabela `produtos`.

Pré-requisitos:
  - DATABASE_URL no .env (string do **Pooler** do Supabase).
  - Bases atualizadas em ..\\dados (o app usa o cache parquet se existir).

Uso:
  python publica_supabase.py
"""
from __future__ import annotations

import sys
import time

import pandas as pd

from core import fonte
from core.dados import carregar_lojas
from core.taxonomia import _tabela_faixas

# Colunas publicadas do cadastro — as que as regras e a tela usam.
COLS_PRODUTOS = [
    "sk_produto", "cod_produto", "cod_sku_pai", "desc_item", "desc_colecao",
    "desc_sub_grupo_wbg", "desc_grupo_wgb", "desc_cor", "desc_tamanho",
    "desc_manga", "desc_comprimento", "desc_fit", "desc_material", "dt_envio",
    "url", "preco", "grupo_material", "cor_grupo", "faixa", "rank_colecao",
]


def construir() -> dict[str, pd.DataFrame]:
    """Monta as 4 tabelas a partir das bases locais."""
    # Importado aqui para não exigir streamlit fora do app.
    from app.dados_app import COLS_VENDAS, construir_produtos, construir_vendas

    print("Preparando cadastro...", flush=True)
    produtos = construir_produtos()
    print("Preparando vendas (2022-2026)...", flush=True)
    vendas = construir_vendas(produtos)

    return {
        "produtos": produtos[[c for c in COLS_PRODUTOS if c in produtos.columns]],
        "vendas": vendas[[c for c in COLS_VENDAS if c in vendas.columns]],
        "lojas": carregar_lojas(),
        "faixas": _tabela_faixas(),
    }


def publicar() -> None:
    from sqlalchemy import text

    if not fonte.db_url():
        print("ERRO: DATABASE_URL não configurada. Defina no .env.")
        sys.exit(1)

    dados = construir()
    eng = fonte.engine()
    try:
        for nome, df in dados.items():
            tabela = f"{fonte.PREFIXO}{nome}"
            t0 = time.time()
            df.to_sql(tabela, eng, if_exists="replace", index=False,
                      chunksize=5000, method="multi")
            print(f"  {tabela}: {len(df)} linhas em {time.time()-t0:.1f}s", flush=True)

        # Habilita RLS (sem policies): bloqueia leitura pela Data API pública do
        # Supabase. O app conecta como dono das tabelas e ignora RLS, então
        # continua lendo normalmente.
        with eng.begin() as con:
            for nome in dados:
                con.execute(text(
                    f'ALTER TABLE public."{fonte.PREFIXO}{nome}" ENABLE ROW LEVEL SECURITY'
                ))
        print("RLS habilitado nas tabelas.")
    finally:
        eng.dispose()
    print("Publicação concluída.")


if __name__ == "__main__":
    publicar()

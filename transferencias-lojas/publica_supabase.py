"""Publica os dados preparados no Supabase (Postgres) para o app na nuvem ler.

Roda NO SEU PC, depois do refresh das planilhas. Reconstrói as tabelas a partir
das bases Excel e grava no Postgres (substituindo o conteúdo do dia). O app
hospedado no Streamlit Cloud lê dessas tabelas.

Pré-requisitos:
  - DATABASE_URL no .env (string de conexão do Supabase — use o Pooler).
  - Curva sazonal construída (python sazonalidade.py) para publicar a sazonalidade.

Uso:
  python publica_supabase.py
"""
from __future__ import annotations

import sys
import time

import config
import data_source
import sazonalidade


def publicar() -> None:
    from sqlalchemy import create_engine

    url = data_source.db_url()
    if not url:
        print("ERRO: DATABASE_URL não configurada. Defina no .env.")
        sys.exit(1)

    print("Reconstruindo dados a partir das bases...", flush=True)
    dados = data_source._build_excel(config.data_referencia())

    eng = create_engine(url, pool_pre_ping=True)
    tabelas = list(data_source.TABELAS)

    # Curva sazonal (opcional, mas recomendada).
    curva = sazonalidade.carregar_curva()
    if curva is not None:
        dados = {**dados, "curva_sazonal": curva}
        tabelas = tabelas + ["curva_sazonal"]
    else:
        print("AVISO: curva_sazonal.parquet não encontrada — rode 'python sazonalidade.py'.")

    for nome in tabelas:
        df = dados[nome]
        t0 = time.time()
        df.to_sql(nome, eng, if_exists="replace", index=False,
                  chunksize=5000, method="multi")
        print(f"  {nome}: {len(df)} linhas em {time.time()-t0:.1f}s", flush=True)

    eng.dispose()
    print("Publicação concluída.")


if __name__ == "__main__":
    publicar()

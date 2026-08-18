# -*- coding: utf-8 -*-
"""Publica o resultado da auditoria no Supabase para o app na nuvem ler.

Roda NO SEU PC, depois do processamento: grava as tabelas comp_* no Postgres
(substituindo o conteúdo) e sobe as miniaturas novas para o Storage.

Pré-requisitos no .env:
  DATABASE_URL           string do POOLER do Supabase
  SUPABASE_URL           https://SEU_REF.supabase.co
  SUPABASE_SERVICE_KEY   service_role key (só fica no seu PC e nos Secrets)

Uso:
  python publica_supabase.py            publica os CSVs já gerados
  python publica_supabase.py --fotos    força reenviar TODAS as miniaturas
"""
from __future__ import annotations

import sys
import time

import pandas as pd

import config
import data_source
import storage

# Registro do que já subiu para o Storage, para não reenviar tudo todo dia.
LEDGER = config.RAIZ / "data" / "thumbs_enviadas.txt"


def _ledger_ler() -> set[str]:
    if not LEDGER.exists():
        return set()
    return {l.strip() for l in LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()}


def _ledger_gravar(pais: set[str]) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text("\n".join(sorted(pais)), encoding="utf-8")


def _tabelas(resultado: dict | None) -> dict[str, pd.DataFrame]:
    """Os DataFrames a publicar: do processamento em memória ou dos CSVs."""
    if resultado:
        return {"detalhe": resultado["df"], "disponibilidade": resultado["dd"],
                "historico": resultado["hist"], "hist_disp": resultado["hist_disp"],
                "meta": pd.DataFrame([{**resultado["resumo"],
                                       "atualizado": time.strftime("%d/%m/%Y %H:%M")}])}
    return {n: df for n, df in data_source.carregar_local().items()}


def publicar(resultado: dict | None = None, *, todas_as_fotos: bool = False) -> None:
    from sqlalchemy import create_engine, text

    url = data_source.db_url()
    if not url:
        print("ERRO: DATABASE_URL não configurada. Defina no .env.")
        sys.exit(1)

    tabelas = _tabelas(resultado)
    eng = create_engine(url, pool_pre_ping=True)
    try:
        for nome, df in tabelas.items():
            alvo = data_source.nome_tabela(nome)
            t0 = time.time()
            df.to_sql(alvo, eng, if_exists="replace", index=False,
                      chunksize=5000, method="multi")
            print(f"  {alvo}: {len(df)} linhas em {time.time()-t0:.1f}s", flush=True)

        # RLS sem policies bloqueia a Data API pública do Supabase. O app conecta
        # como 'postgres' (dono das tabelas) e ignora RLS, então segue lendo.
        with eng.begin() as con:
            for nome in tabelas:
                con.execute(text(f'ALTER TABLE public."{data_source.nome_tabela(nome)}" '
                                 f'ENABLE ROW LEVEL SECURITY'))
        print("RLS habilitado nas tabelas.")
    finally:
        eng.dispose()

    _publicar_fotos(tabelas["disponibilidade"], todas_as_fotos)
    print("Publicação concluída.")


def _publicar_fotos(disp: pd.DataFrame, todas: bool) -> None:
    if not storage.configurado():
        print("AVISO: SUPABASE_URL/SUPABASE_SERVICE_KEY ausentes — miniaturas não publicadas.")
        return
    com_foto = {str(p) for p in disp.loc[disp["tem_foto"] == 1, "pai"]}
    existentes = {a.stem for a in config.PASTA_THUMBS.glob("*.jpg")}
    ja_enviadas = set() if todas else _ledger_ler()
    pendentes = sorted((com_foto & existentes) - ja_enviadas)
    if not pendentes:
        print("  miniaturas: nada novo para enviar.")
        return
    n = storage.sincronizar(pendentes)
    print(f"  miniaturas: {n} enviadas ao bucket '{config.BUCKET_THUMBS}'.")
    _ledger_gravar(ja_enviadas | set(pendentes[:n]))


if __name__ == "__main__":
    publicar(todas_as_fotos="--fotos" in sys.argv)

"""Histórico de apostas: persiste cada projeção para reabrir cenários depois.

Onde grava:
- Com `DATABASE_URL` configurada (PC via .env, nuvem via Secrets): tabela
  `aposta_historico` no Supabase — assim o histórico é compartilhado pelo time e
  sobrevive aos redeploys (o disco do Streamlit Cloud é efêmero).
- Sem banco: fallback em `.cache_dados/historico.jsonl`, só desta máquina.

O payload é o dict da projeção (inputs, espelhos, resultado e os insumos que a
aba Distribuição precisa), serializado em JSON.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from core import fonte

TABELA = f"{fonte.PREFIXO}historico"
_ARQ_LOCAL = Path(__file__).resolve().parent.parent / ".cache_dados" / "historico.jsonl"

_DDL = f"""
create table if not exists public."{TABELA}" (
    id text primary key,
    criado_em timestamptz not null,
    resumo text,
    payload jsonb
)
"""


def _novo_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def _json_seguro(payload: dict) -> str:
    """Serializa tolerando Timestamps/np.float/etc."""
    return json.dumps(payload, ensure_ascii=False, default=str)


# --------------------------------------------------------------------------- #
# Backend Supabase
# --------------------------------------------------------------------------- #
def _salvar_db(id_: str, criado: datetime, resumo: str, payload: dict) -> None:
    from sqlalchemy import text

    eng = fonte.engine()
    try:
        with eng.begin() as con:
            con.execute(text(_DDL))
            con.execute(text(f'alter table public."{TABELA}" enable row level security'))
            con.execute(
                text(f'insert into public."{TABELA}" (id, criado_em, resumo, payload) '
                     "values (:i, :c, :r, cast(:p as jsonb))"),
                {"i": id_, "c": criado, "r": resumo, "p": _json_seguro(payload)},
            )
    finally:
        eng.dispose()


def _listar_db(limite: int) -> pd.DataFrame:
    from sqlalchemy import text

    eng = fonte.engine()
    try:
        with eng.connect() as con:
            existe = con.execute(text(
                "select 1 from information_schema.tables "
                "where table_schema='public' and table_name=:t"), {"t": TABELA}).scalar()
            if not existe:
                return pd.DataFrame(columns=["id", "criado_em", "resumo", "payload"])
            df = pd.read_sql(
                text(f'select id, criado_em, resumo, payload from public."{TABELA}" '
                     "order by criado_em desc limit :n"), con, params={"n": limite})
    finally:
        eng.dispose()
    df["payload"] = df["payload"].map(lambda p: p if isinstance(p, dict) else json.loads(p))
    return df


def _excluir_db(id_: str) -> None:
    from sqlalchemy import text

    eng = fonte.engine()
    try:
        with eng.begin() as con:
            con.execute(text(f'delete from public."{TABELA}" where id = :i'), {"i": id_})
    finally:
        eng.dispose()


# --------------------------------------------------------------------------- #
# Backend arquivo local (fallback sem banco)
# --------------------------------------------------------------------------- #
def _salvar_arq(id_: str, criado: datetime, resumo: str, payload: dict, caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    linha = {"id": id_, "criado_em": criado.isoformat(), "resumo": resumo, "payload": payload}
    with caminho.open("a", encoding="utf-8") as fh:
        fh.write(_json_seguro(linha) + "\n")


def _ler_arq(caminho: Path) -> list[dict]:
    if not caminho.exists():
        return []
    linhas = []
    for ln in caminho.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            try:
                linhas.append(json.loads(ln))
            except json.JSONDecodeError:
                continue  # linha corrompida não derruba o histórico
    return linhas


def _listar_arq(limite: int, caminho: Path) -> pd.DataFrame:
    # inverte antes de ordenar: em empate de criado_em (relógio com tick de ~15ms
    # no Windows), a ordenação estável mantém o gravado por último em primeiro
    linhas = sorted(reversed(_ler_arq(caminho)),
                    key=lambda x: x.get("criado_em", ""), reverse=True)
    df = pd.DataFrame(linhas[:limite], columns=["id", "criado_em", "resumo", "payload"])
    if not df.empty:
        df["criado_em"] = pd.to_datetime(df["criado_em"], errors="coerce")
    return df


def _excluir_arq(id_: str, caminho: Path) -> None:
    restantes = [l for l in _ler_arq(caminho) if l.get("id") != id_]
    with caminho.open("w", encoding="utf-8") as fh:
        for l in restantes:
            fh.write(_json_seguro(l) + "\n")


# --------------------------------------------------------------------------- #
# API pública
# --------------------------------------------------------------------------- #
def salvar(resumo: str, payload: dict, caminho_local: Optional[Path] = None) -> str:
    """Grava um cenário e retorna o id."""
    id_, criado = _novo_id(), datetime.now()
    if fonte.db_url():
        _salvar_db(id_, criado, resumo, payload)
    else:
        _salvar_arq(id_, criado, resumo, payload, caminho_local or _ARQ_LOCAL)
    return id_


def listar(limite: int = 200, caminho_local: Optional[Path] = None) -> pd.DataFrame:
    """Cenários salvos, do mais recente para o mais antigo."""
    if fonte.db_url():
        return _listar_db(limite)
    return _listar_arq(limite, caminho_local or _ARQ_LOCAL)


def excluir(id_: str, caminho_local: Optional[Path] = None) -> None:
    if fonte.db_url():
        _excluir_db(id_)
    else:
        _excluir_arq(id_, caminho_local or _ARQ_LOCAL)

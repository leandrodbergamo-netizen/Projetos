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
from datetime import datetime, timezone
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
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


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


def _obter_db(id_: str) -> Optional[dict]:
    from sqlalchemy import text

    eng = fonte.engine()
    try:
        with eng.connect() as con:
            existe = con.execute(text(
                "select 1 from information_schema.tables "
                "where table_schema='public' and table_name=:t"), {"t": TABELA}).scalar()
            if not existe:
                return None
            row = con.execute(
                text(f'select id, criado_em, resumo, payload from public."{TABELA}" '
                     "where id = :i"), {"i": id_}).mappings().first()
    finally:
        eng.dispose()
    if row is None:
        return None
    p = row["payload"]
    return {"id": row["id"], "criado_em": row["criado_em"], "resumo": row["resumo"],
            "payload": p if isinstance(p, dict) else json.loads(p)}


def _atualizar_db(id_: str, payload: dict, resumo: Optional[str]) -> None:
    from sqlalchemy import text

    eng = fonte.engine()
    try:
        with eng.begin() as con:
            r = con.execute(
                text(f'update public."{TABELA}" set payload = cast(:p as jsonb), '
                     "resumo = coalesce(:r, resumo) where id = :i"),
                {"i": id_, "p": _json_seguro(payload), "r": resumo})
            if r.rowcount == 0:
                raise KeyError(f"Registro {id_!r} não existe no histórico.")
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


def _obter_arq(id_: str, caminho: Path) -> Optional[dict]:
    for linha in _ler_arq(caminho):
        if linha.get("id") == id_:
            return linha
    return None


def _atualizar_arq(id_: str, payload: dict, resumo: Optional[str], caminho: Path) -> None:
    linhas, achou = _ler_arq(caminho), False
    for l in linhas:
        if l.get("id") == id_:
            l["payload"] = payload
            if resumo is not None:
                l["resumo"] = resumo
            achou = True
    if not achou:
        raise KeyError(f"Registro {id_!r} não existe no histórico.")
    with caminho.open("w", encoding="utf-8") as fh:
        for l in linhas:
            fh.write(_json_seguro(l) + "\n")


# --------------------------------------------------------------------------- #
# API pública
# --------------------------------------------------------------------------- #
def normalizar_payload(p: dict) -> dict:
    """Leitura tolerante de payloads antigos (v1) — nunca regrava o registro.

    v1 tinha faixa única derivada do preço e não conhecia parque nem aposta
    final: `inputs.faixas` ausente vira `[inputs.faixa]`; `parque` ausente =
    todas as lojas; `aposta_final` ausente = `aposta_total`. `preco` (v1) fica
    onde existir, só para exibição.
    """
    p = dict(p or {})
    ins = dict(p.get("inputs") or {})
    if not ins.get("faixas"):
        ins["faixas"] = [ins["faixa"]] if ins.get("faixa") else []
    p["inputs"] = ins
    if not p.get("parque"):
        p["parque"] = {"perfis": None, "climas": None, "n_lojas_alvo": None}
    if p.get("aposta_final") is None:
        p["aposta_final"] = p.get("aposta_total")
    p.setdefault("curva_origem", {})
    return p


def salvar(resumo: str, payload: dict, caminho_local: Optional[Path] = None) -> str:
    """Grava um cenário e retorna o id.

    `criado_em` é gravado em UTC com fuso explícito (a nuvem roda em UTC);
    a exibição converte para America/Sao_Paulo.
    """
    id_, criado = _novo_id(), datetime.now(timezone.utc)
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


def obter(id_: str, caminho_local: Optional[Path] = None) -> Optional[dict]:
    """Um registro {'id', 'criado_em', 'resumo', 'payload'} — ou None."""
    if fonte.db_url():
        return _obter_db(id_)
    return _obter_arq(id_, caminho_local or _ARQ_LOCAL)


def atualizar(id_: str, payload: dict, resumo: Optional[str] = None,
              caminho_local: Optional[Path] = None) -> None:
    """Substitui o payload (e opcionalmente o resumo) de um registro existente.

    `criado_em` é preservado — a distribuição atualiza o MESMO cenário em vez
    de criar um segundo registro. KeyError se o id não existe.
    """
    if fonte.db_url():
        _atualizar_db(id_, payload, resumo)
    else:
        _atualizar_arq(id_, payload, resumo, caminho_local or _ARQ_LOCAL)


def excluir(id_: str, caminho_local: Optional[Path] = None) -> None:
    if fonte.db_url():
        _excluir_db(id_)
    else:
        _excluir_arq(id_, caminho_local or _ARQ_LOCAL)

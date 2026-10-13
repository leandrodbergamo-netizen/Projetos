"""Premissas gerais do app (`config/parametros.yaml`) com camada compartilhada no banco.

- O YAML é a base (versionado, com comentários) e o fallback de máquina sem banco.
- Com `DATABASE_URL` (PC via .env, nuvem via Secrets), o que a aba Configurações
  salva vai TAMBÉM para a tabela `aposta_parametros` (chave, valor jsonb) do
  Supabase, e `load_config()` sobrepõe esses valores ao YAML. Assim as premissas
  valem para o time inteiro e sobrevivem ao redeploy (disco da nuvem é efêmero).
- Com `path` explícito (testes), só o arquivo é lido/escrito — nunca o banco.

A leitura do banco é cacheada por `TTL_SEG` segundos (o app chama `load_config`
a cada rerun); `save_config` atualiza o cache na hora.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from core import fonte

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DEFAULT_CONFIG_PATH = CONFIG_DIR / "parametros.yaml"

TABELA = f"{fonte.PREFIXO}parametros"
TTL_SEG = 60
_DDL = f"""
create table if not exists public."{TABELA}" (
    chave text primary key,
    valor jsonb,
    atualizado_em timestamptz not null
)
"""
_cache: dict = {"em": 0.0, "dados": None}


def _ler_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _escrever_yaml(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)


# --------------------------------------------------------------------------- #
# Banco (sobreposição compartilhada)
# --------------------------------------------------------------------------- #
def _ler_db() -> dict:
    from sqlalchemy import text

    eng = fonte.engine()
    try:
        with eng.begin() as con:
            con.execute(text(_DDL))
            linhas = con.execute(text(f'select chave, valor from public."{TABELA}"')).fetchall()
    finally:
        eng.dispose()
    # psycopg2 já decodifica jsonb (um JSON string vira str): não re-parsear
    return {chave: valor for chave, valor in linhas}


def _gravar_db(data: dict) -> None:
    from sqlalchemy import text

    agora = datetime.now(timezone.utc)
    eng = fonte.engine()
    try:
        with eng.begin() as con:
            con.execute(text(_DDL))
            con.execute(text(f'alter table public."{TABELA}" enable row level security'))
            for chave, valor in data.items():
                con.execute(
                    text(f'insert into public."{TABELA}" (chave, valor, atualizado_em) '
                         "values (:c, cast(:v as jsonb), :a) "
                         "on conflict (chave) do update set valor = excluded.valor, "
                         "atualizado_em = excluded.atualizado_em"),
                    {"c": str(chave), "v": json.dumps(valor, ensure_ascii=False, default=str),
                     "a": agora})
    finally:
        eng.dispose()


def _sobreposicao_db() -> dict:
    agora = time.monotonic()
    if _cache["dados"] is not None and agora - _cache["em"] < TTL_SEG:
        return _cache["dados"]
    dados = _ler_db()
    _cache.update(em=agora, dados=dados)
    return dados


def invalidar_cache() -> None:
    _cache.update(em=0.0, dados=None)


# --------------------------------------------------------------------------- #
# API pública (assinatura preservada)
# --------------------------------------------------------------------------- #
def load_config(path: str | None = None) -> dict:
    """YAML + (sem `path` e com banco) valores salvos pela aba Configurações."""
    cfg = _ler_yaml(Path(path or DEFAULT_CONFIG_PATH))
    if path is None and fonte.db_url():
        cfg.update(_sobreposicao_db())
    return cfg


def save_config(data: dict, path: str | None = None) -> None:
    """Grava no YAML e, sem `path` e com banco, também no Supabase."""
    _escrever_yaml(data, Path(path or DEFAULT_CONFIG_PATH))
    if path is None and fonte.db_url():
        _gravar_db(data)
        _cache.update(em=time.monotonic(), dados=dict(data))


def onde_grava() -> str:
    """Texto curto para a interface dizer onde as premissas ficam salvas."""
    if fonte.db_url():
        return "no banco compartilhado (Supabase) — valem para o time e sobrevivem ao redeploy"
    return "em `config/parametros.yaml` desta máquina (sem DATABASE_URL configurada)"

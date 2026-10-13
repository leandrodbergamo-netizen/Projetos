"""Aceleração de venda por loja — fator por filial, válido para TODAS as apostas.

Semântica do percentual: 100 = a loja vende o que o histórico diz (padrão, não
precisa constar); 0 = não vai vender nada (sai do parque e da matriz);
120 = cresce 20% em peças. Pondera a venda projetada (lojas-equivalentes) e a
participação no rateio — ver `regra_distribuicao.fatores_aceleracao`.

Onde grava (mesmo desenho do Histórico):
- Com `DATABASE_URL` (PC via .env, nuvem via Secrets): tabela
  `aposta_aceleracao_lojas` no Supabase — compartilhada pelo time e imune ao
  redeploy (o disco do Streamlit Cloud é efêmero).
- Sem banco: chave `aceleracao_lojas` de `config/parametros.yaml`, só desta máquina.

Só lojas fora de 100% são gravadas; loja nova nasce neutra.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from core import fonte
from core.config_utils import load_config, save_config

TABELA = f"{fonte.PREFIXO}aceleracao_lojas"
CHAVE_LOCAL = "aceleracao_lojas"
PCT_MIN, PCT_MAX, PCT_NEUTRO = 0, 300, 100

_DDL = f"""
create table if not exists public."{TABELA}" (
    sk_localidade text primary key,
    pct integer not null,
    atualizado_em timestamptz not null
)
"""


def normalizar(aceleracao: Optional[dict], padrao: Optional[int] = PCT_NEUTRO) -> Dict[str, int]:
    """{sk: %} saneado: chave '484.0', % inteiro em [0, 300], sem os iguais ao
    `padrao` (loja no padrão não precisa constar; None = não descarta nada).
    Valor inválido é ignorado."""
    saida: Dict[str, int] = {}
    for loja, pct in (aceleracao or {}).items():
        try:
            chave = str(float(loja))
            v = float(pct)
        except (TypeError, ValueError):
            continue
        if v != v:                      # NaN
            continue
        p = int(round(min(max(v, PCT_MIN), PCT_MAX)))
        if padrao is None or p != padrao:
            saida[chave] = p
    return saida


# --------------------------------------------------------------------------- #
# Backend Supabase
# --------------------------------------------------------------------------- #
def _carregar_db() -> Dict[str, int]:
    from sqlalchemy import text

    eng = fonte.engine()
    try:
        with eng.begin() as con:
            con.execute(text(_DDL))
            linhas = con.execute(
                text(f'select sk_localidade, pct from public."{TABELA}"')).fetchall()
    finally:
        eng.dispose()
    return normalizar({sk: pct for sk, pct in linhas}, padrao=None)


def _salvar_db(aceleracao: Dict[str, int]) -> None:
    from sqlalchemy import text

    agora = datetime.now(timezone.utc)
    eng = fonte.engine()
    try:
        with eng.begin() as con:          # apaga-e-regrava numa transação só
            con.execute(text(_DDL))
            con.execute(text(f'alter table public."{TABELA}" enable row level security'))
            con.execute(text(f'delete from public."{TABELA}"'))
            for sk, pct in aceleracao.items():
                con.execute(
                    text(f'insert into public."{TABELA}" (sk_localidade, pct, atualizado_em) '
                         "values (:s, :p, :a)"),
                    {"s": sk, "p": int(pct), "a": agora})
    finally:
        eng.dispose()


# --------------------------------------------------------------------------- #
# Backend local (parametros.yaml)
# --------------------------------------------------------------------------- #
def _carregar_arq(caminho: Optional[Path]) -> Dict[str, int]:
    return normalizar(load_config(caminho).get(CHAVE_LOCAL), padrao=None)


def _salvar_arq(aceleracao: Dict[str, int], caminho: Optional[Path]) -> None:
    cfg = load_config(caminho)
    cfg[CHAVE_LOCAL] = dict(aceleracao)
    save_config(cfg, caminho)


# --------------------------------------------------------------------------- #
# API pública
# --------------------------------------------------------------------------- #
def carregar(caminho_local: Optional[Path] = None) -> Dict[str, int]:
    """{sk_localidade: %} das lojas fora de 100%."""
    if fonte.db_url():
        return _carregar_db()
    return _carregar_arq(caminho_local)


def salvar(aceleracao: Optional[dict], caminho_local: Optional[Path] = None,
           padrao: Optional[int] = PCT_NEUTRO) -> Dict[str, int]:
    """Substitui a configuração inteira pelo dict dado (saneado; lojas no `padrao`
    não são gravadas). Retorna o que gravou."""
    limpo = normalizar(aceleracao, padrao=padrao)
    if fonte.db_url():
        _salvar_db(limpo)
    else:
        _salvar_arq(limpo, caminho_local)
    return limpo


def onde_grava() -> str:
    """Texto curto para a interface dizer onde a configuração fica salva."""
    if fonte.db_url():
        return "no banco compartilhado (Supabase) — vale para o time e sobrevive ao redeploy"
    return "em `config/parametros.yaml` desta máquina (sem DATABASE_URL configurada)"

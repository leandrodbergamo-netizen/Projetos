"""Fixtures globais.

O `.env` do projeto tem DATABASE_URL real: nenhum teste deve tocar o Supabase.
`load_config()`, `historico` e `aceleracao` consultam `fonte.db_url()` para decidir
o backend — aqui ela é neutralizada em todos os testes.
"""
import pytest

from core import config_utils, fonte


@pytest.fixture(autouse=True)
def _sem_banco(monkeypatch):
    monkeypatch.setattr(fonte, "db_url", lambda: "")
    config_utils.invalidar_cache()
    yield
    config_utils.invalidar_cache()

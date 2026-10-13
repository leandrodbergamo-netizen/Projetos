"""Aceleração de venda por loja — backend local (YAML) e saneamento.

O `.env` do projeto tem DATABASE_URL real: o monkeypatch neutraliza para os
testes não tocarem o Supabase.
"""
import pytest

from core import aceleracao, fonte


@pytest.fixture(autouse=True)
def _sem_banco(monkeypatch):
    monkeypatch.setattr(fonte, "db_url", lambda: "")


@pytest.fixture
def arq(tmp_path):
    return tmp_path / "parametros.yaml"


class TestNormalizar:
    def test_chave_vira_sk_float_e_neutro_some(self):
        out = aceleracao.normalizar({"484": 120, 130: 0, "7.0": 100, "x": 50, "9": "abc"})
        assert out == {"484.0": 120, "130.0": 0}

    def test_limites_e_arredondamento(self):
        out = aceleracao.normalizar({"1": -20, "2": 999, "3": 119.6, "4": float("nan")})
        assert out == {"1.0": 0, "2.0": 300, "3.0": 120}

    def test_vazio(self):
        assert aceleracao.normalizar(None) == {}
        assert aceleracao.normalizar({}) == {}


class TestBackendLocal:
    def test_roundtrip_preserva_outras_chaves(self, arq):
        arq.write_text("reserva_cd_pct: 0.2\n", encoding="utf-8")
        gravado = aceleracao.salvar({"484": 120, "5": 100, "6": 0}, caminho_local=arq)
        assert gravado == {"484.0": 120, "6.0": 0}
        assert aceleracao.carregar(caminho_local=arq) == {"484.0": 120, "6.0": 0}
        from core.config_utils import load_config
        assert load_config(arq)["reserva_cd_pct"] == 0.2   # não apagou o resto

    def test_sem_arquivo_devolve_vazio(self, arq):
        assert aceleracao.carregar(caminho_local=arq) == {}

    def test_salvar_vazio_zera(self, arq):
        aceleracao.salvar({"1": 120}, caminho_local=arq)
        aceleracao.salvar({}, caminho_local=arq)
        assert aceleracao.carregar(caminho_local=arq) == {}

    def test_onde_grava_sem_banco(self):
        assert "parametros.yaml" in aceleracao.onde_grava()


class TestPadrao:
    def test_normalizar_descarta_so_o_padrao(self):
        out = aceleracao.normalizar({"1": 105, "2": 100, "3": 120}, padrao=105)
        assert out == {"2.0": 100, "3.0": 120}

    def test_normalizar_sem_padrao_mantem_tudo(self):
        out = aceleracao.normalizar({"1": 105, "2": 100}, padrao=None)
        assert out == {"1.0": 105, "2.0": 100}

    def test_carregar_mantem_loja_em_100_quando_padrao_e_outro(self, arq):
        # com padrão 105, uma loja fixada em 100 (sem crescimento) precisa sobreviver
        aceleracao.salvar({"1": 100, "2": 105}, caminho_local=arq, padrao=105)
        assert aceleracao.carregar(caminho_local=arq) == {"1.0": 100}

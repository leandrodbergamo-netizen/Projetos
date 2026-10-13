"""Premissas da aba Configurações: lojas ativas, lojas espelho e elasticidade.

Sem banco (conftest neutraliza DATABASE_URL); o cadastro de lojas é sintético.
"""
import pandas as pd
import pytest

from core import config_utils, dados
from core.espelho import projetar_aposta, velocidade_por_loja_desaz

LOJAS = pd.DataFrame({
    "sk_localidade": [122, 484, 506, 120, 456],
    "desc_nome": ["Souq Sp Iguatemi Sao Paul", "Souq Casa Jardins", "Souq Florianópolis",
                  "Souq Bh Diamond", "CDES Vendas SOUQ"],
    "Marca": ["SOUQ"] * 5,
    "canal": ["Lojas", "Lojas", "Lojas", "Lojas", "Ecommerce"],
    "dt_fechamento": [pd.NaT, pd.NaT, pd.NaT, pd.Timestamp("2025-04-20"), pd.NaT],
    "dt_abertura": [pd.Timestamp("2017-09-04")] * 5,
    "Perfil": ["A", "A", "AB", "AB", None],
    "Temperatura": ["Híbrido"] * 4 + [None],
})


@pytest.fixture(autouse=True)
def _lojas_fake(monkeypatch):
    monkeypatch.setattr(dados, "carregar_lojas", lambda caminho=None, forcar=False: LOJAS.copy())


class TestLojasAtivas:
    def test_fechada_na_base_sai_sempre(self):
        out = dados.lojas_alvo_souq(cfg={})
        assert set(out["sk_localidade"]) == {122, 484, 506}

    def test_inativa_na_config_sai_do_parque(self):
        out = dados.lojas_alvo_souq(cfg={"lojas_inativas": ["506.0"]})
        assert set(out["sk_localidade"]) == {122, 484}

    def test_chave_invalida_e_ignorada(self):
        out = dados.lojas_alvo_souq(cfg={"lojas_inativas": ["x", 122]})
        assert set(out["sk_localidade"]) == {484, 506}


class TestLojasEspelho:
    def test_yaml_e_lido_quando_config_vazia(self):
        regras = dados.espelhos_loja_nova(cfg={})
        assert regras["484.0"][0] == "122.0"
        assert regras["484.0"][1] == pytest.approx(0.50)

    def test_config_sobrepoe_fator_e_espelho(self):
        regras = dados.espelhos_loja_nova(cfg={"lojas_espelho": {
            "484.0": {"espelho": "506.0", "fator": 0.5}}})
        assert regras["484.0"][:2] == ("506.0", 0.5)
        assert regras["484.0"][3] == "Souq Florianópolis"

    def test_config_desliga_regra_do_yaml(self):
        regras = dados.espelhos_loja_nova(cfg={"lojas_espelho": {"484.0": {"espelho": None}}})
        assert "484.0" not in regras

    def test_espelho_desconhecido_e_ignorado(self):
        regras = dados.espelhos_loja_nova(cfg={"lojas_espelho": {"484.0": {"espelho": "999.0"}}})
        assert regras["484.0"][0] == "122.0"     # YAML segue valendo


class TestElasticidade:
    def _vel(self):
        v = pd.DataFrame([{"dt_transacao": pd.Timestamp("2024-01-03"), "sk_localidade": 1,
                           "qtd_produto": 10, "cod_sku_pai": "X"},
                          {"dt_transacao": pd.Timestamp("2024-01-03"), "sk_localidade": 456,
                           "qtd_produto": 5, "cod_sku_pai": "X"}])
        curva = pd.DataFrame({"semana": list(range(1, 54)), "indice": [100.0] * 53})
        return velocidade_por_loja_desaz(v, "X", curva, ecom_locs={456}), curva

    def test_multiplica_fisico_e_ecom(self):
        ve, curva = self._vel()
        base = projetar_aposta([ve], curva, "2024-01-01", 20, horizonte_semanas=10,
                               aproveitamento=1.0, reserva_cd_pct=0.0)
        mais = projetar_aposta([ve], curva, "2024-01-01", 20, horizonte_semanas=10,
                               aproveitamento=1.0, reserva_cd_pct=0.0, elasticidade=0.10)
        assert mais.venda_projetada == pytest.approx(base.venda_projetada * 1.10)
        assert mais.venda_ecom == pytest.approx(base.venda_ecom * 1.10)
        assert mais.elasticidade == pytest.approx(0.10)
        assert any("Elasticidade" in a for a in mais.avisos)
        assert not any("Elasticidade" in a for a in base.avisos)

    def test_negativa_reduz(self):
        ve, curva = self._vel()
        base = projetar_aposta([ve], curva, "2024-01-01", 20, horizonte_semanas=10,
                               aproveitamento=1.0, reserva_cd_pct=0.0)
        menos = projetar_aposta([ve], curva, "2024-01-01", 20, horizonte_semanas=10,
                                aproveitamento=1.0, reserva_cd_pct=0.0, elasticidade=-0.2)
        assert menos.venda_projetada == pytest.approx(base.venda_projetada * 0.8)


class TestConfigSemBanco:
    def test_roundtrip_em_arquivo(self, tmp_path):
        arq = tmp_path / "p.yaml"
        config_utils.save_config({"elasticidade_pct": 10, "lojas_inativas": ["506.0"]}, path=arq)
        cfg = config_utils.load_config(arq)
        assert cfg == {"elasticidade_pct": 10, "lojas_inativas": ["506.0"]}

    def test_sem_banco_nao_consulta_db(self, monkeypatch):
        chamou = []
        monkeypatch.setattr(config_utils, "_ler_db", lambda: chamou.append(1) or {})
        config_utils.load_config()
        assert not chamou

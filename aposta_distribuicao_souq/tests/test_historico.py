"""Testes do histórico no backend de arquivo (fallback sem banco).

O `.env` do projeto tem DATABASE_URL real: o monkeypatch abaixo a neutraliza
para os testes NUNCA gravarem no Supabase de produção.
"""
import pandas as pd
import pytest

from core import fonte, historico


@pytest.fixture(autouse=True)
def _sem_banco(monkeypatch):
    monkeypatch.setattr(fonte, "db_url", lambda: "")


@pytest.fixture()
def arq(tmp_path):
    return tmp_path / "historico.jsonl"


class TestHistoricoArquivo:
    def test_salvar_e_listar_roundtrip(self, arq):
        id_ = historico.salvar("VESTIDO/Linho · R$798", {
            "aposta_total": 125.0,
            "espelhos": ["04.26.11.497.004"],
            "participacoes_hist": {"122.0": 0.5, "109.0": 0.5},
        }, caminho_local=arq)
        df = historico.listar(caminho_local=arq)
        assert len(df) == 1 and df.iloc[0]["id"] == id_
        p = df.iloc[0]["payload"]
        assert p["aposta_total"] == 125.0
        assert p["participacoes_hist"]["122.0"] == 0.5   # chaves str preservadas

    def test_lista_do_mais_recente_para_o_mais_antigo(self, arq):
        a = historico.salvar("primeiro", {"aposta_total": 1}, caminho_local=arq)
        b = historico.salvar("segundo", {"aposta_total": 2}, caminho_local=arq)
        df = historico.listar(caminho_local=arq)
        assert df["id"].tolist() == [b, a]

    def test_excluir_remove_so_o_escolhido(self, arq):
        a = historico.salvar("fica", {"aposta_total": 1}, caminho_local=arq)
        b = historico.salvar("sai", {"aposta_total": 2}, caminho_local=arq)
        historico.excluir(b, caminho_local=arq)
        df = historico.listar(caminho_local=arq)
        assert df["id"].tolist() == [a]

    def test_linha_corrompida_nao_derruba_a_leitura(self, arq):
        historico.salvar("ok", {"aposta_total": 1}, caminho_local=arq)
        with arq.open("a", encoding="utf-8") as fh:
            fh.write("{json quebrado...\n")
        assert len(historico.listar(caminho_local=arq)) == 1

    def test_listar_sem_arquivo_devolve_vazio(self, arq):
        df = historico.listar(caminho_local=arq)
        assert df.empty and list(df.columns) == ["id", "criado_em", "resumo", "payload"]

    def test_payload_com_timestamp_serializa(self, arq):
        # default=str no json.dumps: Timestamp não pode explodir o save
        historico.salvar("com data", {"dt": pd.Timestamp("2026-07-17")}, caminho_local=arq)
        assert len(historico.listar(caminho_local=arq)) == 1

    def test_obter_por_id(self, arq):
        a = historico.salvar("um", {"aposta_total": 1}, caminho_local=arq)
        historico.salvar("dois", {"aposta_total": 2}, caminho_local=arq)
        reg = historico.obter(a, caminho_local=arq)
        assert reg["resumo"] == "um" and reg["payload"]["aposta_total"] == 1

    def test_obter_id_inexistente_retorna_none(self, arq):
        historico.salvar("um", {"aposta_total": 1}, caminho_local=arq)
        assert historico.obter("nao-existe", caminho_local=arq) is None

    def test_atualizar_substitui_payload_e_preserva_criado_em(self, arq):
        a = historico.salvar("cenario", {"aposta_total": 100}, caminho_local=arq)
        b = historico.salvar("outro", {"aposta_total": 5}, caminho_local=arq)
        antes = historico.obter(a, caminho_local=arq)["criado_em"]
        historico.atualizar(a, {"aposta_total": 100, "aposta_final": 120.0,
                                "distribuido_editado": 96}, caminho_local=arq)
        df = historico.listar(caminho_local=arq)
        assert len(df) == 2                                   # nenhuma linha nova
        reg = historico.obter(a, caminho_local=arq)
        assert reg["payload"]["aposta_final"] == 120.0
        assert reg["criado_em"] == antes
        assert historico.obter(b, caminho_local=arq)["payload"]["aposta_total"] == 5

    def test_atualizar_pode_trocar_o_resumo(self, arq):
        a = historico.salvar("antigo", {"aposta_total": 1}, caminho_local=arq)
        historico.atualizar(a, {"aposta_total": 1}, resumo="novo", caminho_local=arq)
        assert historico.obter(a, caminho_local=arq)["resumo"] == "novo"

    def test_atualizar_id_inexistente_levanta_keyerror(self, arq):
        historico.salvar("um", {"aposta_total": 1}, caminho_local=arq)
        with pytest.raises(KeyError):
            historico.atualizar("nao-existe", {"x": 1}, caminho_local=arq)


class TestNormalizarPayload:
    def test_payload_v1_ganha_faixas_parque_e_aposta_final(self):
        v1 = {"resumo": "VESTIDO/Linho · R$498 · faixa P2 · INVERNO 2027",
              "aposta_total": 90.0,
              "inputs": {"subgrupo": "VESTIDO", "tecido": "Linho",
                         "preco": 498.0, "faixa": "P2", "grupo_faixa": "TECIDO PLANO"}}
        p = historico.normalizar_payload(v1)
        assert p["inputs"]["faixas"] == ["P2"]
        assert p["inputs"]["preco"] == 498.0            # preservado para exibição
        assert p["parque"] == {"perfis": None, "climas": None, "n_lojas_alvo": None}
        assert p["aposta_final"] == 90.0
        assert p["curva_origem"] == {}

    def test_payload_v1_sem_faixa_fica_com_lista_vazia(self):
        p = historico.normalizar_payload({"aposta_total": 10, "inputs": {}})
        assert p["inputs"]["faixas"] == []

    def test_payload_v2_passa_intacto(self):
        v2 = {"versao": 2, "aposta_total": 50.0, "aposta_final": 70.0,
              "parque": {"perfis": ["A"], "climas": None, "n_lojas_alvo": 12},
              "inputs": {"faixas": ["P1", "P4"]}, "curva_origem": {"42|M": "espelhos"}}
        p = historico.normalizar_payload(v2)
        assert p["inputs"]["faixas"] == ["P1", "P4"]
        assert p["aposta_final"] == 70.0
        assert p["parque"]["perfis"] == ["A"]
        assert p["curva_origem"] == {"42|M": "espelhos"}

    def test_nao_muta_o_dict_original(self):
        v1 = {"inputs": {"faixa": "P3"}}
        historico.normalizar_payload(v1)
        assert "faixas" not in v1["inputs"]

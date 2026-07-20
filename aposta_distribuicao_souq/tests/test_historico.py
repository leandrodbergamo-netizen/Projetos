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

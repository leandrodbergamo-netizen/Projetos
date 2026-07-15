from datetime import date

import pandas as pd
import pytest

from core.sazonalidade import (fator_janela, feriados_br, indice_semanal,
                               marcar_feriados, semanas_equivalentes)


def _vendas(registros):
    """registros = [(data, loja, qtd)]"""
    return pd.DataFrame(
        [{"dt_transacao": pd.Timestamp(d), "sk_localidade": l, "qtd_produto": q}
         for d, l, q in registros]
    )


class TestIndiceSemanal:
    def test_vazio(self):
        assert indice_semanal(_vendas([])).empty

    def test_media_do_indice_e_100(self):
        # duas semanas com volumes diferentes -> média dos índices = 100
        reg = [("2024-01-03", 1, 10), ("2024-01-10", 1, 30)]
        cur = indice_semanal(_vendas(reg))
        assert cur["indice"].mean() == pytest.approx(100.0)

    def test_normaliza_por_loja_ativa(self):
        # semana A: 1 loja vende 10 (10/loja). semana B: 2 lojas vendem 20 (10/loja).
        # Volume dobrou, mas por-loja é igual => índices iguais (controla a frota).
        reg = [("2024-01-03", 1, 10),
               ("2024-01-10", 1, 10), ("2024-01-10", 2, 10)]
        cur = indice_semanal(_vendas(reg)).set_index("semana")["indice"]
        assert cur.iloc[0] == pytest.approx(cur.iloc[1])


class TestFatorJanela:
    def test_curva_vazia_e_neutra(self):
        assert fator_janela(pd.DataFrame(), "2024-01-01", "2024-03-01") == 100.0

    def test_janela_quente_acima_de_100(self):
        curva = pd.DataFrame({"semana": [1, 2], "indice": [50.0, 150.0]})
        # 08/01/2024 cai na semana ISO 2 (a "quente")
        assert fator_janela(curva, "2024-01-08", "2024-01-10") == pytest.approx(150.0)

    def test_janela_sem_intersecao_e_neutra(self):
        curva = pd.DataFrame({"semana": [1], "indice": [50.0]})
        assert fator_janela(curva, "2024-06-01", "2024-06-05") == 100.0


class TestSemanasEquivalentes:
    def test_curva_neutra_devolve_o_horizonte(self):
        curva = pd.DataFrame({"semana": list(range(1, 54)), "indice": [100.0] * 53})
        assert semanas_equivalentes(curva, "2024-01-01", 12) == pytest.approx(12.0)

    def test_entrada_em_alta_temporada_vale_mais_que_o_horizonte(self):
        idx = [100.0] * 53
        for w in (2, 3, 4):
            idx[w - 1] = 300.0
        curva = pd.DataFrame({"semana": list(range(1, 54)), "indice": idx})
        assert semanas_equivalentes(curva, "2024-01-08", 4) > 4.0

    def test_horizonte_zero(self):
        curva = pd.DataFrame({"semana": [1], "indice": [100.0]})
        assert semanas_equivalentes(curva, "2024-01-01", 0) == 0


class TestFeriados:
    def test_feriados_fixos_e_moveis(self):
        f = feriados_br(2024)
        assert f[date(2024, 12, 25)] == "Natal"
        assert f[date(2024, 5, 1)] == "Trabalho"
        # Páscoa 2024 = 31/03 -> Carnaval (ter) = 13/02
        assert f[date(2024, 2, 13)] == "Carnaval (ter)"

    def test_marcar_feriados_sinaliza_semana_e_emenda(self):
        curva = pd.DataFrame({"semana": [52], "indice": [300.0]})
        out = marcar_feriados(curva, (2024,))
        assert "Natal" in out.loc[0, "feriado"]
        # 25/12/2024 é quarta -> sem ponte; a coluna deve existir mesmo assim
        assert "tem_emenda" in out.columns

    def test_temporada_de_natal_comeca_3_semanas_antes(self):
        # regra de negócio: a venda de Natal arranca ~3 semanas antes do dia 25.
        # 25/12/2024 cai na semana ISO 52 -> temporada = semanas 49..52.
        curva = pd.DataFrame({"semana": list(range(47, 53)), "indice": [100.0] * 6})
        temp = marcar_feriados(curva, (2024,)).set_index("semana")["temporada"]
        assert temp[52] == "Natal"          # semana do evento
        assert temp[49] == "Natal"          # 3 semanas antes: início da rampa
        assert temp[48] == ""               # fora da janela
        assert temp[47] == ""

    def test_antecedencia_configuravel(self):
        curva = pd.DataFrame({"semana": list(range(50, 53)), "indice": [100.0] * 3})
        temp = marcar_feriados(curva, (2024,), antecedencia={"Natal": 1}).set_index("semana")["temporada"]
        assert temp[52] == "Natal" and temp[51] == "Natal"
        assert temp[50] == ""

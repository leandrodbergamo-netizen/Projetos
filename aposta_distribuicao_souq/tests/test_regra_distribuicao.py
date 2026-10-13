import pytest

from core.regra_distribuicao import (
    reservar_cd,
    distribuir_por_participacao,
    aplicar_grade_minima,
    normalizar_curva,
    abrir_por_tamanho,
    arredondar_maior_resto,
    distribuir,
)


# --------------------------------------------------------------------------- #
# reservar_cd
# --------------------------------------------------------------------------- #
def test_reservar_cd():
    reserva, disponivel = reservar_cd(100.0, 0.20)
    assert reserva == 20.0
    assert disponivel == 80.0


def test_reservar_cd_pct_invalido():
    with pytest.raises(ValueError):
        reservar_cd(100.0, 1.0)


# --------------------------------------------------------------------------- #
# distribuir_por_participacao
# --------------------------------------------------------------------------- #
def test_participacao_proporcional_sem_teto():
    aloc = distribuir_por_participacao(100.0, {"A": 3.0, "B": 1.0})
    assert aloc["A"] == pytest.approx(75.0)
    assert aloc["B"] == pytest.approx(25.0)


def test_participacao_normaliza_pesos():
    # participações que não somam 1 devem ser normalizadas
    aloc = distribuir_por_participacao(90.0, {"A": 30.0, "B": 60.0})
    assert aloc["A"] == pytest.approx(30.0)
    assert aloc["B"] == pytest.approx(60.0)


def test_participacao_com_teto_redistribui_excedente():
    # A pediria 75 mas o teto é 40; excedente vai para B
    aloc = distribuir_por_participacao(100.0, {"A": 3.0, "B": 1.0}, tetos={"A": 40.0})
    assert aloc["A"] == pytest.approx(40.0)
    assert aloc["B"] == pytest.approx(60.0)
    assert sum(aloc.values()) == pytest.approx(100.0)


def test_participacao_soma_zero_erro():
    with pytest.raises(ValueError):
        distribuir_por_participacao(100.0, {"A": 0.0, "B": 0.0})


# --------------------------------------------------------------------------- #
# aplicar_grade_minima
# --------------------------------------------------------------------------- #
def test_grade_minima_corta_e_redistribui():
    # C recebe 5 (< grade 10) => cortada, quota vai para A e B
    dist = {"A": 50.0, "B": 45.0, "C": 5.0}
    part = {"A": 50.0, "B": 45.0, "C": 5.0}
    res = aplicar_grade_minima(dist, grade_minima=10.0, participacoes=part)
    assert res["C"] == 0.0
    assert sum(res.values()) == pytest.approx(100.0)
    assert res["A"] > 50.0 and res["B"] > 45.0


def test_grade_minima_todas_abaixo_zera_tudo():
    dist = {"A": 3.0, "B": 2.0}
    res = aplicar_grade_minima(dist, grade_minima=10.0)
    assert sum(res.values()) == 0.0


# --------------------------------------------------------------------------- #
# curva por tamanho
# --------------------------------------------------------------------------- #
def test_normalizar_curva():
    c = normalizar_curva({"P": 1.0, "M": 2.0, "G": 1.0})
    assert c["M"] == pytest.approx(0.5)
    assert sum(c.values()) == pytest.approx(1.0)


def test_normalizar_curva_soma_zero_uniforme():
    c = normalizar_curva({"P": 0.0, "M": 0.0})
    assert c["P"] == pytest.approx(0.5)
    assert c["M"] == pytest.approx(0.5)


def test_abrir_por_tamanho():
    aberto = abrir_por_tamanho(100.0, {"P": 1.0, "M": 2.0, "G": 1.0})
    assert aberto["M"] == pytest.approx(50.0)


# --------------------------------------------------------------------------- #
# arredondamento por maior resto
# --------------------------------------------------------------------------- #
def test_maior_resto_preserva_total():
    valores = {"A": 33.34, "B": 33.33, "C": 33.33}
    res = arredondar_maior_resto(valores, total_alvo=100)
    assert sum(res.values()) == 100
    # A tem o maior resto fracionário -> recebe a unidade extra
    assert res["A"] == 34


def test_maior_resto_infere_total():
    valores = {"A": 1.5, "B": 1.5, "C": 1.0}
    res = arredondar_maior_resto(valores)
    assert sum(res.values()) == 4


# --------------------------------------------------------------------------- #
# pipeline completo
# --------------------------------------------------------------------------- #
def test_pipeline_soma_bate_e_matriz_consistente():
    resultado = distribuir(
        aposta_total=1000.0,
        participacoes={"L1": 0.5, "L2": 0.3, "L3": 0.2},
        curva_tamanhos={"P": 1.0, "M": 2.0, "G": 1.0},
        reserva_cd_pct=0.20,
        grade_minima=0.0,
    )
    assert resultado.reserva_cd == pytest.approx(200.0)
    assert resultado.disponivel_lojas == pytest.approx(800.0)
    # total distribuído respeita o disponível
    assert resultado.total_distribuido() <= 800
    # cada linha da matriz soma a quantidade da loja
    for loja, qtd in resultado.distribuicao_loja.items():
        assert sum(resultado.matriz[loja].values()) == qtd


def test_pipeline_com_teto_gera_sobra_para_cd():
    # tetos baixos forçam sobra de volta ao CD
    resultado = distribuir(
        aposta_total=1000.0,
        participacoes={"L1": 0.5, "L2": 0.5},
        curva_tamanhos={"U": 1.0},
        reserva_cd_pct=0.0,
        velocidades_semanais={"L1": 50.0, "L2": 50.0},
        cobertura_max_semanas=4.0,  # teto 200 por loja => 400 total < 1000
    )
    assert resultado.total_distribuido() <= 400
    assert resultado.sobra_para_cd > 0
    assert any("CD" in a for a in resultado.avisos)


# --------------------------------------------------------------------------- #
# Aceleração de venda por loja
# --------------------------------------------------------------------------- #
from core.regra_distribuicao import (acelerar_participacao, fatores_aceleracao,  # noqa: E402
                                     lojas_com_aceleracao, lojas_equivalentes)


class TestAceleracaoLojas:
    def test_fatores_convertem_percentual_e_normalizam_chave(self):
        f = fatores_aceleracao({"122.0": 120, 130: 0, "7": "80", "x": 50, "9": "abc", "5": -10})
        assert f["122.0"] == pytest.approx(1.2)
        assert f["130.0"] == 0.0
        assert f["7.0"] == pytest.approx(0.8)
        assert f["5.0"] == 0.0                 # negativo vira 0
        assert "x" not in f and "9.0" not in f  # inválidos ignorados
        assert fatores_aceleracao(None) == {}

    def test_loja_em_zero_sai_do_parque(self):
        f = fatores_aceleracao({"2.0": 0})
        assert lojas_com_aceleracao(["1.0", "2.0", "3.0"], f) == ["1.0", "3.0"]

    def test_lojas_equivalentes_soma_fatores_com_default_1(self):
        f = fatores_aceleracao({"1.0": 120, "2.0": 0})
        # 1.2 + 0 + 1 (sem fator) = 2.2
        assert lojas_equivalentes(["1.0", "2.0", "3.0"], f) == pytest.approx(2.2)
        assert lojas_equivalentes(["1.0", "3.0"], {}) == 2.0

    def test_acelerar_participacao_pondera_e_renormaliza(self):
        part = {"1.0": 0.5, "2.0": 0.3, "3.0": 0.2}
        f = fatores_aceleracao({"1.0": 120, "3.0": 0})
        out = acelerar_participacao(part, f)
        assert "3.0" not in out                       # 0% sai do rateio
        assert sum(out.values()) == pytest.approx(1.0)
        # 0.6 : 0.3 => 2/3 : 1/3
        assert out["1.0"] == pytest.approx(2 / 3)
        assert out["2.0"] == pytest.approx(1 / 3)

    def test_sem_fatores_e_identidade(self):
        part = {"1.0": 0.5, "2.0": 0.5}
        assert acelerar_participacao(part, {}) == pytest.approx(part)

    def test_tudo_zero_devolve_vazio(self):
        assert acelerar_participacao({"1.0": 1.0}, {"1.0": 0.0}) == {}

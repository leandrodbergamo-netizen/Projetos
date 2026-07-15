import pandas as pd
import pytest

from core.dados import (
    filtrar_full_price,
    velocidade_por_produto,
    curva_tamanhos,
    participacao_lojas,
)


@pytest.fixture
def vendas():
    return pd.DataFrame(
        {
            "cod_sku_pai": ["A", "A", "A", "B", "B", "C"],
            "sk_produto": [1, 1, 2, 3, 3, 4],
            "sk_localidade": [10, 10, 20, 10, 20, 20],
            "linha": ["ROUPA", "ROUPA", "ROUPA", "ROUPA", "ACESSORIO", "ROUPA"],
            "cod_canal": [1, 1, 1, 1, 1, 2],
            "flag_liquidacao": [0, 0, 0, 0, 0, 1],  # C está em liquidação
            "tipo_venda": ["venda", "troca", "venda", "venda", "venda", "venda"],
            "qtd_produto": [5, -1, 3, 2, 4, 9],
            "dt_transacao": pd.to_datetime(
                ["2025-01-01", "2025-01-02", "2025-01-15", "2025-01-01", "2025-01-01", "2025-01-01"]
            ),
        }
    )


@pytest.fixture
def produtos():
    return pd.DataFrame(
        {
            "sk_produto": [1, 2, 3, 4],
            "desc_tamanho": ["P", "M", "P", None],
            "desc_grupo_wgb": ["MALHA", "MALHA", "TRICOT", "MALHA"],
        }
    )


def test_filtrar_full_price_exclui_liquidacao_troca_e_linha(vendas):
    fp = filtrar_full_price(vendas, linhas=("ROUPA",))
    # remove troca (linha 2), liquidação (C) e linha ACESSORIO
    assert set(fp["cod_sku_pai"]) == {"A", "B"}
    assert (fp["tipo_venda"] == "venda").all()
    assert (fp["flag_liquidacao"] == 0).all()
    # B com linha ACESSORIO some, resta só o registro ROUPA de B
    assert len(fp) == 3


def test_velocidade_por_produto(vendas):
    fp = filtrar_full_price(vendas, linhas=("ROUPA",))
    vel = velocidade_por_produto(fp).set_index("cod_sku_pai")
    # A: 5 + 3 = 8 unidades, de 01-01 a 15-01 => 14 dias => 3 semanas
    assert vel.loc["A", "unidades"] == 8
    assert vel.loc["A", "semanas_ativas"] == pytest.approx(3.0)
    assert vel.loc["A", "velocidade_semanal"] == pytest.approx(8 / 3)
    # B: 2 unidades, um único dia => 1 semana
    assert vel.loc["B", "semanas_ativas"] == 1.0
    assert vel.loc["B", "velocidade_semanal"] == pytest.approx(2.0)


def test_curva_tamanhos_com_filtro_de_grupo(vendas, produtos):
    fp = filtrar_full_price(vendas, linhas=("ROUPA",))
    curva = curva_tamanhos(fp, produtos, filtro={"desc_grupo_wgb": "MALHA"})
    # MALHA: sku 1 (P, 5 un) e sku 2 (M, 3 un) => P=5/8, M=3/8
    assert curva["P"] == pytest.approx(5 / 8)
    assert curva["M"] == pytest.approx(3 / 8)
    assert sum(curva.values()) == pytest.approx(1.0)


def test_participacao_lojas(vendas):
    fp = filtrar_full_price(vendas, linhas=("ROUPA",))
    part = participacao_lojas(fp)
    # loja 10: A=5, B=2 => 7 ; loja 20: A=3 => 3 ; total 10
    assert part["10"] == pytest.approx(0.7)
    assert part["20"] == pytest.approx(0.3)


def test_curva_vazia_sem_dados():
    assert curva_tamanhos(pd.DataFrame(), pd.DataFrame()) == {}

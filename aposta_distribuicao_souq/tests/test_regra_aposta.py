from core.regra_aposta import calcular_aposta


def test_calculo_simples():
    espelhos = [
        {"sku": "SKU-001", "velocidade_desazonalizada": 24.0},
        {"sku": "SKU-002", "velocidade_desazonalizada": 18.0},
    ]
    pesos = {"SKU-001": 1.0, "SKU-002": 1.0}
    resultado = calcular_aposta(espelhos, pesos, aproveitamento=0.70, reserva_cd_pct=0.20)
    assert resultado.velocidade_referencia == 21.0
    assert resultado.venda_projetada == 84.0
    assert resultado.aposta_sugerida == 120.0
    assert resultado.reserva_cd == 24.0
    assert resultado.restante_lojas == 96.0

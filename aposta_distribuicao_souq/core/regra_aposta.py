from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List


@dataclass
class ApostaResultado:
    velocidade_referencia: float
    venda_projetada: float
    aposta_sugerida: float
    reserva_cd: float
    restante_lojas: float


def calcular_aposta(espelhos: List[dict], pesos: Dict[str, float], aproveitamento: float = 0.70, reserva_cd_pct: float = 0.20) -> ApostaResultado:
    if not espelhos:
        raise ValueError("É necessário selecionar pelo menos um espelho")
    total_peso = sum(pesos.get(item["sku"], 1.0) for item in espelhos)
    if total_peso <= 0:
        raise ValueError("Pesos devem somar um valor positivo")

    velocidade_referencia = round(
        sum((item.get("velocidade_desazonalizada", 0.0) * pesos.get(item["sku"], 1.0)) for item in espelhos) / total_peso,
        10,
    )
    venda_projetada = round(velocidade_referencia * 4.0, 10)
    aposta_sugerida = round(venda_projetada / aproveitamento, 10)
    reserva_cd = round(aposta_sugerida * reserva_cd_pct, 10)
    restante_lojas = round(aposta_sugerida - reserva_cd, 10)

    return ApostaResultado(
        velocidade_referencia=velocidade_referencia,
        venda_projetada=venda_projetada,
        aposta_sugerida=aposta_sugerida,
        reserva_cd=reserva_cd,
        restante_lojas=restante_lojas,
    )

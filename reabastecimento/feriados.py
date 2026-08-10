"""Calendário de feriados nacionais (BR) e efeito de emendas em vendas full price.

Regras (premissa, calibrável):
- Feriado em **terça** ou **quinta** -> emenda de 4 dias -> efeito negativo maior.
- Feriado em **segunda** ou **sexta** -> fim de semana de 3 dias -> efeito negativo.
- Feriado em **quarta** -> sem emenda natural -> neutro.
- Feriado no fim de semana -> neutro.
Os fatores (<1 = queda) são parâmetros iniciais para ajustar com o histórico.
"""
from __future__ import annotations

from datetime import date, timedelta

# Fatores aplicados à SEMANA do feriado (full price). Calibrar com dados.
FATOR_EMENDA_4D = 0.85   # terça/quinta
FATOR_EMENDA_3D = 0.92   # segunda/sexta
FATOR_QUARTA = 1.00      # quarta: neutro
FATOR_FDS = 1.00         # sábado/domingo: neutro


def _pascoa(ano: int) -> date:
    """Domingo de Páscoa (algoritmo de Gauss/Computus)."""
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return date(ano, mes, dia)


def feriados_nacionais(ano: int) -> dict[date, str]:
    pa = _pascoa(ano)
    return {
        date(ano, 1, 1): "Confraternização",
        pa - timedelta(days=48): "Carnaval (segunda)",
        pa - timedelta(days=47): "Carnaval (terça)",
        pa - timedelta(days=2): "Sexta-feira Santa",
        date(ano, 4, 21): "Tiradentes",
        date(ano, 5, 1): "Dia do Trabalho",
        pa + timedelta(days=60): "Corpus Christi",
        date(ano, 9, 7): "Independência",
        date(ano, 10, 12): "N. Sra. Aparecida",
        date(ano, 11, 2): "Finados",
        date(ano, 11, 15): "Proclamação da República",
        date(ano, 12, 25): "Natal",
    }


def dia_das_maes(ano: int) -> date:
    """2º domingo de maio."""
    d = date(ano, 5, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)  # 1º domingo
    return d + timedelta(days=7)


def _fator_feriado(d: date) -> float:
    wd = d.weekday()  # 0=seg ... 6=dom
    if wd in (1, 3):       # terça, quinta
        return FATOR_EMENDA_4D
    if wd in (0, 4):       # segunda, sexta
        return FATOR_EMENDA_3D
    if wd == 2:            # quarta
        return FATOR_QUARTA
    return FATOR_FDS       # fim de semana


def fator_semana(ano: int, isoweek: int) -> float:
    """Produto dos fatores dos feriados que caem na semana ISO informada."""
    fator = 1.0
    for d in feriados_nacionais(ano):
        if d.isocalendar()[1] == isoweek and d.year == ano:
            fator *= _fator_feriado(d)
    return fator

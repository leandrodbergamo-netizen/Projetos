"""Sazonalidade semanal da linha ROUPA/Souq.

A curva é um índice por semana ISO (base 100 = semana média), normalizado
**por loja ativa** para separar sazonalidade real de mudança de parque (abertura/
fechamento de loja). É calculada com múltiplos anos (média das semanas equivalentes)
e por nível subgrupo/tecido, com fallback para grupo/geral quando falta amostra.

Usos:
- `fator_janela`  -> índice médio da janela em que o espelho vendeu (desazonaliza).
- `semanas_equivalentes` -> "semanas-equivalentes" da vida do produto novo, que já
  embute o efeito sazonal da janela de entrada (resolve o gross-up de cobertura).

Emendas de feriado: `feriados_br` fornece o calendário nacional (inclui móveis por
Páscoa) e `marcar_feriados` sinaliza as semanas afetadas para inspeção/ajuste.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from typing import Optional

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- #
# Índice semanal por loja ativa
# --------------------------------------------------------------------------- #
def indice_semanal(
    vendas_fp: pd.DataFrame,
    col_loja: str = "sk_localidade",
    col_qtd: str = "qtd_produto",
    col_data: str = "dt_transacao",
) -> pd.DataFrame:
    """Índice sazonal semanal (base 100 = semana média), unid ÷ loja ativa.

    Para cada (ano, semana ISO): unid / nº de lojas com venda naquela semana.
    Depois faz a média entre anos por semana e reescala para média 100.
    Retorna colunas [semana, indice, unid, lojas_med, n_anos].
    """
    cols = ["semana", "indice", "unid", "lojas_med", "n_anos"]
    if vendas_fp.empty or col_data not in vendas_fp.columns:
        return pd.DataFrame(columns=cols)
    df = vendas_fp.dropna(subset=[col_data])
    if df.empty:
        return pd.DataFrame(columns=cols)

    iso = df[col_data].dt.isocalendar()
    base = pd.DataFrame({
        "ano": iso["year"].values,
        "semana": iso["week"].values,
        "qtd": df[col_qtd].values,
        "loja": df[col_loja].values,
    })
    por_ano = base.groupby(["ano", "semana"]).agg(
        unid=("qtd", "sum"), lojas=("loja", "nunique")
    ).reset_index()
    por_ano["por_loja"] = por_ano["unid"] / por_ano["lojas"]

    agg = por_ano.groupby("semana").agg(
        por_loja=("por_loja", "mean"),
        unid=("unid", "sum"),
        lojas_med=("lojas", "mean"),
        n_anos=("ano", "nunique"),
    ).reset_index()
    media = agg["por_loja"].mean()
    agg["indice"] = 100.0 * agg["por_loja"] / media if media > 0 else 100.0
    return agg[cols]


def curva_por(
    vendas_fp: pd.DataFrame,
    subgrupo: Optional[str] = None,
    material: Optional[str] = None,
    col_subgrupo: str = "subgrupo",
    col_material: str = "grupo_material",
    min_amostra: int = 800,
) -> tuple[pd.DataFrame, str]:
    """Curva semanal no nível mais específico com amostra suficiente.

    Tenta subgrupo+material -> subgrupo -> geral, exigindo `min_amostra` unidades.
    Retorna (curva, nivel_usado).
    """
    tentativas = []
    if subgrupo is not None and material is not None and col_material in vendas_fp.columns:
        tentativas.append((
            f"subgrupo+material={subgrupo}/{material}",
            (vendas_fp[col_subgrupo] == subgrupo) & (vendas_fp[col_material] == material),
        ))
    if subgrupo is not None:
        tentativas.append((f"subgrupo={subgrupo}", vendas_fp[col_subgrupo] == subgrupo))
    tentativas.append(("geral", pd.Series(True, index=vendas_fp.index)))

    for nivel, mask in tentativas:
        sub = vendas_fp[mask]
        if sub["qtd_produto"].sum() >= min_amostra:
            return indice_semanal(sub), nivel
    return indice_semanal(vendas_fp), "geral"


# --------------------------------------------------------------------------- #
# Fatores para desazonalização / reprojeção
# --------------------------------------------------------------------------- #
def _semanas_no_intervalo(dt_inicio, dt_fim, max_semanas: int = 53) -> list[int]:
    """Lista de semanas ISO cobertas por [dt_inicio, dt_fim] (distintas)."""
    d0, d1 = pd.Timestamp(dt_inicio), pd.Timestamp(dt_fim)
    if pd.isna(d0) or pd.isna(d1) or d1 < d0:
        return []
    semanas, atual, i = [], d0, 0
    while atual <= d1 and i <= max_semanas * 7:
        semanas.append(int(atual.isocalendar().week))
        atual += timedelta(days=7)
        i += 7
    # se cobre o ano todo, todas as semanas
    return list(dict.fromkeys(semanas))


def fator_janela(curva: pd.DataFrame, dt_inicio, dt_fim) -> float:
    """Índice médio (100=neutro) das semanas em que o espelho vendeu.

    >100 => janela quente (velocidade observada infla); <100 => janela fraca.
    Sem interseção com a curva => 100 (neutro).
    """
    if curva.empty:
        return 100.0
    idx = curva.set_index("semana")["indice"]
    semanas = _semanas_no_intervalo(dt_inicio, dt_fim)
    vals = [idx[w] for w in semanas if w in idx.index]
    return float(np.mean(vals)) if vals else 100.0


def semanas_equivalentes(curva: pd.DataFrame, dt_entrada, horizonte_semanas: int) -> float:
    """Soma de (indice/100) nas `horizonte_semanas` a partir de `dt_entrada`.

    É o multiplicador sazonal da janela de vida do produto novo em "semanas
    médias": se entrar no Natal, vale mais que `horizonte_semanas`; num vale,
    menos. Multiplique pela velocidade desazonalizada p/ obter a venda projetada.
    """
    if curva.empty or horizonte_semanas <= 0:
        return float(max(horizonte_semanas, 0))
    idx = curva.set_index("semana")["indice"]
    d = pd.Timestamp(dt_entrada)
    total = 0.0
    for _ in range(int(horizonte_semanas)):
        w = int(d.isocalendar().week)
        total += (idx[w] if w in idx.index else 100.0) / 100.0
        d += timedelta(days=7)
    return total


# --------------------------------------------------------------------------- #
# Feriados nacionais e emendas
# --------------------------------------------------------------------------- #
def _pascoa(ano: int) -> date:
    """Domingo de Páscoa (algoritmo de Gauss/Butcher)."""
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    mes = (h + ll - 7 * m + 114) // 31
    dia = ((h + ll - 7 * m + 114) % 31) + 1
    return date(ano, mes, dia)


@lru_cache(maxsize=32)
def feriados_br(ano: int) -> dict:
    """Feriados nacionais (fixos + móveis por Páscoa). {data: nome}."""
    p = _pascoa(ano)
    fer = {
        date(ano, 1, 1): "Confraternização",
        p - timedelta(days=48): "Carnaval (seg)",
        p - timedelta(days=47): "Carnaval (ter)",
        p - timedelta(days=2): "Sexta-feira Santa",
        date(ano, 4, 21): "Tiradentes",
        date(ano, 5, 1): "Trabalho",
        p + timedelta(days=60): "Corpus Christi",
        date(ano, 9, 7): "Independência",
        date(ano, 10, 12): "N. Sra. Aparecida",
        date(ano, 11, 2): "Finados",
        date(ano, 11, 15): "Proclamação",
        date(ano, 12, 25): "Natal",
    }
    return fer


# Antecedência (em semanas) com que a sazonalidade de cada evento COMEÇA antes
# da data em si. Ex.: a venda de Natal arranca ~3 semanas antes do dia 25/12 —
# o pico é a semana ANTERIOR ao feriado, e a semana do Natal já cai.
ANTECEDENCIA_EVENTOS = {"Natal": 3}


def _semanas_do_evento(dia: date, antecedencia: int) -> list[int]:
    """Semana ISO do evento + as `antecedencia` semanas anteriores."""
    return [int((dia - timedelta(days=7 * k)).isocalendar()[1]) for k in range(antecedencia + 1)]


def marcar_feriados(
    curva: pd.DataFrame,
    anos: tuple[int, ...],
    antecedencia: Optional[dict] = None,
) -> pd.DataFrame:
    """Sinaliza semanas ISO com feriado, emenda (ponte) e temporada comercial.

    - `feriado`: feriado que cai naquela semana.
    - `tem_emenda`: feriado na terça (ponte na segunda) ou na quinta (ponte na sexta).
    - `temporada`: janela comercial do evento, que começa ANTES da data — ver
      `ANTECEDENCIA_EVENTOS` (Natal arranca 3 semanas antes). É o que marca a
      rampa de venda, não só o dia do feriado.

    Carnaval e Corpus Christi são móveis, então a marcação usa a semana ISO de
    cada ano informado (a união entre anos).
    """
    antecedencia = ANTECEDENCIA_EVENTOS if antecedencia is None else antecedencia
    marca: dict[int, set] = {}
    emenda: set[int] = set()
    temporada: dict[int, set] = {}
    for ano in anos:
        for dia, nome in feriados_br(ano).items():
            w = int(dia.isocalendar()[1])
            marca.setdefault(w, set()).add(nome)
            wd = dia.weekday()  # 0=seg..6=dom
            if wd in (1, 3):  # terça -> ponte na segunda; quinta -> ponte na sexta
                emenda.add(w)
            if nome in antecedencia:
                for sw in _semanas_do_evento(dia, antecedencia[nome]):
                    temporada.setdefault(sw, set()).add(nome)
    out = curva.copy()
    out["feriado"] = out["semana"].map(lambda w: ", ".join(sorted(marca.get(w, []))) or "")
    out["tem_emenda"] = out["semana"].map(lambda w: w in emenda)
    out["temporada"] = out["semana"].map(lambda w: ", ".join(sorted(temporada.get(w, []))) or "")
    return out

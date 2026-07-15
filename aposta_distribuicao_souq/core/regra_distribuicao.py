"""Regras puras de distribuição inicial.

Todas as funções deste módulo são puras (sem I/O, sem estado global) para
serem facilmente testáveis. A camada de UI apenas monta os inputs e exibe os
resultados; nenhuma regra de negócio deve ficar nas páginas Streamlit.

Convenções:
- `participacoes`: dict {loja: participacao_historica}. Não precisa somar 1;
  é sempre normalizado internamente.
- `velocidades_semanais`: dict {loja: unidades/semana esperadas}. Opcional.
  Usado apenas para o teto de cobertura. Ausência => loja sem teto (fallback).
- `curva_tamanhos`: dict {tamanho: peso}. Não precisa somar 1. Ausência/soma 0
  => distribuição uniforme entre os tamanhos informados.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import floor, isclose
from typing import Dict, List, Optional


# --------------------------------------------------------------------------- #
# Reserva CD
# --------------------------------------------------------------------------- #
def reservar_cd(aposta_total: float, reserva_cd_pct: float = 0.20) -> tuple[float, float]:
    """Separa a reserva do CD do total apostado.

    Retorna (reserva_cd, disponivel_para_lojas).
    """
    if aposta_total < 0:
        raise ValueError("aposta_total não pode ser negativa")
    if not 0.0 <= reserva_cd_pct < 1.0:
        raise ValueError("reserva_cd_pct deve estar em [0, 1)")
    reserva = aposta_total * reserva_cd_pct
    return reserva, aposta_total - reserva


# --------------------------------------------------------------------------- #
# Distribuição por participação com teto de cobertura
# --------------------------------------------------------------------------- #
def distribuir_por_participacao(
    disponivel: float,
    participacoes: Dict[str, float],
    tetos: Optional[Dict[str, float]] = None,
    _tol: float = 1e-9,
) -> Dict[str, float]:
    """Rateia `disponivel` entre lojas conforme participação, respeitando tetos.

    O excedente das lojas que estouram o teto é redistribuído às lojas com
    folga, proporcionalmente às participações delas, iterando até estabilizar.
    Se toda a base atingir o teto antes de esgotar `disponivel`, a sobra não é
    forçada (retorna a distribuição no teto); o chamador decide o destino.

    Retorna valores contínuos (float); o arredondamento é etapa separada.
    """
    if disponivel < 0:
        raise ValueError("disponivel não pode ser negativo")
    total_part = sum(participacoes.values())
    if total_part <= 0:
        raise ValueError("Participações devem somar um valor positivo")

    tetos = tetos or {}
    lojas = list(participacoes.keys())
    aloc: Dict[str, float] = {loja: 0.0 for loja in lojas}
    restante = disponivel
    ativos = set(lojas)  # lojas que ainda podem receber

    # Iteração de "water-filling": distribui proporcional, corta quem estoura o
    # teto, e reparte a sobra entre os que ainda têm folga.
    while restante > _tol and ativos:
        peso_ativos = sum(participacoes[l] for l in ativos)
        if peso_ativos <= 0:
            break
        estourou = False
        for loja in list(ativos):
            quota = restante * participacoes[loja] / peso_ativos
            teto = tetos.get(loja)
            novo = aloc[loja] + quota
            if teto is not None and novo >= teto - _tol:
                aloc[loja] = teto
                ativos.discard(loja)
                estourou = True
            else:
                aloc[loja] = novo
        # recalcula o restante realmente alocado
        restante = disponivel - sum(aloc.values())
        if not estourou:
            break
    return aloc


# --------------------------------------------------------------------------- #
# Grade mínima
# --------------------------------------------------------------------------- #
def aplicar_grade_minima(
    distribuicao: Dict[str, float],
    grade_minima: float,
    participacoes: Optional[Dict[str, float]] = None,
    _tol: float = 1e-9,
) -> Dict[str, float]:
    """Corta lojas abaixo da grade mínima e redistribui a quota liberada.

    Uma loja só permanece se recebe >= `grade_minima` unidades. As cortadas
    vão a 0 e a quantidade liberada é redistribuída entre as lojas que
    permanecem, proporcionalmente à participação (ou à própria distribuição, se
    `participacoes` não for informado). Repete até estabilizar.

    Se nenhuma loja atinge a grade mínima, retorna tudo zerado (o chamador trata
    a sobra, tipicamente devolvendo ao CD).
    """
    if grade_minima <= 0:
        return dict(distribuicao)

    base_peso = participacoes or distribuicao
    atual = dict(distribuicao)

    while True:
        mantidas = {l: q for l, q in atual.items() if q >= grade_minima - _tol}
        cortadas = {l: q for l, q in atual.items() if q < grade_minima - _tol and q > 0}
        if not cortadas:
            break
        liberado = sum(cortadas.values())
        for l in cortadas:
            atual[l] = 0.0
        peso_mantidas = sum(base_peso.get(l, 0.0) for l in mantidas)
        if not mantidas or peso_mantidas <= 0:
            # ninguém para absorver: tudo zerado
            for l in atual:
                atual[l] = 0.0
            break
        for l in mantidas:
            atual[l] += liberado * base_peso.get(l, 0.0) / peso_mantidas
    return atual


# --------------------------------------------------------------------------- #
# Curva por tamanho
# --------------------------------------------------------------------------- #
def normalizar_curva(curva_tamanhos: Dict[str, float]) -> Dict[str, float]:
    """Normaliza a curva para somar 1. Soma 0 ou vazia => uniforme."""
    if not curva_tamanhos:
        return {}
    total = sum(curva_tamanhos.values())
    if total <= 0:
        n = len(curva_tamanhos)
        return {t: 1.0 / n for t in curva_tamanhos}
    return {t: p / total for t, p in curva_tamanhos.items()}


def abrir_por_tamanho(qtd_loja: float, curva_tamanhos: Dict[str, float]) -> Dict[str, float]:
    """Abre a quantidade de uma loja por tamanho segundo a curva (contínuo)."""
    curva = normalizar_curva(curva_tamanhos)
    return {t: qtd_loja * p for t, p in curva.items()}


# --------------------------------------------------------------------------- #
# Arredondamento por maior resto (Hamilton / largest remainder)
# --------------------------------------------------------------------------- #
def arredondar_maior_resto(valores: Dict[str, float], total_alvo: Optional[int] = None) -> Dict[str, int]:
    """Arredonda um dict de floats para inteiros preservando a soma.

    Usa o método do maior resto: aplica piso a todos e distribui as unidades
    restantes (`total_alvo - soma dos pisos`) para as chaves com maior parte
    fracionária. Se `total_alvo` é None, usa round(soma dos valores).
    """
    if not valores:
        return {}
    if total_alvo is None:
        total_alvo = int(round(sum(valores.values())))

    pisos = {k: floor(v) for k, v in valores.items()}
    restantes = total_alvo - sum(pisos.values())

    if restantes <= 0:
        # nada a adicionar; se piso já excede o alvo, apenas devolve pisos
        return pisos

    # ordena por parte fracionária desc; desempate por valor original desc e chave
    fracs = sorted(
        valores.items(),
        key=lambda kv: (kv[1] - floor(kv[1]), kv[1], kv[0]),
        reverse=True,
    )
    resultado = dict(pisos)
    for i in range(restantes):
        chave = fracs[i % len(fracs)][0]
        resultado[chave] += 1
    return resultado


# --------------------------------------------------------------------------- #
# Pipeline completo -> matriz loja x tamanho
# --------------------------------------------------------------------------- #
@dataclass
class ResultadoDistribuicao:
    reserva_cd: float
    disponivel_lojas: float
    distribuicao_loja: Dict[str, int]          # {loja: unidades}
    matriz: Dict[str, Dict[str, int]]          # {loja: {tamanho: unidades}}
    sobra_para_cd: int                         # não distribuído (volta ao CD)
    avisos: List[str] = field(default_factory=list)

    def total_distribuido(self) -> int:
        return sum(self.distribuicao_loja.values())


def distribuir(
    aposta_total: float,
    participacoes: Dict[str, float],
    curva_tamanhos: Dict[str, float],
    reserva_cd_pct: float = 0.20,
    velocidades_semanais: Optional[Dict[str, float]] = None,
    cobertura_max_semanas: float = 4.0,
    grade_minima: float = 0.0,
) -> ResultadoDistribuicao:
    """Executa o pipeline completo de distribuição inicial.

    Etapas: reserva CD -> participação com teto de cobertura -> grade mínima
    -> arredondamento inteiro por loja -> abertura por tamanho (arredondada).
    A sobra não distribuível (teto/grade) é reportada como `sobra_para_cd`.
    """
    avisos: List[str] = []
    reserva, disponivel = reservar_cd(aposta_total, reserva_cd_pct)

    # teto de cobertura por loja (só se houver velocidade informada)
    tetos: Optional[Dict[str, float]] = None
    if velocidades_semanais:
        tetos = {l: v * cobertura_max_semanas for l, v in velocidades_semanais.items()}
    else:
        avisos.append("Sem velocidades por loja: teto de cobertura não aplicado (fallback).")

    aloc = distribuir_por_participacao(disponivel, participacoes, tetos)
    aloc = aplicar_grade_minima(aloc, grade_minima, participacoes)

    # arredonda a distribuição por loja (maior resto sobre o total efetivamente alocado)
    total_alocado = int(floor(sum(aloc.values()) + 1e-9))
    distrib_int = arredondar_maior_resto(aloc, total_alocado)

    sobra = int(round(disponivel)) - sum(distrib_int.values())
    if sobra > 0:
        avisos.append(f"{sobra} unidade(s) não distribuída(s) (teto/grade) retornaram ao CD.")

    # abertura por tamanho, arredondada por loja para preservar o total da loja
    matriz: Dict[str, Dict[str, int]] = {}
    for loja, qtd in distrib_int.items():
        if qtd <= 0:
            matriz[loja] = {t: 0 for t in curva_tamanhos} if curva_tamanhos else {}
            continue
        continuo = abrir_por_tamanho(qtd, curva_tamanhos)
        matriz[loja] = arredondar_maior_resto(continuo, qtd)

    return ResultadoDistribuicao(
        reserva_cd=reserva,
        disponivel_lojas=disponivel,
        distribuicao_loja=distrib_int,
        matriz=matriz,
        sobra_para_cd=max(sobra, 0),
        avisos=avisos,
    )


# Compatibilidade retroativa: rateio simples usado pela versão anterior.
def distribuir_por_loja(aposta: float, participacoes: Dict[str, float], teto_semanas: float = 4.0) -> Dict[str, float]:
    """Rateio proporcional simples (mantido por compatibilidade)."""
    return distribuir_por_participacao(aposta, participacoes)


# --------------------------------------------------------------------------- #
# Extrapolação de participação para lojas novas (média do Cluster)
# --------------------------------------------------------------------------- #
def participacao_com_loja_nova(
    part_hist: Dict[str, float],
    lojas_alvo: List[str],
    cluster_por_loja: Dict[str, str],
) -> Dict[str, float]:
    """Participação para TODAS as lojas-alvo, extrapolando as novas pelo Cluster.

    - `part_hist`: participação observada do(s) espelho(s) por loja (só lojas com
      histórico; SEM Ecom).
    - `lojas_alvo`: lojas físicas ativas que devem receber (inclui novas).
    - `cluster_por_loja`: mapa loja -> Cluster (Base_Lojas).

    Loja nova (em `lojas_alvo` e sem histórico) herda a média da participação das
    lojas do mesmo Cluster que têm histórico; sem cluster comparável, usa a média
    geral. No fim, tudo é renormalizado para somar 1.
    """
    if not part_hist:
        # sem histórico algum: distribuição uniforme entre as lojas-alvo
        return {l: 1.0 / len(lojas_alvo) for l in lojas_alvo} if lojas_alvo else {}

    media_geral = sum(part_hist.values()) / len(part_hist)
    # média por cluster (apenas lojas com histórico)
    soma_cl: Dict[str, float] = {}
    cont_cl: Dict[str, int] = {}
    for loja, p in part_hist.items():
        cl = cluster_por_loja.get(loja)
        soma_cl[cl] = soma_cl.get(cl, 0.0) + p
        cont_cl[cl] = cont_cl.get(cl, 0) + 1
    media_cluster = {cl: soma_cl[cl] / cont_cl[cl] for cl in soma_cl}

    resultado: Dict[str, float] = {}
    for loja in lojas_alvo:
        if loja in part_hist:
            resultado[loja] = part_hist[loja]
        else:
            cl = cluster_por_loja.get(loja)
            resultado[loja] = media_cluster.get(cl, media_geral)

    total = sum(resultado.values())
    if total <= 0:
        return {l: 1.0 / len(lojas_alvo) for l in lojas_alvo}
    return {l: p / total for l, p in resultado.items()}

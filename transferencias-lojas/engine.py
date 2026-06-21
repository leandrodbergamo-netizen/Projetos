"""Motor de remanejamento entre lojas.

Fluxo:
  1. necessidades()  -> lojas em ruptura (estoque 0 do SKU filho) que vendem o
     SKU pai, e onde o CD não tem o filho e não há trânsito para a loja.
     A prioridade ("probabilidade de venda") é a venda histórica do SKU pai
     naquela loja na janela configurada.
  2. doadoras()      -> lojas com estoque do SKU filho parado há >= N semanas
     desde o recebimento (sem venda no período).
  3. gerar_sugestoes() -> casa necessidades x doadoras respeitando o limite de
     no máximo MAX_LOJAS_POR_DOADORA lojas atendidas por doadora.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

import config
import cobertura
import sazonalidade


def _ultima_venda(vendas: pd.DataFrame) -> pd.DataFrame:
    """Data da última venda por (loja, sku_filho)."""
    if vendas.empty:
        return pd.DataFrame(columns=["loja", "sku_filho", "ultima_venda"])
    return (
        vendas.groupby(["loja", "sku_filho"])["data"].max()
        .reset_index().rename(columns={"data": "ultima_venda"})
    )


def _venda_pai_por_loja(vendas: pd.DataFrame, hoje: date, janela_dias: int) -> pd.DataFrame:
    """Quantidade vendida do SKU pai por loja na janela (probabilidade de venda)."""
    if vendas.empty:
        return pd.DataFrame(columns=["loja", "sku_pai", "venda_pai"])
    corte = pd.Timestamp(hoje) - pd.Timedelta(days=janela_dias)
    recente = vendas[vendas["data"] >= corte]
    return (
        recente.groupby(["loja", "sku_pai"])["qtd"].sum()
        .reset_index().rename(columns={"qtd": "venda_pai"})
    )


def necessidades(dados: dict[str, pd.DataFrame], hoje: date,
                 janela_dias: int = config.JANELA_VENDAS_DIAS,
                 curva=None) -> pd.DataFrame:
    produtos = dados["produtos"]
    estoque_loja = dados["estoque_loja"]
    estoque_cd = dados["estoque_cd"]
    transito = dados["transito"]
    vendas = dados["vendas"]

    venda_pai = _venda_pai_por_loja(vendas, hoje, janela_dias)

    # Universo candidato: toda (loja, sku_filho) cujo SKU pai a loja vende.
    cand = venda_pai.merge(produtos, on="sku_pai")  # loja, sku_pai, venda_pai, sku_filho, descricao, grupo
    cand = cand[cand["venda_pai"] > 0]

    # Só grupos com regra de limite (exclui BAZAR MATRIZ / linhas fora do mapa).
    cand = cand[cand["grupo"].isin(config.GRUPO_LIMITES)]

    # Só SKUs com estoque de status permitido em algum lugar (exclui OUTLET etc.).
    permitidos = dados.get("skus_permitidos")
    if permitidos is not None and not permitidos.empty:
        cand = cand[cand["sku_filho"].isin(set(permitidos["sku_filho"]))]

    # Estoque atual do filho na loja (ausente = 0).
    cand = cand.merge(estoque_loja, on=["loja", "sku_filho"], how="left")
    cand["qtd"] = cand["qtd"].fillna(0)

    # Ruptura = estoque zero do SKU filho.
    cand = cand[cand["qtd"] == 0].copy()

    # Clusterização x ruptura: a loja precisa JÁ carregar o SKU pai, ou seja,
    # ter estoque de pelo menos um outro SKU filho do mesmo pai. Se nunca
    # recebeu nenhum filho do pai, é clusterização (não é ruptura).
    el_pai = estoque_loja.merge(produtos[["sku_filho", "sku_pai"]], on="sku_filho", how="left")
    carrega_pai = set(zip(el_pai["loja"], el_pai["sku_pai"]))
    chaves_pai = list(zip(cand["loja"], cand["sku_pai"]))
    cand = cand[[c in carrega_pai for c in chaves_pai]]

    # CD não pode ter o filho.
    cd_com_estoque = set(estoque_cd.loc[estoque_cd["qtd"] > 0, "sku_filho"])
    cand = cand[~cand["sku_filho"].isin(cd_com_estoque)]

    # Não pode haver trânsito do filho para aquela loja.
    em_transito = set(zip(transito["sku_filho"], transito["loja_destino"])) if not transito.empty else set()
    if em_transito:
        chaves = list(zip(cand["sku_filho"], cand["loja"]))
        cand = cand[[c not in em_transito for c in chaves]]

    if cand.empty:
        return pd.DataFrame(columns=["loja", "sku_pai", "sku_filho", "descricao", "grupo",
                                     "prev_4sem", "cobertura_pai", "score", "qtd_sugerida"])

    # Cobertura + previsão sazonal por (loja, sku_pai) e combinação com a venda.
    pares = cand[["loja", "sku_pai"]].drop_duplicates()
    cob = cobertura.cobertura_receptoras(pares, produtos, estoque_loja, vendas, hoje, curva=curva)
    cand = cand.merge(cob[["loja", "sku_pai", "n_tam", "prev_horizonte", "cobertura_pai"]],
                      on=["loja", "sku_pai"], how="left")
    cand["prev_horizonte"] = cand["prev_horizonte"].fillna(0.0)

    # Score combinado: maior demanda prevista E menor cobertura -> maior prioridade.
    cand["score"] = cand["prev_horizonte"] / (1 + cand["cobertura_pai"].fillna(0))

    # Quantidade: previsão do horizonte rateada por tamanho, limitada pelo grupo.
    lim = cand["grupo"].map(config.limite_do_grupo).fillna(config.LIMITE_GRUPO_PADRAO)
    por_tam = (cand["prev_horizonte"] / cand["n_tam"].clip(lower=1).fillna(1)).round()
    cand["qtd_sugerida"] = por_tam.clip(lower=1, upper=lim).fillna(1).astype(int)

    cand["prev_4sem"] = cand["prev_horizonte"].round(1)
    return cand[["loja", "sku_pai", "sku_filho", "descricao", "grupo",
                 "prev_4sem", "cobertura_pai", "score", "qtd_sugerida"]] \
        .sort_values("score", ascending=False).reset_index(drop=True)


def doadoras(dados: dict[str, pd.DataFrame], hoje: date,
             semanas_min: int = config.SEMANAS_SEM_VENDA_MIN) -> pd.DataFrame:
    estoque_loja = dados["estoque_loja"]
    recebimento = dados["recebimento"]
    vendas = dados["vendas"]

    dias_min = semanas_min * 7
    hoje_ts = pd.Timestamp(hoje)
    d = estoque_loja[estoque_loja["qtd"] > 0].copy()

    # Data de recebimento estimada (histórico de estoque). Pode não existir
    # ainda — nesse caso a condição "há N semanas em loja" é relaxada e usamos
    # apenas a regra de "N semanas sem venda".
    if recebimento is not None and not recebimento.empty:
        d = d.merge(recebimento, on=["loja", "sku_filho"], how="left")
        d["dias_em_loja"] = (hoje_ts - d["data_recebimento"]).dt.days
    else:
        d["data_recebimento"] = pd.NaT
        d["dias_em_loja"] = pd.NA

    d = d.merge(_ultima_venda(vendas), on=["loja", "sku_filho"], how="left")

    # Dias sem venda: desde a última venda; se nunca vendeu na janela carregada,
    # usa a data de recebimento; se também não há recebimento, considera o item
    # totalmente parado (muito tempo sem venda).
    ref = d["ultima_venda"].fillna(d["data_recebimento"])
    d["dias_sem_venda"] = (hoje_ts - ref).dt.days
    d["dias_sem_venda"] = d["dias_sem_venda"].fillna(9999).astype(int)

    # Elegível: não vende há >= N semanas E (se conhecida) está em loja há >= N semanas.
    sem_venda_ok = d["dias_sem_venda"] >= dias_min
    em_loja_ok = d["dias_em_loja"].isna() | (d["dias_em_loja"] >= dias_min)
    d = d[sem_venda_ok & em_loja_ok].copy()

    d = d.rename(columns={"qtd": "qtd_disp"})
    return d[["loja", "sku_filho", "qtd_disp", "dias_sem_venda", "dias_em_loja"]] \
        .reset_index(drop=True)


def gerar_sugestoes(nec: pd.DataFrame, doa: pd.DataFrame,
                    max_lojas: int = config.MAX_LOJAS_POR_DOADORA) -> pd.DataFrame:
    # Estoque disponível por (loja_doadora, sku_filho) e metadados para priorizar.
    disp: dict[tuple, int] = {}
    meta: dict[tuple, dict] = {}
    for _, r in doa.iterrows():
        chave = (r["loja"], r["sku_filho"])
        disp[chave] = int(r["qtd_disp"])
        meta[chave] = {"dias_sem_venda": int(r["dias_sem_venda"])}

    # Doadoras por SKU filho.
    doa_por_sku: dict[str, list[str]] = {}
    for (loja, sku) in disp:
        doa_por_sku.setdefault(sku, []).append(loja)

    receptoras_por_doadora: dict[str, set] = {}
    sugestoes = []

    for _, need in nec.iterrows():
        sku, loja_dest, restante = need["sku_filho"], need["loja"], int(need["qtd_sugerida"])
        candidatos = [l for l in doa_por_sku.get(sku, []) if l != loja_dest and disp.get((l, sku), 0) > 0]
        # Prioriza doadora com item mais parado e com mais estoque.
        candidatos.sort(key=lambda l: (meta[(l, sku)]["dias_sem_venda"], disp[(l, sku)]), reverse=True)

        for doador in candidatos:
            if restante <= 0:
                break
            atendidas = receptoras_por_doadora.setdefault(doador, set())
            # Respeita o teto de lojas atendidas por doadora (lojas distintas).
            if loja_dest not in atendidas and len(atendidas) >= max_lojas:
                continue
            qtd = min(restante, disp[(doador, sku)])
            if qtd <= 0:
                continue
            disp[(doador, sku)] -= qtd
            atendidas.add(loja_dest)
            restante -= qtd
            sugestoes.append({
                "loja_doadora": doador,
                "loja_receptora": loja_dest,
                "grupo": need.get("grupo", ""),
                "sku_pai": need["sku_pai"],
                "sku_filho": sku,
                "qtd": qtd,
                "score_receptora": round(float(need["score"]), 1),
                "dias_parado_doadora": meta[(doador, sku)]["dias_sem_venda"],
            })

    cols = ["loja_doadora", "loja_receptora", "grupo", "sku_pai", "sku_filho",
            "qtd", "score_receptora", "dias_parado_doadora"]
    return pd.DataFrame(sugestoes, columns=cols)


def calcular(dados: dict[str, pd.DataFrame], hoje: date,
             semanas_min: int = config.SEMANAS_SEM_VENDA_MIN,
             max_lojas: int = config.MAX_LOJAS_POR_DOADORA,
             janela_dias: int = config.JANELA_VENDAS_DIAS) -> dict[str, pd.DataFrame]:
    """Roda o fluxo completo e devolve necessidades, doadoras e sugestões."""
    curva = sazonalidade.carregar_curva()  # carrega 1x e reaproveita
    nec = necessidades(dados, hoje, janela_dias=janela_dias, curva=curva)
    doa = doadoras(dados, hoje, semanas_min=semanas_min)
    sug = gerar_sugestoes(nec, doa, max_lojas=max_lojas)
    return {"necessidades": nec, "doadoras": doa, "sugestoes": sug}

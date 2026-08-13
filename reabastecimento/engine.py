"""Motor de remanejamento entre lojas.

Fluxo:
  1. necessidades()  -> lojas em ruptura (estoque 0 do SKU filho) que vendem o
     SKU pai, e onde o CD não tem o filho e não há trânsito para a loja.
     A prioridade ("probabilidade de venda") é a venda histórica do SKU pai
     naquela loja na janela configurada.
  2. doadoras()      -> pares (loja, SKU filho) em que o SKU PAI está sem venda
     na loja há >= N semanas (doa-se o filho, mas o gatilho é o pai) e, quando a
     data é conhecida, o filho está em loja há >= N semanas.
  3. gerar_sugestoes() -> casa necessidades x doadoras respeitando o limite de
     no máximo MAX_LOJAS_POR_DOADORA lojas atendidas por doadora.

Exceções por loja (config.LOJAS_NAO_DOAM / LOJAS_NAO_RECEBEM, sobreponíveis
pelos parâmetros nao_doam/nao_recebem de calcular()): lojas fora do jogo como
doadoras e/ou receptoras.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

import config
import cobertura
import sazonalidade


def _ultima_venda_pai(vendas: pd.DataFrame) -> pd.DataFrame:
    """Data da última venda do SKU PAI (qualquer filho) por loja."""
    if vendas.empty:
        return pd.DataFrame(columns=["loja", "sku_pai", "ultima_venda_pai"])
    return (
        vendas.groupby(["loja", "sku_pai"])["data"].max()
        .reset_index().rename(columns={"data": "ultima_venda_pai"})
    )


def _filtra_lojas(df: pd.DataFrame, col: str, excluir) -> pd.DataFrame:
    """Remove linhas cuja loja está na lista de exceção (sem acento/caixa)."""
    if not excluir or df.empty:
        return df
    excl = {config.norm_loja(x) for x in excluir}
    return df[~df[col].map(config.norm_loja).isin(excl)]


def _vendas_demanda(vendas: pd.DataFrame, produtos: pd.DataFrame) -> pd.DataFrame:
    """Vendas para o cálculo de DEMANDA, com cap de outlier por cupom.

    A contribuição de um mesmo cupom fica limitada ao limite do grupo por SKU
    pai (Home 10 / Acessórios 4 / Roupa 2): cliente VIP que "leva tudo" numa
    compra não infla a previsão. Sem a coluna `cupom` (nuvem antes da
    republicação) ou com o cap desligado, devolve as vendas como estão.
    Não usar no relógio "pai sem venda" da doadora (lá a venda real conta).
    """
    if (not config.CAP_DEMANDA_POR_CUPOM or vendas.empty
            or "cupom" not in vendas.columns):
        return vendas
    lim_pai = (produtos.groupby("sku_pai")["grupo_limite"].first()
               .map(config.limite_do_grupo))
    v = vendas.copy()
    total = v.groupby(["cupom", "sku_pai"])["qtd"].transform("sum")
    cap = v["sku_pai"].map(lim_pai).fillna(config.LIMITE_GRUPO_PADRAO)
    v["qtd"] = v["qtd"] * (cap / total).clip(upper=1.0)
    return v


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


def _pais_elegiveis_abastecimento(dados: dict[str, pd.DataFrame]) -> set | None:
    """Pais elegíveis ao abastecimento CD: têm dt_envio E (estoque em alguma
    loja OU venda histórica 2022->hoje, via tabela pais_com_venda).

    None = não filtrar (degradação: produtos sem coluna dt_envio ou 100% nula,
    caso da nuvem antes da republicação). Sem pais_com_venda, o fallback é a
    base de vendas do ano corrente.
    """
    produtos = dados["produtos"]
    if "dt_envio" not in produtos.columns or produtos["dt_envio"].notna().sum() == 0:
        return None
    tem_envio = set(produtos.loc[produtos["dt_envio"].notna(), "sku_pai"])
    el = dados["estoque_loja"].merge(produtos[["sku_filho", "sku_pai"]],
                                     on="sku_filho", how="left")
    com_estoque = set(el["sku_pai"].dropna())
    pcv = dados.get("pais_com_venda")
    com_venda = set(pcv["sku_pai"]) if pcv is not None and not pcv.empty else set()
    com_venda |= set(dados["vendas"]["sku_pai"].unique())
    return tem_envio & (com_estoque | com_venda)


def necessidades(dados: dict[str, pd.DataFrame], hoje: date,
                 janela_dias: int = config.JANELA_VENDAS_DIAS,
                 curva=None, excluir=None, gate_cd: str = "sem",
                 exigir_carrega_pai: bool = True) -> pd.DataFrame:
    """Rupturas candidatas a receber peças.

    `excluir`: lojas que não recebem (default config.LOJAS_NAO_RECEBEM).
    `gate_cd`: "sem" = só SKUs que o CD NÃO tem (remanejamento entre lojas);
               "com" = só SKUs que o CD TEM (abastecimento a partir do CD).
               No modo "com" exige ainda pai já lançado: dt_envio preenchido
               E (estoque em alguma loja OU venda histórica) — ver
               _pais_elegiveis_abastecimento.
    `exigir_carrega_pai`: False (abastecimento) não filtra por "loja carrega o
    pai"; a informação vira a coluna `introducao` ("Sim" = loja zerada em
    todos os filhos do pai — re-clusterização via CD).
    """
    produtos = dados["produtos"]
    estoque_loja = dados["estoque_loja"]
    estoque_cd = dados["estoque_cd"]
    transito = dados["transito"]
    # Demanda usa vendas com cap de outlier por cupom (cliente VIP).
    vendas = _vendas_demanda(dados["vendas"], produtos)

    if excluir is None:
        excluir = config.LOJAS_NAO_RECEBEM
    venda_pai = _venda_pai_por_loja(vendas, hoje, janela_dias)
    venda_pai = _filtra_lojas(venda_pai, "loja", excluir)

    # Universo candidato: toda (loja, sku_filho) cujo SKU pai a loja vende.
    cand = venda_pai.merge(produtos, on="sku_pai")  # loja, sku_pai, venda_pai, sku_filho, descricao, grupo
    cand = cand[cand["venda_pai"] > 0]

    # Só grupos (de limite) válidos (exclui BAZAR MATRIZ / linhas fora do mapa).
    cand = cand[cand["grupo_limite"].isin(config.GRUPO_LIMITES)]

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
    # Exceção: pai de FILHO ÚNICO (Home/Acessórios, sem grade) não tem "outro
    # filho" possível — a evidência de que a loja trabalha o produto é a venda
    # do pai na janela, já exigida no início do funil (venda_pai > 0).
    # No abastecimento (exigir_carrega_pai=False) o CD PODE introduzir: a regra
    # vira apenas a flag `introducao`.
    el_pai = estoque_loja.merge(produtos[["sku_filho", "sku_pai"]], on="sku_filho", how="left")
    carrega_pai = set(zip(el_pai["loja"], el_pai["sku_pai"]))
    n_filhos = produtos.groupby("sku_pai")["sku_filho"].nunique()
    filho_unico = set(n_filhos[n_filhos == 1].index)
    if exigir_carrega_pai:
        cand = cand[[p in filho_unico or (l, p) in carrega_pai
                     for l, p in zip(cand["loja"], cand["sku_pai"])]]
    else:
        cand = cand.copy()
        cand["introducao"] = ["" if (l, p) in carrega_pai else "Sim"
                              for l, p in zip(cand["loja"], cand["sku_pai"])]

    # Gate do CD: remanejamento exige CD zerado; abastecimento exige CD com peça.
    cd_com_estoque = set(estoque_cd.loc[estoque_cd["qtd"] > 0, "sku_filho"])
    if gate_cd == "com":
        cand = cand[cand["sku_filho"].isin(cd_com_estoque)]
        # Abastecimento só para produto já lançado: pai com dt_envio e com
        # presença em loja (estoque) ou venda histórica.
        pais_ok = _pais_elegiveis_abastecimento(dados)
        if pais_ok is not None:
            cand = cand[cand["sku_pai"].isin(pais_ok)]
    else:
        cand = cand[~cand["sku_filho"].isin(cd_com_estoque)]

    # Não pode haver trânsito do filho para aquela loja.
    em_transito = set(zip(transito["sku_filho"], transito["loja_destino"])) if not transito.empty else set()
    if em_transito:
        chaves = list(zip(cand["sku_filho"], cand["loja"]))
        cand = cand[[c not in em_transito for c in chaves]]

    saida_cols = ["loja", "linha", "grupo", "subgrupo", "colecao", "status",
                  "sku_pai", "sku_filho", "descricao", "prev_4sem", "cobertura_pai",
                  "score", "qtd_sugerida"]
    if not exigir_carrega_pai:
        saida_cols = saida_cols + ["introducao"]
    if cand.empty:
        return pd.DataFrame(columns=saida_cols)

    # Cobertura + previsão sazonal por (loja, sku_pai) e combinação com a venda.
    pares = cand[["loja", "sku_pai"]].drop_duplicates()
    cob = cobertura.cobertura_receptoras(pares, produtos, estoque_loja, vendas, hoje, curva=curva)
    cand = cand.merge(cob[["loja", "sku_pai", "n_tam", "prev_horizonte", "cobertura_pai"]],
                      on=["loja", "sku_pai"], how="left")
    cand["prev_horizonte"] = cand["prev_horizonte"].fillna(0.0)

    # Score combinado: maior demanda prevista E menor cobertura -> maior prioridade.
    cand["score"] = cand["prev_horizonte"] / (1 + cand["cobertura_pai"].fillna(0))

    # Quantidade: previsão do horizonte rateada por tamanho, limitada pelo grupo.
    lim = cand["grupo_limite"].map(config.limite_do_grupo).fillna(config.LIMITE_GRUPO_PADRAO)
    por_tam = (cand["prev_horizonte"] / cand["n_tam"].clip(lower=1).fillna(1)).round()
    cand["qtd_sugerida"] = por_tam.clip(lower=1, upper=lim).fillna(1).astype(int)

    cand["prev_4sem"] = cand["prev_horizonte"].round(1)
    for c in ("colecao", "status", "linha", "subgrupo"):
        if c not in cand.columns:
            cand[c] = "—"
    return cand[saida_cols].sort_values("score", ascending=False).reset_index(drop=True)


def doadoras(dados: dict[str, pd.DataFrame], hoje: date,
             semanas_min: int = config.SEMANAS_SEM_VENDA_MIN,
             excluir=None) -> pd.DataFrame:
    """Pares (loja, sku_filho) elegíveis a doar.

    Gatilho: o SKU PAI está sem venda na loja há >= N semanas — vale para
    qualquer tipo de produto; a doação continua a nível de SKU filho.
    `excluir`: lojas que não doam (default config.LOJAS_NAO_DOAM).
    """
    produtos = dados["produtos"]
    estoque_loja = dados["estoque_loja"]
    recebimento = dados["recebimento"]
    vendas = dados["vendas"]

    if excluir is None:
        excluir = config.LOJAS_NAO_DOAM

    dias_min = semanas_min * 7
    hoje_ts = pd.Timestamp(hoje)
    d = estoque_loja[estoque_loja["qtd"] > 0].copy()
    d = _filtra_lojas(d, "loja", excluir)
    d = d.merge(produtos[["sku_filho", "sku_pai"]], on="sku_filho", how="left")

    # Data de recebimento estimada (histórico de estoque). Pode não existir
    # ainda — nesse caso a condição "há N semanas em loja" é relaxada e usamos
    # apenas a regra de "N semanas sem venda".
    if recebimento is not None and not recebimento.empty:
        d = d.merge(recebimento, on=["loja", "sku_filho"], how="left")
        d["dias_em_loja"] = (hoje_ts - d["data_recebimento"]).dt.days
    else:
        d["data_recebimento"] = pd.NaT
        d["dias_em_loja"] = pd.NA

    d = d.merge(_ultima_venda_pai(vendas), on=["loja", "sku_pai"], how="left")

    # Dias sem venda do PAI: desde a última venda de qualquer filho na loja;
    # se o pai nunca vendeu na janela carregada, usa a data de recebimento do
    # filho; se também não há recebimento, considera totalmente parado.
    ref = d["ultima_venda_pai"].fillna(d["data_recebimento"])
    d["dias_sem_venda"] = (hoje_ts - ref).dt.days
    d["dias_sem_venda"] = d["dias_sem_venda"].fillna(9999).astype(int)

    # Elegível: pai sem venda há >= N semanas E (se conhecida) o filho está em
    # loja há >= N semanas.
    sem_venda_ok = d["dias_sem_venda"] >= dias_min
    em_loja_ok = d["dias_em_loja"].isna() | (d["dias_em_loja"] >= dias_min)
    d = d[sem_venda_ok & em_loja_ok].copy()

    d = d.rename(columns={"qtd": "qtd_disp"})
    return d[["loja", "sku_filho", "qtd_disp", "dias_sem_venda", "dias_em_loja"]] \
        .reset_index(drop=True)


def _info_grade(dados: dict[str, pd.DataFrame]):
    """grade_total[sku_pai] (nº de tamanhos no cadastro) e tamanhos em estoque por
    (loja, sku_pai). Usados na regra de grade quebrada da doadora."""
    produtos = dados["produtos"]
    estoque_loja = dados["estoque_loja"]
    grade_total = produtos.groupby("sku_pai")["sku_filho"].nunique().to_dict()
    el = estoque_loja[estoque_loja["qtd"] > 0].merge(
        produtos[["sku_filho", "sku_pai"]], on="sku_filho", how="left")
    tam_em_estoque = el.groupby(["loja", "sku_pai"])["sku_filho"].nunique().to_dict()
    pai_de_filho = dict(zip(produtos["sku_filho"], produtos["sku_pai"]))
    return grade_total, tam_em_estoque, pai_de_filho


def gerar_sugestoes(nec: pd.DataFrame, doa: pd.DataFrame, dados: dict[str, pd.DataFrame],
                    max_lojas: int = config.MAX_LOJAS_POR_DOADORA) -> pd.DataFrame:
    grade_total, tam_em_estoque, pai_de_filho = _info_grade(dados)

    def grade_quebrada(loja, sku_pai) -> bool:
        total = grade_total.get(sku_pai, 0)
        if not total:
            return False
        return (tam_em_estoque.get((loja, sku_pai), 0) / total) < config.PCT_GRADE_MIN

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
            # Grade quebrada: doadora envia TODO o estoque do filho (ignora limite).
            quebrada = grade_quebrada(doador, need["sku_pai"])
            qtd = disp[(doador, sku)] if quebrada else min(restante, disp[(doador, sku)])
            if qtd <= 0:
                continue
            disp[(doador, sku)] -= qtd
            atendidas.add(loja_dest)
            restante -= qtd
            sugestoes.append({
                "loja_doadora": doador,
                "loja_receptora": loja_dest,
                "linha": need.get("linha", ""),
                "grupo": need.get("grupo", ""),
                "subgrupo": need.get("subgrupo", ""),
                "colecao": need.get("colecao", ""),
                "status": need.get("status", ""),
                "sku_pai": need["sku_pai"],
                "sku_filho": sku,
                "qtd": qtd,
                "grade_quebrada": "Sim" if quebrada else "",
                "score_receptora": round(float(need["score"]), 1),
                "dias_parado_doadora": meta[(doador, sku)]["dias_sem_venda"],
            })

    cols = ["loja_doadora", "loja_receptora", "linha", "grupo", "subgrupo", "colecao",
            "status", "sku_pai", "sku_filho", "qtd", "grade_quebrada",
            "score_receptora", "dias_parado_doadora"]
    return pd.DataFrame(sugestoes, columns=cols)


def gerar_abastecimento(nec_cd: pd.DataFrame, estoque_cd: pd.DataFrame,
                        reserva: int = config.RESERVA_CD_PADRAO) -> pd.DataFrame:
    """Distribui o estoque do CD entre as necessidades, priorizando por score.

    O CD não tem gatilho de "parado", teto de lojas atendidas nem grade
    quebrada: manda até `qtd_sugerida` (já limitada pelo grupo) enquanto houver
    saldo, guardando `reserva` peças por SKU. Alocação menor que o pedido
    ganha flag "Parcial"."""
    disp = {r["sku_filho"]: max(int(r["qtd"]) - int(reserva), 0)
            for _, r in estoque_cd.iterrows()}
    linhas = []
    for _, need in nec_cd.iterrows():   # nec_cd já vem ordenada por score desc
        sku = need["sku_filho"]
        saldo = disp.get(sku, 0)
        if saldo <= 0:
            continue
        pedido = int(need["qtd_sugerida"])
        qtd = min(pedido, saldo)
        disp[sku] = saldo - qtd
        linhas.append({
            "loja_receptora": need["loja"],
            "linha": need.get("linha", ""),
            "grupo": need.get("grupo", ""),
            "subgrupo": need.get("subgrupo", ""),
            "colecao": need.get("colecao", ""),
            "status": need.get("status", ""),
            "sku_pai": need["sku_pai"],
            "sku_filho": sku,
            "qtd": qtd,
            "introducao": need.get("introducao", ""),
            "parcial": "Sim" if qtd < pedido else "",
            "score_receptora": round(float(need["score"]), 1),
        })
    cols = ["loja_receptora", "linha", "grupo", "subgrupo", "colecao", "status",
            "sku_pai", "sku_filho", "qtd", "introducao", "parcial",
            "score_receptora"]
    return pd.DataFrame(linhas, columns=cols)


def calcular_abastecimento(dados: dict[str, pd.DataFrame], hoje: date,
                           janela_dias: int = config.JANELA_VENDAS_DIAS,
                           reserva: int = config.RESERVA_CD_PADRAO,
                           nao_recebem=None) -> dict[str, pd.DataFrame]:
    """Fluxo do abastecimento CD → lojas.

    Necessidades = mesmo funil do remanejamento com o gate invertido (só SKUs
    que o CD tem) e sem exigir carrega-o-pai (CD pode introduzir). Devolve
    também a sobra por SKU no CD após a distribuição."""
    curva = dados.get("curva")
    if curva is None:
        curva = sazonalidade.carregar_curva()
    nec_cd = necessidades(dados, hoje, janela_dias=janela_dias, curva=curva,
                          excluir=nao_recebem, gate_cd="com",
                          exigir_carrega_pai=False)
    abast = gerar_abastecimento(nec_cd, dados["estoque_cd"], reserva=reserva)

    enviado = (abast.groupby("sku_filho")["qtd"].sum()
               if not abast.empty else pd.Series(dtype="int64"))
    sobra = dados["estoque_cd"].loc[dados["estoque_cd"]["qtd"] > 0].copy()
    sobra["enviado"] = sobra["sku_filho"].map(enviado).fillna(0).astype(int)
    sobra["sobra"] = sobra["qtd"].astype(int) - sobra["enviado"]
    produtos = dados["produtos"]
    attrs = [c for c in ("sku_filho", "sku_pai", "linha", "subgrupo", "colecao",
                         "status", "descricao") if c in produtos.columns]
    sobra = sobra.merge(produtos[attrs].drop_duplicates("sku_filho"),
                        on="sku_filho", how="left")
    sobra = sobra.sort_values("sobra", ascending=False).reset_index(drop=True)
    return {"necessidades_cd": nec_cd, "abastecimento": abast, "sobra_cd": sobra}


def ruptura_skus(dados: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Ruptura a nível SKU sobre o sortimento da loja (filhos dos pais que ela carrega).

    Sortimento da loja = todos os SKUs filho (status permitido) dos SKUs pai que a
    loja CARREGA (tem ≥1 filho em estoque). Devolve um registro por (loja, sku_filho)
    com atributos de produto e flags: ruptura, rup_sem_transito, soldout_cd.
    """
    produtos = dados["produtos"]
    estoque_loja = dados["estoque_loja"]
    estoque_cd = dados["estoque_cd"]
    transito = dados["transito"]
    permitidos = dados.get("skus_permitidos")

    attrs = ["sku_filho", "sku_pai", "linha", "grupo", "subgrupo", "colecao", "status"]
    attrs = [c for c in attrs if c in produtos.columns]
    prod_pai = produtos[attrs]
    if permitidos is not None and not permitidos.empty:
        prod_pai = prod_pai[prod_pai["sku_filho"].isin(set(permitidos["sku_filho"]))]

    carrega = (estoque_loja.merge(prod_pai[["sku_filho", "sku_pai"]], on="sku_filho")[["loja", "sku_pai"]]
               .drop_duplicates())
    sort = carrega.merge(prod_pai, on="sku_pai")  # loja, sku_pai, sku_filho, atributos

    em_estoque = set(zip(estoque_loja["loja"], estoque_loja["sku_filho"]))
    em_transito = set(zip(transito["loja_destino"], transito["sku_filho"])) if not transito.empty else set()
    cd_com = set(estoque_cd.loc[estoque_cd["qtd"] > 0, "sku_filho"])

    pares = list(zip(sort["loja"], sort["sku_filho"]))
    sort["ruptura"] = [p not in em_estoque for p in pares]
    sort["em_transito"] = [p in em_transito for p in pares]
    sort["rup_sem_transito"] = sort["ruptura"] & (~sort["em_transito"])
    sort["soldout_cd"] = sort["rup_sem_transito"] & (~sort["sku_filho"].isin(cd_com))
    return sort.reset_index(drop=True)


ALERTA_CD_COLS = ["linha", "grupo", "subgrupo", "colecao", "status", "sku_pai",
                  "sku_filho", "descricao", "tamanho", "qtd_cd", "dt_envio",
                  "dias_desde_envio"]


def alerta_parado_cd(dados: dict[str, pd.DataFrame], hoje: date) -> pd.DataFrame:
    """SKUs filho parados no CD: qtd_cd>0, ZERO em qualquer loja, pai com
    dt_envio (já foi lançado) e status em config.STATUS_ALERTA_CD.

    Requer a tabela `estoque_amplo` (foto CD x lojas de TODOS os status);
    ausente/None (nuvem ainda não republicada) -> DataFrame vazio.
    """
    ea = dados.get("estoque_amplo")
    produtos = dados["produtos"]
    if ea is None or ea.empty or "dt_envio" not in produtos.columns:
        return pd.DataFrame(columns=ALERTA_CD_COLS)

    ea = ea.copy()
    ea[["qtd_cd", "qtd_lojas"]] = ea[["qtd_cd", "qtd_lojas"]].astype(int)
    ea = ea[(ea["qtd_cd"] > 0) & (ea["qtd_lojas"] == 0)
            & (ea["status"].isin(config.STATUS_ALERTA_CD))]
    if ea.empty:
        return pd.DataFrame(columns=ALERTA_CD_COLS)

    # Atributos do produto; o status autoritativo é o do estoque_amplo.
    attrs = ["sku_filho", "sku_pai", "descricao", "tamanho", "linha", "grupo",
             "subgrupo", "colecao"]
    attrs = [c for c in attrs if c in produtos.columns]
    al = ea[["sku_filho", "status", "qtd_cd"]].merge(produtos[attrs],
                                                     on="sku_filho", how="left")

    # dt_envio do PAI (máximo entre os filhos) — exige pai já lançado.
    dt_pai = (produtos.dropna(subset=["dt_envio"])
              .groupby("sku_pai")["dt_envio"].max().rename("dt_envio"))
    al = al.merge(dt_pai, on="sku_pai", how="left")
    al = al[al["dt_envio"].notna()].copy()
    if al.empty:
        return pd.DataFrame(columns=ALERTA_CD_COLS)

    al["dias_desde_envio"] = (pd.Timestamp(hoje) - al["dt_envio"]).dt.days
    for c in ALERTA_CD_COLS:
        if c not in al.columns:
            al[c] = "—"
    return (al[ALERTA_CD_COLS]
            .sort_values(["dias_desde_envio", "qtd_cd"], ascending=False)
            .reset_index(drop=True))


def cobertura_sortimento(dados: dict[str, pd.DataFrame], hoje: date,
                         curva=None) -> pd.DataFrame:
    """Cobertura por (loja, sku_pai) sobre o sortimento carregado.

    prev_sem = previsão SEMANAL full price (dessazonalizada x índice sazonal);
    cobertura_sem = estoque do pai na loja ÷ prev_sem, em semanas.
    Sem previsão (pai sem venda full price recente) -> cobertura indefinida (NaN).
    """
    produtos = dados["produtos"]
    estoque_loja = dados["estoque_loja"]
    if curva is None:
        curva = dados.get("curva")
    pares = (estoque_loja.merge(produtos[["sku_filho", "sku_pai"]], on="sku_filho", how="left")
             [["loja", "sku_pai"]].dropna().drop_duplicates())
    cob = cobertura.cobertura_receptoras(pares, produtos, estoque_loja,
                                         dados["vendas"], hoje, curva=curva)
    cob["prev_sem"] = cob["prev_horizonte"] / config.COBERTURA_HORIZONTE_SEMANAS
    cob["cobertura_sem"] = cob["estoque_pai"] / cob["prev_sem"].where(cob["prev_sem"] > 0)
    return cob[["loja", "sku_pai", "estoque_pai", "prev_sem", "cobertura_sem"]]


def cobertura_agregada(df: pd.DataFrame, cob: pd.DataFrame, por: str) -> pd.DataFrame:
    """Cobertura agregada por dimensão: soma de estoque ÷ soma de previsão semanal.

    df vem de ruptura_skus (já filtrado); dedup em (loja, sku_pai) para não
    contar o mesmo pai uma vez por filho."""
    if df.empty or cob.empty:
        return pd.DataFrame(columns=[por, "estoque", "prev_sem", "cobertura_sem"])
    cols = ["loja", "sku_pai"] + ([] if por == "loja" else [por])
    pares = df[cols].drop_duplicates(subset=["loja", "sku_pai"])
    m = pares.merge(cob, on=["loja", "sku_pai"], how="left")
    g = m.groupby(por).agg(estoque=("estoque_pai", "sum"),
                           prev_sem=("prev_sem", "sum")).reset_index()
    g["cobertura_sem"] = (g["estoque"] / g["prev_sem"].where(g["prev_sem"] > 0)).round(1)
    return g[[por, "estoque", "prev_sem", "cobertura_sem"]]


def _agrega_ruptura(df: pd.DataFrame, por: str) -> pd.DataFrame:
    """Agrega flags de ruptura por uma dimensão (ex.: 'loja' ou 'subgrupo')."""
    if df.empty:
        return pd.DataFrame(columns=[por, "sortimento", "%Ruptura Loja",
                                     "%Ruptura Loja+Trânsito", "%Sold Out CD"])
    g = df.groupby(por).agg(
        sortimento=("sku_filho", "count"),
        rupturas=("ruptura", "sum"),
        rup_sem_transito=("rup_sem_transito", "sum"),
        soldout_cd=("soldout_cd", "sum"),
    ).reset_index()
    g["%Ruptura Loja"] = (100 * g["rupturas"] / g["sortimento"]).round(1)
    g["%Ruptura Loja+Trânsito"] = (100 * g["rup_sem_transito"] / g["sortimento"]).round(1)
    g["%Sold Out CD"] = (100 * g["soldout_cd"] / g["sortimento"]).round(1)
    return g.sort_values("%Ruptura Loja", ascending=False).reset_index(drop=True)


def ruptura_por_loja(df: pd.DataFrame) -> pd.DataFrame:
    return _agrega_ruptura(df, "loja")


def ruptura_por_subgrupo(df: pd.DataFrame) -> pd.DataFrame:
    return _agrega_ruptura(df, "subgrupo")


def calcular(dados: dict[str, pd.DataFrame], hoje: date,
             semanas_min: int = config.SEMANAS_SEM_VENDA_MIN,
             max_lojas: int = config.MAX_LOJAS_POR_DOADORA,
             janela_dias: int = config.JANELA_VENDAS_DIAS,
             nao_doam=None, nao_recebem=None) -> dict[str, pd.DataFrame]:
    """Roda o fluxo completo e devolve necessidades, doadoras e sugestões.

    nao_doam / nao_recebem: exceções por loja (None -> listas do config)."""
    # Curva: vinda do banco (nuvem) se presente; senão, do parquet local.
    curva = dados.get("curva")
    if curva is None:
        curva = sazonalidade.carregar_curva()
    nec = necessidades(dados, hoje, janela_dias=janela_dias, curva=curva,
                       excluir=nao_recebem)
    doa = doadoras(dados, hoje, semanas_min=semanas_min, excluir=nao_doam)
    sug = gerar_sugestoes(nec, doa, dados, max_lojas=max_lojas)
    return {"necessidades": nec, "doadoras": doa, "sugestoes": sug}

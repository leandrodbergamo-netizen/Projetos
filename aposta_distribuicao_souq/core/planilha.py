"""Planilha-mãe: export/import Excel dos cenários de aposta.

Uma linha = um cenário COMPLETO, com a aposta já decidida — o import valida,
grava no Histórico e roda só o rateio loja × tamanho (distribuição massiva).
O export usa a MESMA máscara, fechando o ciclo exportar → ajustar → importar.

Convenções da máscara (aba `cenarios` + aba `leia-me` gerada de MASCARA):
- listas usam `;` como separador (nunca `|`, que aparece nos buckets `38|PP`);
- curva de tamanhos: pares `tamanho=peso` (`38|PP=0.08;40|P=0.22;…`);
- `id` vazio cria um registro novo; preenchido atualiza o existente.
Validação ALL-OR-NOTHING: qualquer erro e nada é gravado.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from io import BytesIO
from typing import Optional

import pandas as pd

from core.dados import (cluster_por_loja, espelhos_loja_nova, lojas_alvo_souq,
                        participacao_lojas, rank_colecao)
from core.espelho import curva_tamanhos_grade, pool_suavizacao
from core.regra_distribuicao import (CD_ROTULO, cd_por_tamanho, distribuir,
                                     participacao_com_loja_nova)

SEP = ";"
FAIXAS_VALIDAS = ("P1", "P2", "P3", "P4")

# Fonte única da máscara: colunas da aba `cenarios` e conteúdo da aba `leia-me`.
MASCARA = [
    {"coluna": "id", "obrigatoria": False, "tipo": "texto",
     "descricao": "Vazio = cria registro novo; preenchido = atualiza o registro "
                  "existente (o id aparece no export).", "exemplo": ""},
    {"coluna": "sku_ref", "obrigatoria": False, "tipo": "texto",
     "descricao": "Referência livre do produto novo.", "exemplo": "04.26.11.497"},
    {"coluna": "subgrupo", "obrigatoria": True, "tipo": "texto",
     "descricao": "Subgrupo do cadastro.", "exemplo": "VESTIDO"},
    {"coluna": "tecido", "obrigatoria": True, "tipo": "texto",
     "descricao": "Tecido (grupo de matéria-prima).", "exemplo": "Linho"},
    {"coluna": "faixas", "obrigatoria": True, "tipo": "lista",
     "descricao": "Faixas de preço, separadas por ';'.", "exemplo": "P2;P3"},
    {"coluna": "cores", "obrigatoria": False, "tipo": "lista",
     "descricao": "Cores (informativo).", "exemplo": "Azul;Preto"},
    {"coluna": "grade", "obrigatoria": True, "tipo": "lista",
     "descricao": "Buckets de tamanho da aposta.", "exemplo": "38|PP;40|P;42|M;44|G;46|GG"},
    {"coluna": "colecao", "obrigatoria": True, "tipo": "texto",
     "descricao": "Coleção apostada.", "exemplo": "INVERNO 2027"},
    {"coluna": "dt_entrada", "obrigatoria": True, "tipo": "data",
     "descricao": "Data de entrada em loja (célula de data, AAAA-MM-DD ou "
                  "DD/MM/AAAA).", "exemplo": "2027-01-20"},
    {"coluna": "aproveitamento_pct", "obrigatoria": True, "tipo": "inteiro 10-100",
     "descricao": "% da aposta vendida a full price no período.", "exemplo": "70"},
    {"coluna": "reserva_cd_pct", "obrigatoria": True, "tipo": "inteiro 0-50",
     "descricao": "% da aposta que fica no CD.", "exemplo": "20"},
    {"coluna": "perfis", "obrigatoria": False, "tipo": "lista",
     "descricao": "Perfis econômicos do parque; vazio = todos.", "exemplo": "A;AB"},
    {"coluna": "climas", "obrigatoria": False, "tipo": "lista",
     "descricao": "Climas do parque; vazio = todos.", "exemplo": "Quente"},
    {"coluna": "aposta_final", "obrigatoria": True, "tipo": "número > 0",
     "descricao": "Unidades a distribuir — é o que o rateio usa.", "exemplo": "120"},
    {"coluna": "espelhos", "obrigatoria": False, "tipo": "lista",
     "descricao": "cod_sku_pai dos espelhos (curva e participação); vazio = "
                  "segmento subgrupo+tecido.", "exemplo": "04.25.11.001.002;04.25.11.003.001"},
    {"coluna": "curva_tamanhos", "obrigatoria": False, "tipo": "lista tamanho=peso",
     "descricao": "Pesos por tamanho (não precisam somar 1); vazio = recalcula; "
                  "parcial = completa pelo segmento.", "exemplo": "38|PP=0.1;40|P=0.25"},
    {"coluna": "max_por_tamanho_loja", "obrigatoria": False, "tipo": "inteiro >= 1",
     "descricao": "Teto por célula loja×tamanho; vazio = padrão do app.", "exemplo": "4"},
    {"coluna": "garantir_grade_completa", "obrigatoria": False, "tipo": "SIM/NAO",
     "descricao": "1 peça de cada tamanho em toda loja (padrão SIM).", "exemplo": "SIM"},
    {"coluna": "aposta_modelo", "obrigatoria": False, "tipo": "número",
     "descricao": "Sugerida pelo modelo (só no export, informativa — ignorada "
                  "no import).", "exemplo": ""},
]
COLUNAS = [c["coluna"] for c in MASCARA]


# --------------------------------------------------------------------------- #
# Serialização
# --------------------------------------------------------------------------- #
def _junta(valores) -> str:
    return SEP.join(str(v) for v in (valores or []))


def _separa(texto) -> list[str]:
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return []
    return [p.strip() for p in str(texto).split(SEP) if p.strip()]


def _junta_curva(curva: dict) -> str:
    return SEP.join(f"{t}={float(p):.4f}" for t, p in (curva or {}).items())


def _separa_curva(texto) -> dict[str, float]:
    pares = {}
    for parte in _separa(texto):
        if "=" not in parte:
            raise ValueError(f"'{parte}' não está no formato tamanho=peso")
        t, p = parte.rsplit("=", 1)
        pares[t.strip()] = float(p.replace(",", "."))
    return pares


def _data(valor) -> Optional[str]:
    """Aceita datetime/date do Excel, AAAA-MM-DD e DD/MM/AAAA -> 'AAAA-MM-DD'."""
    if isinstance(valor, (datetime, date, pd.Timestamp)):
        if pd.isna(pd.Timestamp(valor)):
            return None
        return pd.Timestamp(valor).strftime("%Y-%m-%d")
    txt = str(valor or "").strip()
    if not txt:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(txt.split(" ")[0], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _vazio(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == ""


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #
def _linha_export(registro: dict) -> dict:
    """registro = {'id', 'payload'} com payload já normalizado (v2)."""
    p = registro["payload"]
    ins, parque = p.get("inputs") or {}, p.get("parque") or {}
    return {
        "id": registro.get("id") or "",
        "sku_ref": ins.get("sku_ref") or "",
        "subgrupo": ins.get("subgrupo") or "",
        "tecido": ins.get("tecido") or "",
        "faixas": _junta(ins.get("faixas")),
        "cores": _junta(ins.get("cores")),
        "grade": _junta(ins.get("grade")),
        "colecao": ins.get("colecao") or "",
        "dt_entrada": ins.get("dt_entrada") or "",
        "aproveitamento_pct": round(100 * float(ins.get("aproveitamento") or 0.70)),
        "reserva_cd_pct": round(100 * float(p.get("reserva_cd_pct") or 0.20)),
        "perfis": _junta(parque.get("perfis")),
        "climas": _junta(parque.get("climas")),
        "aposta_final": float(p.get("aposta_final") or p.get("aposta_total") or 0),
        "espelhos": _junta(p.get("espelhos")),
        "curva_tamanhos": _junta_curva(p.get("curva_tamanhos")),
        "max_por_tamanho_loja": p.get("max_por_tamanho_loja") or "",
        "garantir_grade_completa": "NAO" if p.get("garantir_grade_completa") is False else "SIM",
        "aposta_modelo": float(p.get("aposta_total") or 0),
    }


def exportar(registros: list[dict]) -> bytes:
    """Excel da planilha-mãe (abas `cenarios` + `leia-me`) para os registros
    dados ([{'id', 'payload'}], payload já normalizado)."""
    cen = pd.DataFrame([_linha_export(r) for r in registros], columns=COLUNAS)
    leia = pd.DataFrame(MASCARA).rename(columns={
        "coluna": "Coluna", "obrigatoria": "Obrigatória", "tipo": "Tipo",
        "descricao": "Descrição", "exemplo": "Exemplo"})
    leia["Obrigatória"] = leia["Obrigatória"].map({True: "SIM", False: "não"})
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        cen.to_excel(xw, sheet_name="cenarios", index=False)
        leia.to_excel(xw, sheet_name="leia-me", index=False)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Import — validação (all-or-nothing)
# --------------------------------------------------------------------------- #
def validar(df: pd.DataFrame, ctx: dict) -> tuple[list[dict], list[str]]:
    """Valida a aba `cenarios` e devolve (linhas normalizadas, erros).

    `ctx` = {subgrupos, tecidos, tamanhos, perfis, climas, ids} (sets).
    Qualquer erro => a lista de linhas volta VAZIA (nada deve ser gravado).
    Os números de linha nas mensagens são os do Excel (cabeçalho = linha 1).
    """
    erros: list[str] = []
    linhas: list[dict] = []

    faltam = [c for c in COLUNAS if c not in df.columns and c != "aposta_modelo"]
    if faltam:
        return [], [f"Colunas ausentes na aba 'cenarios': {', '.join(faltam)}. "
                    "Use o export do Histórico como modelo."]

    for i, row in df.iterrows():
        n = i + 2      # linha do Excel
        erro_antes = len(erros)

        def falta(campo):
            erros.append(f"Linha {n}: campo obrigatório '{campo}' vazio.")

        id_ = "" if _vazio(row.get("id")) else str(row.get("id")).strip()
        if id_ and id_ not in ctx.get("ids", set()):
            erros.append(f"Linha {n}: id '{id_}' não encontrado no Histórico "
                         "(deixe vazio para criar novo).")

        subgrupo = "" if _vazio(row.get("subgrupo")) else str(row["subgrupo"]).strip()
        if not subgrupo:
            falta("subgrupo")
        elif subgrupo not in ctx.get("subgrupos", set()):
            erros.append(f"Linha {n}: subgrupo '{subgrupo}' não existe no cadastro.")

        tecido = "" if _vazio(row.get("tecido")) else str(row["tecido"]).strip()
        if not tecido:
            falta("tecido")
        elif tecido not in ctx.get("tecidos", set()):
            erros.append(f"Linha {n}: tecido '{tecido}' não existe no cadastro.")

        faixas = _separa(row.get("faixas"))
        if not faixas:
            falta("faixas")
        for f in faixas:
            if f not in FAIXAS_VALIDAS:
                erros.append(f"Linha {n}: faixa '{f}' inválida "
                             f"(use {';'.join(FAIXAS_VALIDAS)}).")

        grade = _separa(row.get("grade"))
        if not grade:
            falta("grade")
        for t in grade:
            if t not in ctx.get("tamanhos", set()):
                erros.append(f"Linha {n}: tamanho '{t}' não existe na régua "
                             "(buckets como 38|PP … 46|GG ou U).")

        colecao = "" if _vazio(row.get("colecao")) else str(row["colecao"]).strip()
        if not colecao:
            falta("colecao")
        elif rank_colecao(colecao) is None:
            erros.append(f"Linha {n}: coleção '{colecao}' não reconhecida "
                         "(ex.: INVERNO 2027, VERÃO 2026-2027).")

        dt = None if _vazio(row.get("dt_entrada")) else _data(row.get("dt_entrada"))
        if _vazio(row.get("dt_entrada")):
            falta("dt_entrada")
        elif dt is None:
            erros.append(f"Linha {n}: dt_entrada '{row.get('dt_entrada')}' inválida "
                         "(use data do Excel, AAAA-MM-DD ou DD/MM/AAAA).")

        def inteiro(campo, minimo, maximo, obrigatorio=True):
            v = row.get(campo)
            if _vazio(v):
                if obrigatorio:
                    falta(campo)
                return None
            try:
                x = int(float(str(v).replace(",", ".")))
            except ValueError:
                erros.append(f"Linha {n}: {campo} '{v}' não é um número inteiro.")
                return None
            if not minimo <= x <= maximo:
                erros.append(f"Linha {n}: {campo} deve estar entre {minimo} e {maximo}.")
                return None
            return x

        aprov = inteiro("aproveitamento_pct", 10, 100)
        reserva = inteiro("reserva_cd_pct", 0, 50)
        max_tam = inteiro("max_por_tamanho_loja", 1, 50, obrigatorio=False)

        perfis = _separa(row.get("perfis"))
        for pfl in perfis:
            if pfl not in ctx.get("perfis", set()):
                erros.append(f"Linha {n}: perfil '{pfl}' não existe nas lojas ativas.")
        climas = _separa(row.get("climas"))
        for cl in climas:
            if cl not in ctx.get("climas", set()):
                erros.append(f"Linha {n}: clima '{cl}' não existe nas lojas ativas.")

        aposta = row.get("aposta_final")
        if _vazio(aposta):
            falta("aposta_final")
            aposta_f = None
        else:
            try:
                aposta_f = float(str(aposta).replace(",", "."))
            except ValueError:
                erros.append(f"Linha {n}: aposta_final '{aposta}' não é um número.")
                aposta_f = None
            if aposta_f is not None and aposta_f <= 0:
                erros.append(f"Linha {n}: aposta_final deve ser um número > 0.")
                aposta_f = None

        try:
            curva_exp = _separa_curva(row.get("curva_tamanhos"))
        except ValueError as e:
            erros.append(f"Linha {n}: curva_tamanhos inválida ({e}).")
            curva_exp = {}
        for t in curva_exp:
            if grade and t not in grade:
                erros.append(f"Linha {n}: curva_tamanhos tem o tamanho '{t}' "
                             "que não está na grade.")

        garantir_txt = "" if _vazio(row.get("garantir_grade_completa")) \
            else str(row["garantir_grade_completa"]).strip().upper()
        if garantir_txt not in ("", "SIM", "NAO", "NÃO"):
            erros.append(f"Linha {n}: garantir_grade_completa '{garantir_txt}' "
                         "inválido (use SIM ou NAO).")

        if len(erros) > erro_antes:
            continue
        linhas.append({
            "id": id_ or None,
            "sku_ref": "" if _vazio(row.get("sku_ref")) else str(row["sku_ref"]).strip(),
            "subgrupo": subgrupo, "tecido": tecido, "faixas": faixas,
            "cores": _separa(row.get("cores")), "grade": grade,
            "colecao": colecao, "dt_entrada": dt,
            "aproveitamento_pct": aprov, "reserva_cd_pct": reserva,
            "perfis": perfis or None, "climas": climas or None,
            "aposta_final": aposta_f,
            "espelhos": _separa(row.get("espelhos")),
            "curva_tamanhos": curva_exp,
            "max_por_tamanho_loja": max_tam,
            "garantir_grade_completa": garantir_txt not in ("NAO", "NÃO"),
        })

    if erros:
        return [], erros
    return linhas, []


# --------------------------------------------------------------------------- #
# Import — montagem do cenário (payload v2 + rateio)
# --------------------------------------------------------------------------- #
def montar_cenario(linha: dict, pp: pd.DataFrame, fp: pd.DataFrame, cfg: dict):
    """Linha VALIDADA -> (payload v2 `origem='import'`, ResultadoDistribuicao).

    Roda só o rateio (sem projeção de velocidade): participações do segmento
    (ou dos espelhos informados), curva de tamanhos explícita/completada pelo
    segmento (6b) e `distribuir` — sem teto de cobertura, mesma decisão do app.
    `cfg` = parametros.yaml + {'ecom_locs': set} (participação só física).
    """
    desde = float(cfg.get("desde_colecao", 2022.0))
    perfis, climas = linha.get("perfis"), linha.get("climas")
    lojas_df = lojas_alvo_souq(perfis=perfis, climas=climas)
    if lojas_df.empty:
        raise ValueError("nenhuma loja ativa com o Perfil/Clima informado")
    lojas_alvo = [str(float(x)) for x in lojas_df["sk_localidade"]]

    ecom = set(cfg.get("ecom_locs") or set())
    fp_fis = fp[~fp["sk_localidade"].isin(ecom)] if ecom else fp
    pool = pool_suavizacao(pp, subgrupo=linha["subgrupo"], tecido=linha["tecido"],
                           desde_colecao=desde)
    espelhos = linha.get("espelhos") or []
    part_esp = participacao_lojas(fp_fis[fp_fis["cod_sku_pai"].isin(espelhos)]) \
        if espelhos else {}
    part_hist = participacao_lojas(fp_fis[fp_fis["cod_sku_pai"].isin(pool)]) or part_esp
    if not part_hist:
        raise ValueError("sem histórico de venda no segmento (nem nos espelhos) "
                         "para ratear entre lojas")

    grade = linha["grade"]
    curva_exp = linha.get("curva_tamanhos") or {}
    if curva_exp and set(grade) <= set(curva_exp):
        curva = {t: float(curva_exp[t]) for t in grade}
        curva_origem = {t: "planilha" for t in grade}
        avisos_curva: list[str] = []
    else:
        calc, calc_origem, avisos_curva = curva_tamanhos_grade(
            fp, pp, espelhos or sorted(pool), grade,
            subgrupo=linha["subgrupo"], tecido=linha["tecido"], desde_colecao=desde)
        if curva_exp:
            # pesos da planilha prevalecem; os demais tamanhos são calibrados
            # pelos tamanhos em comum (mesma lógica do 6b)
            comuns = [t for t in grade if t in curva_exp and calc.get(t, 0) > 0]
            den = sum(calc[t] for t in comuns)
            esc = (sum(float(curva_exp[t]) for t in comuns) / den) if den > 0 else 1.0
            curva, curva_origem = {}, {}
            for t in grade:
                if t in curva_exp:
                    curva[t] = float(curva_exp[t])
                    curva_origem[t] = "planilha"
                else:
                    curva[t] = calc[t] * esc
                    curva_origem[t] = calc_origem[t]
        else:
            curva, curva_origem = calc, calc_origem

    part = participacao_com_loja_nova(
        part_hist, lojas_alvo, cluster_por_loja(),
        lojas_espelho=espelhos_loja_nova(),
        com_dado_proprio=set(part_esp) if espelhos else None)
    max_tam = linha.get("max_por_tamanho_loja") or int(cfg.get("max_por_tamanho_loja", 4))
    resultado = distribuir(
        aposta_total=float(linha["aposta_final"]),
        participacoes=part,
        curva_tamanhos=curva,
        reserva_cd_pct=linha["reserva_cd_pct"] / 100.0,
        max_por_tamanho_loja=max_tam,
        garantir_grade_completa=bool(linha.get("garantir_grade_completa", True)),
    )

    # matriz no MESMO formato do save da tela: lojas nomeadas + linha do CD
    nomes = {str(float(r["sk_localidade"])): f'{r["desc_nome"]} ({r["Perfil"]}/{r["Temperatura"]})'
             for _, r in lojas_df.iterrows()}
    aposta_final = float(linha["aposta_final"]) + resultado.acrescimo_garantia
    matriz_dict = {nomes.get(loja, loja): {t: int(q) for t, q in tams.items()}
                   for loja, tams in resultado.matriz.items()}
    por_tamanho: dict[str, int] = {}
    for tams in resultado.matriz.values():
        for t, q in tams.items():
            por_tamanho[t] = por_tamanho.get(t, 0) + int(q)
    cd = cd_por_tamanho(aposta_final, por_tamanho, curva)
    if cd:
        matriz_dict[CD_ROTULO] = {t: int(v) for t, v in cd.items()}

    ref = f"{linha['sku_ref']} · " if linha.get("sku_ref") else ""
    payload = {
        "versao": 2,
        "origem": "import",
        "resumo": (f"{ref}{linha['subgrupo']}/{linha['tecido']} · "
                   f"{'/'.join(linha['faixas'])} · {linha['colecao']}"),
        "aposta_total": float(linha["aposta_final"]),
        "aposta_final": aposta_final,
        "parque": {"perfis": perfis, "climas": climas, "n_lojas_alvo": len(lojas_alvo)},
        "reserva_cd_pct": linha["reserva_cd_pct"] / 100.0,
        "participacoes_hist": part_hist,
        "participacoes_espelhos": part_esp,
        "curva_tamanhos": curva,
        "curva_origem": curva_origem,
        "espelhos": espelhos,
        "suavizacao": {"n_modelos": len(pool), "fits": []},
        "lojas_com_espelho_proprio": sorted(part_esp),
        "inputs": {
            "sku_ref": linha.get("sku_ref"), "subgrupo": linha["subgrupo"],
            "tecido": linha["tecido"], "cores": linha.get("cores"),
            "grade": grade, "faixas": linha["faixas"],
            "dt_entrada": linha["dt_entrada"], "colecao": linha["colecao"],
            "aproveitamento": linha["aproveitamento_pct"] / 100.0,
        },
        "avisos_projecao": avisos_curva,
        "distribuicao_editada": matriz_dict,
        "distribuido_editado": int(resultado.total_distribuido()),
        "max_por_tamanho_loja": max_tam,
        "garantir_grade_completa": bool(linha.get("garantir_grade_completa", True)),
        "atualizado_em": datetime.now(timezone.utc).isoformat(),
    }
    return payload, resultado

"""Coleta a composição (tecido) dos produtos no site da Souq (Shopify) e grava o
de-para `config/material_por_sku.yaml` para os modelos SEM `desc_material` no cadastro.

Por que existe: ~870 linhas do cadastro (coleções desde Inverno 2022) não têm
`desc_material`, então caem no tecido "Outros". O site expõe a composição real
("94,5% VISCOSE 5,5% ELASTANO") na descrição — para os modelos que ainda estão à
venda. Coleções antigas não estão no site nem no Wayback: para essas, o de-para
só se completa à mão (planilha `tecido_correto`).

Fonte: feed público `https://www.souqstore.com.br/products.json` (Shopify, permitido
no robots.txt). O SKU da variante é o `cod_produto` do cadastro
(modelo.cor.tamanho); os 5 primeiros segmentos são o `cod_sku_pai`.

Uso (no PC, com os Excel):
    python coleta_tecido_site.py            # só modelos sem desc_material
    python coleta_tecido_site.py --todos    # também os que já têm (para conferência)

O YAML preserva entradas escritas à mão (chave já existente não é sobrescrita).
Depois de rodar: reinicie o app (cache) e, para a nuvem, `python publica_supabase.py`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
ARQ_DEPARA = ROOT / "config" / "material_por_sku.yaml"
FEED = "https://www.souqstore.com.br/products.json?limit=250&page={page}"
UA = {"User-Agent": "Mozilla/5.0 (Souq aposta_distribuicao; coleta de composicao; 1 req/s)"}

# Composição explícita: "96% POLIÉSTER 4% ELASTANO", "100 % algodão", "94,5% viscose..."
_PCT = re.compile(r"\d{1,3}(?:[.,]\d+)?\s?%\s?[A-Za-zÀ-ÿ]+(?:\s(?:e\s)?\d{1,3}(?:[.,]\d+)?\s?%\s?[A-Za-zÀ-ÿ]+)*")
# Campo rotulado: "Tecido: Malha de viscose com elastano"
_ROTULO = re.compile(r"(?:tecido|composi[cç][aã]o)\s*:\s*([^\n.]{3,100})", re.I)
# Frase "confeccionada em malha de viscose com elastano"
_FRASE = re.compile(r"(?:confeccionad[ao]|produzid[ao]|feit[ao])\s+em\s+([^\n.,]{3,100})", re.I)
# "malha de viscose com elastano" solta no texto, ou a 1ª fibra citada (último recurso)
_MALHA = re.compile(r"(malha de [a-zà-ÿ]+(?: com [a-zà-ÿ]+)?)", re.I)
_FIBRA = re.compile(r"\b(linho|viscose|algod[aã]o|poli[eé]ster|poliamida|seda|tricot|modal|acetato|acr[ií]lico)\b", re.I)


def _texto(html: str) -> str:
    t = re.sub(r"<[^>]+>", "\n", html or "")
    t = re.sub(r"&nbsp;", " ", t)
    return re.sub(r"[ \t]+", " ", t)


def composicao(produto: dict) -> str | None:
    """Composição mais explícita disponível no produto: % > rótulo > frase > tag."""
    txt = _texto(produto.get("body_html") or "")
    m = _PCT.search(txt)
    if m:
        return re.sub(r"\s+", " ", m.group(0)).strip().upper()
    m = _ROTULO.search(txt)
    if m:
        return m.group(1).strip().upper()
    m = _FRASE.search(txt)
    if m:
        return m.group(1).strip().upper()
    for tag in produto.get("tags") or []:
        if "%" in tag:
            return tag.strip().upper()
    m = _MALHA.search(txt)
    if m:
        return m.group(1).strip().upper()
    m = _FIBRA.search(txt)
    if m:
        return f"{m.group(1).upper()} (MENCIONADO NA DESCRIÇÃO DO SITE)"
    return None


def baixar_catalogo(pausa: float = 1.0) -> list[dict]:
    todos: list[dict] = []
    for page in range(1, 200):
        req = urllib.request.Request(FEED.format(page=page), headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            ps = json.load(r).get("products", [])
        todos.extend(ps)
        print(f"  página {page}: {len(ps)} produtos")
        if len(ps) < 250:
            break
        time.sleep(pausa)
    return todos


def composicao_por_sku_pai(catalogo: list[dict]) -> dict[str, dict]:
    saida: dict[str, dict] = {}
    for p in catalogo:
        comp = composicao(p)
        for v in p.get("variants") or []:
            seg = str(v.get("sku") or "").split(".")
            if len(seg) < 5:
                continue
            pai = ".".join(seg[:5])
            if pai not in saida:
                saida[pai] = {"composicao": comp, "titulo": p.get("title"), "handle": p.get("handle")}
    return saida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--todos", action="store_true",
                    help="inclui modelos que já têm desc_material (conferência)")
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT))
    from core.dados import carregar_produtos

    print("Baixando catálogo do site…")
    site = composicao_por_sku_pai(baixar_catalogo())
    com_comp = {k: v for k, v in site.items() if v["composicao"]}
    print(f"  {len(site)} modelos no site, {len(com_comp)} com composição legível")

    # mesmo recorte do app (linha ROUPA, grão vendável, sem CANCELADO); o de-para
    # atual já foi aplicado aqui, então "sem material" = o que ainda falta
    from core.espelho import preparar_produtos
    pp = preparar_produtos(carregar_produtos())
    por_pai = pp.drop_duplicates("cod_sku_pai").set_index("cod_sku_pai")
    sem_material = set(por_pai.index[por_pai["desc_material"].isna()])
    sem_material_escopo = {k for k in sem_material if (por_pai.loc[k, "rank_colecao"] or 0) >= 2022}

    atual: dict = {}
    if ARQ_DEPARA.exists():
        atual = yaml.safe_load(ARQ_DEPARA.read_text(encoding="utf-8")) or {}

    novos, mantidos = 0, 0
    for pai, info in sorted(com_comp.items()):
        if pai not in por_pai.index:
            continue
        if not args.todos and pai not in sem_material:
            continue
        if pai in atual:                      # entrada manual/anterior prevalece
            mantidos += 1
            continue
        atual[pai] = info["composicao"]
        novos += 1

    cab = (f"# De-para cod_sku_pai -> material (composição), para modelos SEM desc_material\n"
           f"# no cadastro. Lido por core/taxonomia.material_por_sku e aplicado em\n"
           f"# core/espelho.preparar_produtos ANTES da regra de tecido (material_grupos.yaml).\n"
           f"# Gerado por coleta_tecido_site.py a partir de souqstore.com.br; edite à vontade\n"
           f"# (entrada existente nunca é sobrescrita pelo script). Última coleta: {date.today():%d/%m/%Y}.\n")
    corpo = yaml.safe_dump(dict(sorted(atual.items())), allow_unicode=True, sort_keys=False,
                           default_flow_style=False, width=120)
    ARQ_DEPARA.write_text(cab + corpo, encoding="utf-8")
    print(f"Gravado {ARQ_DEPARA.relative_to(ROOT)}: {novos} novos, {mantidos} mantidos, "
          f"{len(atual)} no total.")
    faltam = len(sem_material_escopo - set(atual))
    print(f"Modelos sem material (coleções >= Inverno 2022) que seguem sem de-para: "
          f"{faltam} — não estão no site; completar à mão no YAML.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

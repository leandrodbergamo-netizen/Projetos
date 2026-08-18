# -*- coding: utf-8 -*-
"""Coleta do catálogo publicado em souqstore.com.br (endpoint products.json)."""
from __future__ import annotations

import json
import urllib.request

import config

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')


def fetch(url: str):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def coletar() -> list[dict]:
    """Percorre as páginas do products.json até a primeira página VAZIA.

    Atenção: nunca parar em página "incompleta" (<250 itens). A plataforma
    devolve páginas parciais no meio da série — foi o que zerou a coleta em
    17/08/2026, quando a página 1 veio com 247 itens e o loop parava ali.
    """
    prods, page = [], 1
    while page <= config.MAX_PAGINAS:
        d = fetch(config.CATALOGO_URL.format(page=page))
        if not d.get('products'):
            break
        prods += d['products']
        page += 1
    return prods


def gravar_cache(prods: list[dict]) -> None:
    with open(config.CACHE_CATALOGO, 'w', encoding='utf-8') as f:
        json.dump(prods, f, ensure_ascii=False)


def ler_cache() -> list[dict] | None:
    """Catálogo da última coleta, ou None se não houver cache utilizável."""
    if not config.CACHE_CATALOGO.exists() or config.CACHE_CATALOGO.stat().st_size == 0:
        return None
    with open(config.CACHE_CATALOGO, encoding='utf-8') as f:
        return json.load(f)


def limpar_cache() -> None:
    try:
        config.CACHE_CATALOGO.unlink(missing_ok=True)
    except OSError:
        open(config.CACHE_CATALOGO, 'w').close()   # esvazia se não puder excluir

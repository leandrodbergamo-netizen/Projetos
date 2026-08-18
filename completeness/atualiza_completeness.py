# -*- coding: utf-8 -*-
"""Auditoria diária de completeness do catálogo Souq (souqstore.com.br).

Gera: historico.csv (acumulado), detalhe_atual.csv / disponibilidade_atual.csv
(snapshots do dia) e data.js (dashboard legado).

Uso: python atualiza_completeness.py [--coleta | --processa]
  --coleta    baixa o catálogo e guarda em _cache_catalogo.json
  --processa  cruza o catálogo em cache com as bases internas e grava tudo
"""
from __future__ import annotations

import json
import sys

import analise
import coleta
import config
import relatorio


def processar(prods: list[dict], *, miniaturas: bool = True) -> dict:
    """Roda a auditoria completa sobre um catálogo já coletado.

    Devolve os DataFrames e o resumo do dia (usados pela publicação na nuvem e
    pela notificação no Teams), mantendo os mesmos arquivos de saída de sempre.
    """
    data = config.hoje()
    df_full = analise.analisar(prods)
    m, sku_map, pai_attr, com_envio = analise.carregar_base_produtos()
    df_full = analise.enriquecer(df_full, m)
    excecoes = analise.carregar_excecoes()
    fotos = analise.carregar_fotos()
    dd, n_exc, n_sem_envio = analise.disponibilidade(df_full, sku_map, pai_attr, com_envio,
                                                     excecoes, fotos,
                                                     analise.imagens_do_site(prods))
    n_comb = int((df_full['combined'] == 1).sum())
    df = df_full[df_full['combined'] == 0].drop(columns=['combined', 'pais_all']).reset_index(drop=True)

    hist_disp = relatorio.salvar_disponibilidade(dd, data)
    hist = relatorio.salvar(df, dd, hist_disp, data)
    thumbs = relatorio.gerar_thumbs(dd, fotos) if miniaturas else []

    sem_desc = int((df['f0'] == 0).sum())
    sem_match = int((df['colecao'] == 'Sem cadastro').sum())
    cand = len(dd)
    no_site = int(dd['no_site'].sum())
    fora_com_foto = dd[(dd['no_site'] == 0) & (dd['tem_foto'] == 1)].sort_values('qtde', ascending=False)
    sem_img = df[df['f6'] == 0]

    print(f'OK {data}: {len(df)} produtos no site | sem descrição: {sem_desc} | '
          f'sem match: {sem_match} | candidatos estoque>=2: {cand} | '
          f'no site: {no_site} ({no_site/cand*100:.1f}%)')
    print(f'   filtros: {n_exc} SKUs exceção excluídos | {n_sem_envio} sem data de envio '
          f'excluídos | {n_comb} combined listings excluídos do dash')
    if fotos:
        print(f'   contraprova fotos ({len(fotos)} SKUs na pasta): {len(fora_com_foto)} '
              f'candidatos com foto e FORA do site')
        for _, r in fora_com_foto.head(20).iterrows():
            print(f"      {r['pai']} {r['item']} ({r['cor']}) — {r['status']}, "
                  f"qtde {r['qtde']} (CD {r['qtde_cd']})")
        com_foto_pasta = sem_img[sem_img['sku_pai'].isin(fotos)]
        print(f'   produtos no site sem imagem: {len(sem_img)} | desses, com foto na pasta: '
              f'{len(com_foto_pasta)}')
        for _, r in com_foto_pasta.iterrows():
            print(f"      {r['sku_pai']} {r['titulo']} — {r['url']}")

    resumo = {
        'data': data,
        'coletados': len(prods),
        'no_site': len(df),
        'sem_descricao': sem_desc,
        'sem_match': sem_match,
        'candidatos': cand,
        'publicados': no_site,
        'pct_disponibilidade': round(no_site / cand * 100, 1) if cand else 0.0,
        'fora_do_site': cand - no_site,
        'fora_com_foto': len(fora_com_foto),
        'skus_com_foto': len(fotos),
        'sem_imagem_no_site': len(sem_img),
        'excluidos_excecao': n_exc,
        'excluidos_sem_envio': n_sem_envio,
        'combined_listings': n_comb,
        'thumbs_novos': len(thumbs),
    }
    config.RESUMO_JSON.parent.mkdir(parents=True, exist_ok=True)
    config.RESUMO_JSON.write_text(json.dumps(resumo, ensure_ascii=False, indent=2),
                                  encoding='utf-8')
    return {'df': df, 'dd': dd, 'hist': hist, 'hist_disp': hist_disp,
            'fotos': fotos, 'thumbs_novos': thumbs, 'resumo': resumo}


def carregar_catalogo(etapa: str = '') -> list[dict]:
    """Catálogo do cache (--processa) ou coletado na hora. Aborta se vier curto."""
    prods = coleta.ler_cache() if etapa == '--processa' else None
    if prods is None:
        prods = coleta.coletar()
    if len(prods) < config.MIN_PRODUTOS_COLETA:
        print(f'ERRO: coleta retornou apenas {len(prods)} produtos — abortando sem gravar.')
        sys.exit(1)
    return prods


def main() -> None:
    etapa = sys.argv[1] if len(sys.argv) > 1 else ''
    if etapa == '--coleta':
        prods = coleta.coletar()
        coleta.gravar_cache(prods)
        print(f'coleta ok: {len(prods)} produtos')
        return
    processar(carregar_catalogo(etapa))
    coleta.limpar_cache()


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""Gravação dos resultados: séries acumuladas, snapshots do dia, miniaturas e
o data.js consumido pelo dashboard.html legado.

As séries (historico.csv e historico_disponibilidade.csv) são acumuladas e
nunca truncadas: a gravação do dia substitui apenas as linhas da própria data.
"""
from __future__ import annotations

import datetime
import json
import os

import pandas as pd

import config

FCOLS = [f'f{i}' for i in range(14)]


def _acumular(novo: pd.DataFrame, arquivo, data: str) -> pd.DataFrame:
    """Regrava o arquivo trocando só as linhas da data corrente. Devolve a série."""
    if os.path.exists(arquivo):
        h = pd.read_csv(arquivo)
        h = h[h['data'] != data]
        novo = pd.concat([h, novo], ignore_index=True)
    novo.to_csv(arquivo, index=False)
    return pd.read_csv(arquivo)


def salvar_disponibilidade(dd: pd.DataFrame, data: str) -> pd.DataFrame:
    dd = dd.sort_values('qtde', ascending=False)
    dd.to_csv(config.DISP_ATUAL, index=False)
    dims = ['colecao', 'linha', 'grupo', 'subgrupo', 'status', 'grade_completa']
    ag = dd.groupby(dims, dropna=False).agg(n_cand=('pai', 'size'), n_site=('no_site', 'sum'),
                                            n_vend=('vendavel_site', 'sum'),
                                            q_total=('qtde', 'sum')).reset_index()
    ag.insert(0, 'data', data)
    return _acumular(ag, config.HIST_DISP, data)


def salvar(df: pd.DataFrame, dd: pd.DataFrame, hist_disp: pd.DataFrame, data: str) -> pd.DataFrame:
    """Grava o snapshot do catálogo, acumula a série e monta o data.js."""
    df.to_csv(config.DETALHE_ATUAL, index=False)
    dims = ['dept', 'cat', 'colecao', 'tipo', 'status']
    ag = df.groupby(dims, dropna=False)[FCOLS].sum().reset_index()
    ag.columns = dims + [f's{i}' for i in range(14)]
    ag['n'] = df.groupby(dims, dropna=False).size().values
    ag.insert(0, 'data', data)
    hist = _acumular(ag, config.HIST, data)

    det_cols = ['titulo', 'dept', 'cat', 'colecao', 'tipo', 'status', 'preco', 'n_img',
                'disponivel'] + FCOLS + ['url']
    det = df[det_cols].copy()
    det['flags'] = det[FCOLS].astype(str).agg(''.join, axis=1)
    det = det.drop(columns=FCOLS)
    payload = {
        'atualizado': datetime.datetime.now().strftime('%d/%m/%Y %H:%M'),
        'campos': config.FLAGS,
        'hist': hist.values.tolist(), 'hist_cols': list(hist.columns),
        'det': det.values.tolist(), 'det_cols': list(det.columns),
        'disp': dd.values.tolist(), 'disp_cols': list(dd.columns),
        'hist_disp': hist_disp.values.tolist(), 'hist_disp_cols': list(hist_disp.columns),
    }
    with open(config.DATA_JS, 'w', encoding='utf-8') as f:
        f.write('window.DADOS = ')
        json.dump(payload, f, ensure_ascii=False, default=str)
        f.write(';')
    return hist


def gerar_thumbs(dd: pd.DataFrame, fotos: dict) -> list[str]:
    """Miniaturas locais (fotos_thumb/<pai>.jpg) das fotos dos candidatos.

    Incremental: só gera o que ainda não existe. Devolve os SKUs criados agora
    (é o que a publicação envia para o Storage).
    """
    try:
        from PIL import Image
    except ImportError:
        print('AVISO: Pillow não instalado — miniaturas não geradas.')
        return []
    config.PASTA_THUMBS.mkdir(exist_ok=True)
    novos, falha = [], 0
    for pai in dd.loc[dd['tem_foto'] == 1, 'pai']:
        foto = fotos.get(pai)
        if not foto:
            continue
        dst = config.PASTA_THUMBS / f'{pai}.jpg'
        if dst.exists():
            continue
        try:
            img = Image.open(foto['abs'])
            img.thumbnail((360, 360))
            img.convert('RGB').save(dst, 'JPEG', quality=72)
            novos.append(pai)
        except Exception:
            falha += 1
    if novos or falha:
        print(f'   miniaturas: {len(novos)} geradas' + (f' | {falha} falharam' if falha else ''))
    return novos

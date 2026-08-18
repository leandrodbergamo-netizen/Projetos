# -*- coding: utf-8 -*-
"""Resolve a imagem de cada SKU pai para exibição no app.

Cascata: miniatura da foto de e-commerce (pasta do Marketing) > foto do cadastro
(url da Dim Produtos) > 1ª imagem do Shopify (só existe para quem está no site).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
import storage


@st.cache_data(ttl=2400, show_spinner=False)
def _miniaturas(pais: tuple[str, ...], nuvem: bool) -> dict[str, str]:
    """SKU pai -> URL da miniatura. Na nuvem, assinada (validade de 1h)."""
    if nuvem:
        return storage.urls_assinadas(list(pais), validade_s=3600)
    return {p: f"{config.URL_THUMBS_LOCAL}/{p}.jpg"
            for p in pais if (config.PASTA_THUMBS / f"{p}.jpg").exists()}


def coluna_imagem(df: pd.DataFrame) -> pd.Series:
    """Melhor imagem disponível por linha, na ordem da cascata."""
    if df.empty:
        return pd.Series(dtype="object")
    com_foto = tuple(str(p) for p in df.loc[df["tem_foto"] == 1, "pai"])
    nuvem = config.fonte_dados() in ("supabase", "db", "postgres")
    minis = _miniaturas(com_foto, nuvem) if com_foto else {}
    cadastro = df["foto_url"] if "foto_url" in df.columns else pd.Series("", index=df.index)
    shopify = df["img_site"] if "img_site" in df.columns else pd.Series("", index=df.index)
    return pd.Series(
        [minis.get(str(p)) or _texto(c) or _texto(s) or None
         for p, c, s in zip(df["pai"], cadastro, shopify)],
        index=df.index)


def _texto(v) -> str:
    return "" if v is None or pd.isna(v) else str(v).strip()

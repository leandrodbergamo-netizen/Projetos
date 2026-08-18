# -*- coding: utf-8 -*-
"""Miniaturas das fotos no Supabase Storage (bucket privado).

O bucket é privado: o app não expõe URL pública, gera URLs assinadas de curta
duração com a service key que fica nos Secrets do Streamlit. Fala direto com a
API REST do Storage para não adicionar dependência.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import config


def _base() -> tuple[str, str]:
    url = config.segredo("SUPABASE_URL").rstrip("/")
    key = config.segredo("SUPABASE_SERVICE_KEY")
    return url, key


def configurado() -> bool:
    url, key = _base()
    return bool(url and key)


def _chamar(metodo: str, caminho: str, corpo: bytes | None = None,
            content_type: str = "application/json", extra: dict | None = None):
    url, key = _base()
    if not (url and key):
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY não configuradas.")
    req = urllib.request.Request(f"{url}/storage/v1{caminho}", data=corpo, method=metodo)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("apikey", key)
    req.add_header("Content-Type", content_type)
    for k, v in (extra or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=60) as r:
        bruto = r.read()
    return json.loads(bruto) if bruto else None


def garantir_bucket() -> None:
    """Cria o bucket privado se ainda não existir (idempotente)."""
    corpo = json.dumps({"name": config.BUCKET_THUMBS, "id": config.BUCKET_THUMBS,
                        "public": False}).encode()
    try:
        _chamar("POST", "/bucket", corpo)
        print(f"   bucket '{config.BUCKET_THUMBS}' criado (privado).")
    except urllib.error.HTTPError as e:
        if e.code in (400, 409):
            return          # já existe
        raise


def enviar(pais: list[str]) -> int:
    """Sobe as miniaturas destes SKUs pai. Devolve quantas foram enviadas."""
    enviados = 0
    for pai in pais:
        arq = config.PASTA_THUMBS / f"{pai}.jpg"
        if not arq.exists():
            continue
        try:
            _chamar("POST", f"/object/{config.BUCKET_THUMBS}/{pai}.jpg",
                    arq.read_bytes(), "image/jpeg", {"x-upsert": "true"})
            enviados += 1
        except urllib.error.HTTPError as e:
            print(f"   AVISO: falha ao enviar {pai}.jpg ({e.code}).")
    return enviados


def sincronizar(pais: list[str]) -> int:
    """Garante o bucket e envia as miniaturas informadas."""
    if not pais:
        return 0
    garantir_bucket()
    return enviar(pais)


def urls_assinadas(pais: list[str], validade_s: int = 3600) -> dict[str, str]:
    """SKU pai -> URL assinada da miniatura (lote, uma chamada só)."""
    if not pais or not configurado():
        return {}
    corpo = json.dumps({"expiresIn": validade_s,
                        "paths": [f"{p}.jpg" for p in pais]}).encode()
    try:
        resp = _chamar("POST", f"/object/sign/{config.BUCKET_THUMBS}", corpo)
    except urllib.error.HTTPError:
        return {}
    base, _ = _base()
    out: dict[str, str] = {}
    for item in resp or []:
        assinada = item.get("signedURL") or item.get("signedUrl")
        if not assinada or item.get("error"):
            continue
        pai = (item.get("path") or "").removesuffix(".jpg")
        out[pai] = f"{base}/storage/v1{assinada}" if assinada.startswith("/") else assinada
    return out

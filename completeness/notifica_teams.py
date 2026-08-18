# -*- coding: utf-8 -*-
"""Resumo diário da auditoria no Teams (canal Ecom + CRM).

Os "Incoming Webhooks" clássicos do Teams foram descontinuados; o destino agora
é um fluxo (Workflow) do Power Automate. Dois caminhos, os dois suportados aqui
via TEAMS_FORMATO:

  "cartao" (padrão) — fluxo criado pelo próprio Teams:
      canal Ecom + CRM > ⋯ > Fluxos de trabalho >
      "Postar em um canal quando uma solicitação de webhook for recebida".
      Espera um Adaptive Card no corpo.

  "texto" — fluxo montado à mão no Power Automate:
      gatilho "Quando uma solicitação HTTP é recebida" com o esquema
      { "type": "object", "properties": { "text": { "type": "string" } } }
      e ação "Postar mensagem em um chat ou canal" usando @{triggerBody()?['text']}.

Em qualquer um dos casos, cole a URL gerada em TEAMS_WEBHOOK_URL no .env.

Uso:
  python notifica_teams.py            só imprime a mensagem (não envia)
  python notifica_teams.py --enviar   posta no canal
"""
from __future__ import annotations

import json
import sys
import urllib.request

import config
import data_source
import metricas

APP_URL = config.segredo("APP_URL", "")


def montar_mensagem(dados: dict) -> str:
    """Markdown do resumo diário — o Teams renderiza negrito, listas e links."""
    meta = dados["meta"].iloc[0] if not dados["meta"].empty else {}
    disp = dados["disponibilidade"]
    serie = metricas.serie_disponibilidade(metricas.desde_inicio_serie(dados["hist_disp"]))
    serie = serie.sort_values("data")
    delta = (serie.iloc[-1]["pct"] - serie.iloc[-2]["pct"]) if len(serie) >= 2 else None

    candidatos = int(meta.get("candidatos") or len(disp))
    publicados = int(meta.get("publicados") or disp["no_site"].sum())
    pct = publicados / candidatos * 100 if candidatos else 0
    fila = metricas.fila_de_publicacao(disp)
    urgentes = metricas.com_volume_no_cd(fila)

    variacao = ""
    if delta is not None:
        sinal = "+" if delta > 0 else "−"
        variacao = f" ({sinal}{config.numero(abs(delta), 1)} p.p. vs carga anterior)"

    linhas = [
        f"**Completeness do catálogo — {meta.get('data', '')}**",
        "",
        f"- SKUs elegíveis: **{config.numero(candidatos)}**",
        f"- Disponibilidade no site: **{config.numero(pct, 1)}%**{variacao}",
        f"- Fora do site: **{config.numero(candidatos - publicados)}**",
        f"- Com foto pronta e sem publicação: **{config.numero(len(fila))}**"
        + (f" (sendo {config.plural(len(urgentes), 'SKU')} com "
           f"{config.ALERTAS['cd_min_foto_fora']}+ un. no CD)" if len(urgentes) else ""),
        f"- Produtos publicados sem imagem: **{config.numero(int(meta.get('sem_imagem_no_site') or 0))}**",
    ]

    ligados = [a for a in metricas.alertas(dados) if a["alerta"]]
    if ligados:
        linhas += ["", "**Pedindo atenção:**"]
        linhas += [f"- {a['nome']}: **{a['valor']}** — {a['detalhe']}" for a in ligados]
    else:
        linhas += ["", "Nenhum alerta hoje."]

    if not fila.empty:
        linhas += ["", "**Topo da fila de publicação:**"]
        for _, r in fila.head(5).iterrows():
            linhas.append(f"- {r['pai']} {r['item']} ({r['cor']}) — {r['status']}, "
                          f"{config.numero(int(r['qtde']))} un. "
                          f"(CD {config.numero(int(r['qtde_cd']))})")

    if APP_URL:
        linhas += ["", f"[Abrir o painel completo]({APP_URL})"]
    return "\n".join(linhas)


def _corpo(texto: str) -> dict:
    """Payload no formato esperado pelo fluxo configurado."""
    if config.segredo("TEAMS_FORMATO", "cartao").lower() == "texto":
        return {"text": texto}
    return {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": [{"type": "TextBlock", "text": texto, "wrap": True}],
            },
        }],
    }


def enviar(texto: str) -> bool:
    url = config.segredo("TEAMS_WEBHOOK_URL")
    if not url:
        print("AVISO: TEAMS_WEBHOOK_URL não configurada — nada enviado.")
        return False
    corpo = json.dumps(_corpo(texto)).encode("utf-8")
    req = urllib.request.Request(url, data=corpo, method="POST",
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        ok = 200 <= r.status < 300
    print("Resumo postado no Teams." if ok else f"Falha ao postar (HTTP {r.status}).")
    return ok


def notificar(*, enviar_de_verdade: bool = False) -> str:
    texto = montar_mensagem(data_source.carregar_dados())
    if enviar_de_verdade:
        enviar(texto)
    else:
        print("--- mensagem (modo de teste, nada foi enviado) ---")
        print(texto)
    return texto


if __name__ == "__main__":
    notificar(enviar_de_verdade="--enviar" in sys.argv)

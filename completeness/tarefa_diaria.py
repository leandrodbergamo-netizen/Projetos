# -*- coding: utf-8 -*-
"""Rotina diária (no seu PC): coleta, processa, publica e notifica.

É isto que o Agendador de Tarefas roda, logo depois de as bases da pasta
Projetos\\dados serem atualizadas pelo Power Automate:

  1. coleta      -> baixa o catálogo de souqstore.com.br
  2. processa    -> cruza com Base_Produtos/Base_Estoque e grava as séries
  3. publica     -> manda as tabelas comp_* e as miniaturas para o Supabase
  4. notifica    -> posta o resumo no canal Ecom + CRM

Cada etapa falha isolada: um erro na publicação não impede a notificação, e um
erro na coleta interrompe tudo (sem catálogo não há o que gravar).

Uso:
  python tarefa_diaria.py                 completo
  python tarefa_diaria.py --sem-teams     não posta no Teams
  python tarefa_diaria.py --sem-publicar  não sobe para o Supabase
"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime

import atualiza_completeness
import coleta
import config


def _log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    _log(f"== Auditoria de completeness · {config.hoje()} ==")

    _log("Coletando o catálogo do site...")
    prods = coleta.coletar()
    if len(prods) < config.MIN_PRODUTOS_COLETA:
        _log(f"ERRO: coleta devolveu {len(prods)} produtos — abortando sem gravar.")
        return 1
    _log(f"Coleta ok: {len(prods)} produtos.")

    resultado = atualiza_completeness.processar(prods)
    coleta.limpar_cache()

    if "--sem-publicar" not in argv:
        try:
            _log("Publicando no Supabase...")
            import publica_supabase
            publica_supabase.publicar(resultado)
        except SystemExit:
            _log("Publicação ignorada: DATABASE_URL não configurada.")
        except Exception:
            _log("Falha na publicação:")
            traceback.print_exc()

    if "--sem-teams" not in argv:
        try:
            _log("Notificando no Teams...")
            import notifica_teams
            notifica_teams.enviar(notifica_teams.montar_mensagem(
                {"meta": _meta(resultado), "disponibilidade": resultado["dd"],
                 "hist_disp": resultado["hist_disp"], "detalhe": resultado["df"],
                 "historico": resultado["hist"]}))
        except Exception:
            _log("Falha na notificação:")
            traceback.print_exc()

    _log("Rotina concluída.")
    return 0


def _meta(resultado: dict):
    import pandas as pd
    return pd.DataFrame([{**resultado["resumo"],
                          "atualizado": datetime.now().strftime("%d/%m/%Y %H:%M")}])


if __name__ == "__main__":
    sys.exit(main())

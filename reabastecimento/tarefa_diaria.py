"""Tarefa diária (no seu PC): atualiza as planilhas e publica no Supabase.

É isto que o Agendador de Tarefas do Windows deve rodar todo dia de manhã:
  1. refresh_bases.py     -> atualiza Base_Estoque/Base_2026/Base_Produtos (Power Query/Excel)
  2. publica_supabase.py  -> grava os dados preparados no Postgres (app na nuvem lê)
"""
from __future__ import annotations

import traceback


def main() -> None:
    print("== Tarefa diária ==", flush=True)
    try:
        import refresh_bases
        refresh_bases.atualizar()
    except SystemExit:
        raise
    except Exception:
        print("Falha no refresh das planilhas:")
        traceback.print_exc()

    import publica_supabase
    publica_supabase.publicar()


if __name__ == "__main__":
    main()

"""Atualiza (Refresh) as planilhas linkadas ao banco antes do app rodar.

As planilhas Base_Estoque, Base_2026 e Base_Produtos são alimentadas por
Power Query (linkadas ao banco). Este script abre cada uma no Excel, executa
'Atualizar Tudo' (RefreshAll), salva e fecha — para que o app leia os dados
do dia.

Requer Excel instalado e o pacote pywin32:
    pip install pywin32

Agende para rodar TODO DIA (ex.: 06:00) no Agendador de Tarefas do Windows.
Veja as instruções em README.md.
"""
from __future__ import annotations

import sys
import time

import config

# Apenas as bases que vêm do banco e mudam diariamente.
BASES_DIARIAS = [config.ARQ_ESTOQUE, config.ARQS_VENDAS[-1], config.ARQ_PRODUTOS]


def atualizar():
    try:
        import win32com.client as win32
    except ImportError:
        print("ERRO: pywin32 não instalado. Rode: pip install pywin32")
        sys.exit(1)

    excel = win32.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        for caminho in BASES_DIARIAS:
            if not caminho.exists():
                print(f"AVISO: {caminho.name} não encontrado — pulando.")
                continue
            print(f"Atualizando {caminho.name} ...", flush=True)
            wb = excel.Workbooks.Open(str(caminho))
            # Atualiza as conexões de forma síncrona.
            try:
                wb.RefreshAll()
                excel.CalculateUntilAsyncQueriesDone()
            except Exception as e:  # noqa: BLE001
                print(f"  Falha no refresh de {caminho.name}: {e}")
            time.sleep(1)
            wb.Save()
            wb.Close(SaveChanges=True)
            print(f"  OK: {caminho.name}")
    finally:
        excel.Quit()

    # Invalida o cache do dia para o app reconstruir com os dados novos.
    if config.PASTA_CACHE.exists():
        for f in config.PASTA_CACHE.glob("dados_*.pkl"):
            f.unlink()
    print("Atualização concluída.")


if __name__ == "__main__":
    atualizar()

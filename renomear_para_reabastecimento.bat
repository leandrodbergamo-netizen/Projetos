@echo off
REM Renomeia transferencias-lojas para reabastecimento (rode com o VS Code FECHADO)
cd /d "%~dp0"
git mv transferencias-lojas reabastecimento
if errorlevel 1 goto erro
git add reabastecimento
git commit -m "Renomeia projeto para reabastecimento" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push
schtasks /create /f /tn ReabastecimentoRefreshBases /xml "%~dp0tarefa_reabastecimento.xml"
if errorlevel 1 goto fim_tarefa
schtasks /delete /f /tn RemanejamentoRefreshBases
:fim_tarefa
echo.
echo ====================================================================
echo PRONTO. Proximos passos:
echo  1. Reabra o VS Code na pasta C:\Users\LeandroDias\Projetos\reabastecimento
echo  2. Streamlit Cloud (share.streamlit.io): mude o main file do app para
echo     reabastecimento/app.py (Settings; se nao houver o campo, delete e
echo     recrie o app com esse main file e os mesmos Secrets)
echo  3. Pode apagar este .bat e o tarefa_reabastecimento.xml
echo ====================================================================
pause
exit /b 0
:erro
echo ERRO: nao consegui renomear a pasta. Feche o VS Code e outros programas
echo usando a pasta transferencias-lojas e rode este script de novo.
pause
exit /b 1

@echo off
REM Rotina diaria da auditoria de completeness, com log datado em logs\.
REM Registrado no Agendador de Tarefas por setup_agendador.ps1.
cd /d "%~dp0"
if not exist logs mkdir logs
for /f "tokens=1-3 delims=/- " %%a in ('echo %date%') do set HOJE=%%c-%%b-%%a
python tarefa_diaria.py %* >> "logs\completeness_%HOJE%.log" 2>&1
echo Concluido. Log: logs\completeness_%HOJE%.log

@echo off
REM Abre o app de completeness no navegador (http://localhost:8502)
cd /d "%~dp0"
python -m streamlit run app.py --server.port 8502
pause

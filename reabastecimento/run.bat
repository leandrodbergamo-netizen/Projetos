@echo off
REM Inicia o app de reabastecimento no navegador (http://localhost:8501)
cd /d "%~dp0"
python -m streamlit run app.py
pause

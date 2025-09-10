@echo off
setlocal
cd /d %~dp0
call .venv\Scripts\activate
set FLASK_APP=app_finance.py
flask run

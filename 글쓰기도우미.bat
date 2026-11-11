@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 블로그 글쓰기 도우미 시작 중... (이 검은 창은 닫지 마세요)
python -m pip install -q -r requirements.txt
python writer_app.py
if errorlevel 1 pause

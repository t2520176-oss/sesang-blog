@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 네이버 블로그 자동 글쓰기 시작 중... (이 검은 창은 닫지 마세요)
python -m pip install -q -r requirements.txt
python app.py
if errorlevel 1 pause

@echo off
REM Start Pramaan on http://localhost:8000 (API + built dashboard).
cd /d "%~dp0backend"

REM Install, finish a broken install, or add libraries a newer version needs.
REM The marker is versioned and only written when pip succeeds; bump it when requirements.txt changes.
if not exist .venv\installed-v3.ok (
  echo Installing Python libraries - this can take a few minutes...
  if not exist .venv\Scripts\python.exe (
    if exist .venv rmdir /s /q .venv
    python -m venv .venv || (echo. & echo Could not create the environment. Is Python installed and on PATH? & pause & exit /b 1)
  )
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt || (echo. & echo Install failed - see the error above. & pause & exit /b 1)
  echo ok> .venv\installed-v3.ok
)

REM Demo clock: keeps expiry checks reproducible for the synthetic data.
if "%PRAMAAN_TODAY%"=="" set PRAMAAN_TODAY=2026-10-21
if not exist storage\pramaan.db .venv\Scripts\python scripts\seed.py
echo.
echo Open http://localhost:8000  (officer / demo1234)
.venv\Scripts\python -m uvicorn app.main:app --port 8000
pause

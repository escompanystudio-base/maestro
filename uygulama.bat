@echo off
cd /d "%~dp0"
where fnm >nul 2>nul
if not errorlevel 1 (
  for /f "tokens=*" %%i in ('fnm env --shell cmd') do call %%i
)
if "%GEMINI_API_KEY%"=="" (
  for /f "tokens=2,*" %%a in ('reg query HKCU\Environment /v GEMINI_API_KEY 2^>nul') do set "GEMINI_API_KEY=%%b"
)
python gui.py
if errorlevel 1 (
  echo.
  echo Bir sorun olustu. Python kurulu mu? Kontrol icin: python --version
  pause
)

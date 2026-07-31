@echo off
REM Maestro lokal CI: derleme + encoding bekcisi + testler.
REM Kullanim: ci.bat  (proje kokunde)
cd /d "%~dp0"

echo [1/4] Derleme kontrolu...
python -m compileall -q orkestra.py gui.py web_panel.py menu.py runner.py workflow.py constants.py models.py logging_config.py ui_tabs || goto :fail

echo [2/4] Encoding bekcisi...
python tools\check_encoding.py || goto :fail

echo [3/4] Import duman testi...
python -c "import orkestra, runner, web_panel, constants, models, logging_config" || goto :fail

echo [4/4] Testler...
python -m pytest -q || goto :fail

echo.
echo CI OK - hepsi yesil.
exit /b 0

:fail
echo.
echo CI BASARISIZ - yukaridaki adima bak.
exit /b 1

@echo off
REM Cift tiklayinca "su an aktif kurulum var mi?" kontrolunu calistirir.
REM Terminal penceresi sonuclari okuyabilmen icin acik kalir.
cd /d "%~dp0"
python signal_bot.py --check
echo.
pause

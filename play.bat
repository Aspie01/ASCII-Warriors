@echo off
REM ASCII Warriors launcher (Windows)
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 -m ascii_warriors %*
    goto :done
)
where python >nul 2>nul
if %ERRORLEVEL%==0 (
    python -m ascii_warriors %*
    goto :done
)
echo ASCII Warriors needs Python 3.9 or newer on your PATH.
echo Get it from https://www.python.org/downloads/
pause
exit /b 1
:done
endlocal

@echo off
rem ===========================================================================
rem  SuperMrWang AI setup - one click on Windows.
rem
rem  Pure ASCII on purpose: cmd parses .bat with the active code page, and
rem  non-ASCII in a UTF-8 file turns into mojibake on some systems. All the
rem  Chinese text comes from setup_ai.py instead (we set chcp 65001 below).
rem
rem  No nested if-blocks anywhere: a ">=" inside a block gets parsed as a
rem  redirection and cmd answers with "... was unexpected at this time".
rem  Plain gotos only.
rem
rem  Usage:  double-click, or  setup-ai.bat --model sd15 --dir D:\lb-ai
rem ===========================================================================
setlocal enableextensions
chcp 65001 >nul
title SuperMrWang AI setup

set "HERE=%~dp0"
set "SETUP=%HERE%setup_ai.py"

if not exist "%SETUP%" goto :no_setup

call :find_python
if defined PYEXE goto :run

call :fetch_python
if errorlevel 1 goto :no_python

:run
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
%PYEXE% "%SETUP%" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :failed
if not defined LB_NO_PAUSE (
  echo.
  pause
)
exit /b 0

rem ---- subroutines -----------------------------------------------------------

:find_python
set "PYEXE="
where py >nul 2>nul
if errorlevel 1 goto :try_plain
py -3 -c "import sys" >nul 2>nul
if errorlevel 1 goto :try_plain
set "PYEXE=py -3"
goto :eof

:try_plain
where python >nul 2>nul
if errorlevel 1 goto :eof
rem the Windows Store stub answers "where" but fails on every real call
python -c "import sys" >nul 2>nul
if errorlevel 1 goto :eof
set "PYEXE=python"
goto :eof

:fetch_python
echo.
echo   No Python found. Downloading a temporary one (about 11 MB)...
echo.
set "TMPPY=%TEMP%\lb-setup-python"
if exist "%TMPPY%" rmdir /s /q "%TMPPY%" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $d='%TMPPY%'; New-Item -ItemType Directory -Force -Path $d | Out-Null; Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-amd64.zip' -OutFile \"$d\py.zip\"; Expand-Archive -Path \"$d\py.zip\" -DestinationPath $d -Force"
if errorlevel 1 exit /b 1
set "PYEXE=%TMPPY%\python.exe"
if not exist "%PYEXE%" exit /b 1
exit /b 0

rem ---- error exits -----------------------------------------------------------

:no_setup
echo.
echo   ERROR: setup_ai.py not found next to this file.
echo   Keep both files in the same folder.
echo.
if not defined LB_NO_PAUSE pause
exit /b 1

:no_python
echo.
echo   ERROR: could not get Python automatically.
echo   Install Python 3.8+ from https://www.python.org/downloads/
echo   then run this file again.
echo.
if not defined LB_NO_PAUSE pause
exit /b 1

:failed
echo.
echo   Setup ended with code %RC%. Scroll up for the reason.
echo.
if not defined LB_NO_PAUSE pause
exit /b %RC%

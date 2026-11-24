@echo off
rem ===========================================================================
rem  SuperMrWang AI assets - download models / node packs with one double-click.
rem
rem  Pure ASCII on purpose: cmd parses .bat with the active code page, and
rem  non-ASCII in a UTF-8 file turns into mojibake on some systems. All the
rem  Chinese text comes from setup_comfy.py itself (chcp 65001 below).
rem
rem  No nested if-blocks: a ">=" inside a block is parsed as a redirection and
rem  cmd answers with "... was unexpected at this time". Plain gotos only.
rem
rem  Usage:  double-click, or
rem          setup-comfy.bat --tier full
rem          setup-comfy.bat --home D:\ComfyUI --python D:\ComfyUI\py312\python.exe
rem ===========================================================================
setlocal enableextensions
chcp 65001 >nul
title SuperMrWang AI assets

set "HERE=%~dp0"
set "SETUP=%HERE%setup_comfy.py"

if not exist "%SETUP%" goto :no_setup

call :find_python
if defined PYEXE goto :probe
goto :no_python

rem ---- 1) 先体检，把「缺什么、多大」摆出来 ---------------------------------
:probe
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
echo.
echo   === AI assets check ===
echo.
%PYEXE% "%SETUP%" --check %*
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" goto :done
if "%RC%"=="2" goto :no_comfy

echo.
choice /c yn /n /m "  Download the missing files now? [Y/N] "
if errorlevel 2 goto :cancelled

echo.
%PYEXE% "%SETUP%" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :failed
goto :done

:done
echo.
echo   All set. Restart ComfyUI (or let GIMP start it) and use:
echo     SuperMrWang - AI - AI Inpaint / AI Select by Name
echo.
if not defined LB_NO_PAUSE pause
exit /b 0

:cancelled
echo.
echo   Nothing downloaded.
echo.
if not defined LB_NO_PAUSE pause
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

rem ---- error exits -----------------------------------------------------------

:no_setup
echo.
echo   ERROR: setup_comfy.py not found next to this file.
echo   Keep both files in the same folder.
echo.
if not defined LB_NO_PAUSE pause
exit /b 1

:no_python
echo.
echo   ERROR: no Python found.
echo   Install Python 3.8+ from https://www.python.org/downloads/
echo   (tick "Add python.exe to PATH") and run this file again.
echo.
if not defined LB_NO_PAUSE pause
exit /b 1

:no_comfy
echo.
echo   ComfyUI was not found. Two options:
echo     1) already installed: pass its folder
echo          setup-comfy.bat --home D:\ComfyUI
echo     2) not installed yet: run setup-ai.bat first
echo.
if not defined LB_NO_PAUSE pause
exit /b 2

:failed
echo.
echo   Finished with code %RC%. Scroll up for the reason;
echo   running it again resumes interrupted downloads.
echo.
if not defined LB_NO_PAUSE pause
exit /b %RC%

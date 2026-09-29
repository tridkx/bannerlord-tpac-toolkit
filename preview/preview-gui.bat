@echo off
rem ===========================================================
rem  Bannerlord outfit - offline animation preview (GUI)
rem
rem  Double-click this file, or run it from a shell.
rem
rem  The data source is picked automatically (or given as the
rem  first argument). Any argument starting with "-" is passed
rem  straight through to the Python GUI, e.g.:
rem
rem      preview-gui.bat --pack D:\mod\AssetPackages\pack0.tpac
rem      preview-gui.bat --project D:\dsh-mod\mb-xianjian7
rem      preview-gui.bat --selftest
rem
rem  This .bat is intentionally PURE ASCII: cmd.exe reads .bat
rem  files using the *console* code page, so non-ASCII text here
rem  garbles or even breaks parsing depending on the locale.
rem  All Chinese messages come from the Python side, which pins
rem  its own encoding (see reconfigure() in mbpreview_gui.py).
rem
rem  Structure note: this file is written as a **flat sequence of
rem  if/goto**, not nested ( ) blocks. Deeply nested blocks with
rem  quoted paths inside are where cmd.exe starts mis-parsing
rem  (classic "X was unexpected at this time.").
rem ===========================================================
chcp 65001 >nul 2>nul
setlocal EnableExtensions
title Bannerlord outfit - animation preview

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"

echo ===========================================================
echo   Bannerlord outfit  -  offline animation preview
echo ===========================================================
echo.

rem ---------------- 1. locate python ----------------
set "PY="
set "PYA="
if defined MB_PYTHON if exist "%MB_PYTHON%" set "PY=%MB_PYTHON%"
if defined PY goto :py_done

python -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto :py_done

py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=py" & set "PYA=-3"
if defined PY goto :py_done

for %%p in (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "%USERPROFILE%\anaconda3\python.exe"
    "%USERPROFILE%\miniconda3\python.exe"
    "C:\ProgramData\anaconda3\python.exe"
) do if not defined PY if exist "%%~p" set "PY=%%~p"
if defined PY goto :py_done

echo [ERROR] Python 3.10+ not found.
echo.
echo   Install Python, or set MB_PYTHON to the full path of python.exe:
echo       set MB_PYTHON=D:\Python313\python.exe
echo.
pause
exit /b 1

:py_done
echo [ok] python  : %PY% %PYA%

rem ---------------- 2. figure out the data source ----------------
rem  Arguments that start with "-" belong to the Python GUI.
set "FIRST=%~1"
set "PASSTHRU="
if not defined FIRST goto :no_first_arg
if "%FIRST:~0,1%"=="-" set "PASSTHRU=%*" & set "FIRST="
:no_first_arg

set "PACK="
set "PROJ="
if not defined FIRST goto :no_path_arg
if /i "%~x1"==".tpac" set "PACK=%~f1"
if not defined PACK set "PROJ=%~f1"
:no_path_arg

if defined PACK goto :have_source
if defined PROJ goto :have_source

if not defined MB_PACK goto :try_mb_project
if exist "%MB_PACK%" set "PACK=%MB_PACK%"
:try_mb_project
if defined PACK goto :have_source
if not defined MB_PROJECT goto :try_conf
if exist "%MB_PROJECT%\work" set "PROJ=%MB_PROJECT%"
:try_conf
if defined PACK goto :have_source
if defined PROJ goto :have_source
if not exist "%HERE%\preview.conf" goto :try_known
for /f "usebackq tokens=1,* delims==" %%a in ("%HERE%\preview.conf") do call :read_conf "%%a" "%%b"
:try_known
if defined PACK goto :have_source
if defined PROJ goto :have_source

for %%p in (
    "%HERE%\..\mb-xianjian7"
    "%HERE%\..\..\mb-xianjian7"
    "%HERE%\..\mb2mod-ada"
    "%HERE%\..\..\mb2mod-ada"
    "D:\dsh-mod\mb-xianjian7"
    "C:\dsh-mod\mb-xianjian7"
    "D:\dsh-mod\mb2mod-ada"
    "C:\dsh-mod\mb2mod-ada"
) do if not defined PROJ if exist "%%~p\work\posed" set "PROJ=%%~fp"
if defined PROJ goto :have_source

for %%f in ("%HERE%\*.tpac") do if not defined PACK set "PACK=%%~ff"
if defined PACK goto :have_source

echo [ERROR] No data source found.
echo.
echo   Any one of these works:
echo     1) drag a .tpac onto this .bat
echo     2) drag an outfit project folder onto this .bat
echo     3) create preview.conf next to this .bat with one line:
echo            pack=D:\path\to\pack0.tpac
echo        or  project=D:\path\to\your\project
echo     4) set MB_PACK or MB_PROJECT
echo     5) run:  preview-gui.bat --pack ^<pack0.tpac^>
echo.
echo   Inside the GUI: press M to open a .tpac, Shift+M for a project.
echo.
pause
exit /b 1

:have_source
set "SRCARGS="
if not defined PACK goto :src_project
echo [ok] source  : %PACK%
set SRCARGS=--pack "%PACK%"
goto :src_anims
:src_project
echo [ok] source  : %PROJ%
set SRCARGS=--project "%PROJ%"
:src_anims
if not exist "%HERE%\anims" goto :launch
rem  Animations live beside this script: they are VANILLA GAME data,
rem  identical for every outfit project, so they are not per-project.
set SRCARGS=%SRCARGS% --anim-dir "%HERE%\anims"

:launch
echo.
echo controls: drag=rotate  wheel=zoom  Tab=switch char  1..9=switch anim
echo           space=pause  comma/period=step frame  T=textures
echo           M=open a .tpac  R=reset view  S=screenshot  ESC=quit
echo.

"%PY%" %PYA% "%HERE%\mbpreview_gui.py" %SRCARGS% --nframes 48 %PASSTHRU%

if errorlevel 1 (
    echo.
    echo [ERROR] preview exited with a non-zero code - see messages above.
    pause
)

endlocal
exit /b 0

rem ---------------- helper: one line of preview.conf ----------------
:read_conf
if /i "%~1"=="pack" if exist "%~2" set "PACK=%~2"
if /i "%~1"=="project" if exist "%~2\work" set "PROJ=%~2"
goto :eof
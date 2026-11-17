@echo off
rem scope-gui.bat: opens the SCOPE graphical interface from a source checkout, with nothing to set up by hand (Windows).
rem
rem The first time, it finds a Python 3.12, creates a private virtual environment, installs SCOPE (editable, with the
rem GUI extra) from this folder and opens the window. Later starts reuse the environment. It is reinstalled by itself
rem when core\pyproject.toml changes (for instance after "git pull").
rem
rem   scope-gui.bat                  open the GUI
rem   scope-gui.bat -n env.npy       open the GUI with an Environment file
rem   scope-gui.bat --check          build the window, print one line and exit (tests the installation)
rem   scope-gui.bat --reinstall      reinstall SCOPE into the private environment, then open the GUI
rem   scope-gui.bat --where          print where the private environment lives, and exit
rem
rem SCOPE_GUI_HOME=C:\some\folder    keeps the private environment somewhere else
rem SCOPE_GUI_PYTHON=C:\path\python.exe   uses that Python (must be 3.12) instead of searching for one
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "CORE=%ROOT%\core"
if not exist "%CORE%\pyproject.toml" goto nocore

if defined SCOPE_GUI_HOME goto homeset
set "HOMEDIR=%LOCALAPPDATA%\scope\launcher"
goto homedone
:homeset
set "HOMEDIR=%SCOPE_GUI_HOME%"
:homedone
set "VENV=%HOMEDIR%\venv"
set "VPY=%VENV%\Scripts\python.exe"
set "STAMP=%HOMEDIR%\installed.stamp"

set "REINSTALL=0"
set "ARGS="
:parse
if "%~1"=="" goto parsed
if /I "%~1"=="--where" goto where
if /I "%~1"=="--reinstall" goto flagreinstall
set ARGS=!ARGS! %1
goto nextarg
:flagreinstall
set "REINSTALL=1"
:nextarg
shift
goto parse
:where
echo %VENV%
exit /b 0
:parsed

if not exist "%VPY%" goto create
call :is312 "%VPY%"
if errorlevel 1 goto wrongvenv
goto have_venv

:create
set "PY="
if defined SCOPE_GUI_PYTHON goto usegiven
rem the "py" launcher first, then the usual names on PATH
for /f "usebackq delims=" %%P in (`py -3.12 -c "import sys; print(sys.executable)" 2^>nul`) do if not defined PY set "PY=%%P"
if defined PY goto havepy
for %%N in (python3.12.exe python.exe python3.exe) do (
    if not defined PY (
        for /f "delims=" %%W in ('where %%N 2^>nul') do (
            if not defined PY (
                call :is312 "%%W"
                if not errorlevel 1 set "PY=%%W"
            )
        )
    )
)
if defined PY goto havepy
goto nopython

:usegiven
call :is312 "%SCOPE_GUI_PYTHON%"
if errorlevel 1 goto badgiven
set "PY=%SCOPE_GUI_PYTHON%"

:havepy
echo scope-gui: first start. Creating the private environment with %PY% in %VENV%
if not exist "%HOMEDIR%" mkdir "%HOMEDIR%"
"%PY%" -m venv "%VENV%"
if errorlevel 1 goto venvfail
set "REINSTALL=1"

:have_venv
call :fingerprint
if "%REINSTALL%"=="1" goto install
set "OLD="
if exist "%STAMP%" set /p OLD=<"%STAMP%"
if "!OLD!"=="!FP!" goto launch
echo scope-gui: core\pyproject.toml changed, updating the installation.

:install
echo scope-gui: installing SCOPE and the GUI from %CORE% (internet needed; the first time takes a few minutes).
if exist "%STAMP%" del "%STAMP%"
"%VPY%" -m pip install --disable-pip-version-check -e "%CORE%[gui]"
if errorlevel 1 goto installfail
>"%STAMP%" echo !FP!

:launch
"%VPY%" -c "from scope.cli.main import main; main()" gui %ARGS%
exit /b %errorlevel%

:is312
"%~1" -c "import sys; sys.exit(0 if sys.version_info[:2]==(3,12) else 1)" >nul 2>&1
exit /b %errorlevel%

:fingerprint
set "FP="
for /f "skip=1 tokens=*" %%H in ('certutil -hashfile "%CORE%\pyproject.toml" MD5') do if not defined FP set "FP=%%H"
set "FP=!FP: =!"
exit /b 0

:nocore
echo scope-gui: cannot find core\pyproject.toml next to this script (%ROOT%). 1>&2
exit /b 1

:badgiven
echo scope-gui: SCOPE_GUI_PYTHON=%SCOPE_GUI_PYTHON% is not a Python 3.12. 1>&2
exit /b 1

:nopython
echo scope-gui: SCOPE needs Python 3.12 (not 3.11, not 3.13) and none was found. 1>&2
echo Install it, then run scope-gui.bat again: 1>&2
echo   winget install Python.Python.3.12      (or download it from python.org; tick "Add python.exe to PATH") 1>&2
echo   or with conda:  conda create -n scope python=3.12   then   conda activate scope   and set SCOPE_GUI_PYTHON to the output of "where python" 1>&2
exit /b 1

:wrongvenv
echo scope-gui: the private environment in %VENV% is not Python 3.12 (was Python replaced?). Delete that folder and run scope-gui.bat again. 1>&2
exit /b 1

:venvfail
echo scope-gui: could not create the virtual environment. 1>&2
exit /b 1

:installfail
echo scope-gui: the installation failed. Check the internet connection and run scope-gui.bat again (scope-gui.bat --reinstall retries from scratch). 1>&2
exit /b 1

@echo off
setlocal EnableDelayedExpansion
rem =====================================================================
rem  SkyWatch first-run bootstrap + launcher (Windows).
rem  Double-click this, or run from cmd. Forwards any extra args to
rem  python -m skywatch (so `start.bat -wifi wlan0` still works).
rem =====================================================================

rem --- Make the script's own folder the working dir ---
pushd "%~dp0"

echo.
echo ============================================================
echo  SkyWatch launcher
echo ============================================================

rem --- 1. Pick a Python interpreter ---
rem  Priority order:
rem    a) Bundled embeddable Python at tools\python-win64\python.exe
rem       (testers get this — no system Python needed).
rem    b) System Python (py launcher / python on PATH) for developers.
set VENVPY=
if exist "tools\python-win64\python.exe" (
    set VENVPY=tools\python-win64\python.exe
    echo [OK] Using bundled Python:
    "!VENVPY!" --version
    goto :launch
)

set PYEXE=
where py >NUL 2>NUL
if %ERRORLEVEL% EQU 0 (
    set PYEXE=py -3
) else (
    where python >NUL 2>NUL
    if %ERRORLEVEL% EQU 0 (
        set PYEXE=python
    )
)
if "%PYEXE%"=="" (
    echo [X] Python is not installed or not on PATH, and tools\python-win64\
    echo     does not contain a bundled interpreter.
    echo.
    echo     Tester instructions: see QUICKSTART.md — your bundle is missing
    echo     the tools\python-win64\ folder. Re-download the SkyWatch zip.
    echo.
    echo     Developer instructions: install Python 3.10+ from
    echo     https://www.python.org/downloads/  (tick "Add Python to PATH").
    goto :fail
)

%PYEXE% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if %ERRORLEVEL% NEQ 0 (
    echo [X] Python 3.10 or newer is required.
    %PYEXE% --version
    goto :fail
)
echo [OK] Found system Python:
%PYEXE% --version

rem --- 2. Create venv if missing ---
if not exist ".venv\Scripts\python.exe" (
    echo [..] Creating virtual environment in .venv ...
    %PYEXE% -m venv .venv
    if %ERRORLEVEL% NEQ 0 (
        echo [X] venv creation failed.
        goto :fail
    )
)
set VENVPY=.venv\Scripts\python.exe
echo [OK] Virtual environment: .venv

rem --- 3. Install / refresh dependencies on first run or when
rem        requirements.txt changes. We use a marker file whose timestamp
rem        is compared against requirements.txt. ---
set MARKER=.venv\skywatch.installed
set NEED_INSTALL=0
if not exist "%MARKER%" set NEED_INSTALL=1
if exist "%MARKER%" (
    for %%F in ("requirements.txt") do set REQ_TIME=%%~tF
    for %%F in ("%MARKER%")        do set MARK_TIME=%%~tF
    rem Lexicographic compare on dd/mm/yyyy hh:mm strings is unreliable;
    rem rely on PowerShell to compare actual file timestamps.
    powershell -NoProfile -Command "if ((Get-Item 'requirements.txt').LastWriteTime -gt (Get-Item '%MARKER%').LastWriteTime) { exit 1 } else { exit 0 }"
    if !ERRORLEVEL! NEQ 0 set NEED_INSTALL=1
)

if "%NEED_INSTALL%"=="1" (
    echo [..] Installing dependencies from requirements.txt ...
    "%VENVPY%" -m pip install --upgrade pip >NUL
    "%VENVPY%" -m pip install -r requirements.txt
    if !ERRORLEVEL! NEQ 0 (
        echo [X] pip install failed. Check the output above.
        goto :fail
    )
    rem Patch pyrtlsdr for older librtlsdr.dll builds (rtl-sdr-blog v4
    rem ships without rtlsdr_set_dithering / set_bias_tee). Idempotent.
    "%VENVPY%" -m skywatch._patch_pyrtlsdr
    echo installed > "%MARKER%"
    echo [OK] Dependencies installed.
) else (
    echo [OK] Dependencies up to date.
)

:launch

rem --- 4. Sanity check: bundled tools folder ---
rem  Note: do NOT use "[!!]" here — delayed expansion (enabled at the top
rem  of this script) treats `!!` as an empty variable reference and
rem  silently strips it from the printed line.
if exist "tools\win64\rtlsdr.dll" (
    echo [OK] Bundled tools detected: tools\win64\
) else (
    echo [WARN] tools\win64\ is missing rtlsdr.dll
    echo        RTL-SDR features will not work until you drop the rtl-sdr-blog
    echo        Windows release into tools\win64\. See tools\README.md.
)

rem --- 5. Launch ---
echo.
echo ============================================================
echo  Launching SkyWatch.  Open http://localhost:8080
echo  (Ctrl+C in this window stops the server.)
echo ============================================================
echo.
"%VENVPY%" -m skywatch %*
set RC=%ERRORLEVEL%

popd
echo.
if %RC% NEQ 0 (
    echo [ERR] SkyWatch exited with code %RC%.
    pause
)
exit /b %RC%

:fail
popd
echo.
pause
exit /b 1

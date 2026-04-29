@echo off
setlocal EnableDelayedExpansion
rem =====================================================================
rem  SkyWatch — maintainer-side bundling helper.
rem
rem  WHO RUNS THIS: only the person preparing a tester drop.
rem                 Testers DO NOT run this. They run start.bat.
rem
rem  WHAT IT DOES:
rem    1. Downloads the Windows embeddable-zip Python distribution.
rem    2. Extracts it into tools\python-win64\.
rem    3. Patches python_._pth so site-packages are importable.
rem    4. Bootstraps pip into the embeddable Python.
rem    5. pip-installs requirements.txt into the embeddable's
rem       Lib\site-packages\ directly (no venv — embeddable Python's
rem       venv module isn't reliably configured).
rem
rem  RESULT: tools\python-win64\ becomes a portable, self-contained
rem    Python that start.bat detects automatically. Zip the project
rem    folder and ship it. Testers don't need to install Python.
rem
rem  USAGE:
rem    .\scripts\setup-bundle.bat            (uses default 3.13.x)
rem    .\scripts\setup-bundle.bat 3.13.7     (override version)
rem =====================================================================

pushd "%~dp0\.."

rem --- Configurable Python version ---
set PYVER=%~1
if "%PYVER%"=="" set PYVER=3.13.7
echo Target Python version: %PYVER%

set DEST=tools\python-win64
set ZIPNAME=python-%PYVER%-embed-amd64.zip
set ZIPURL=https://www.python.org/ftp/python/%PYVER%/%ZIPNAME%
set ZIPPATH=%TEMP%\%ZIPNAME%

if exist "%DEST%\python.exe" (
    echo.
    echo [!!] %DEST%\ already contains a python.exe.
    echo      Delete it first if you want a clean rebuild:
    echo        rmdir /s /q "%DEST%"
    goto :end
)

rem --- 1. Download embeddable zip ---
echo.
echo [..] Downloading %ZIPURL% ...
powershell -NoProfile -Command ^
    "$ProgressPreference='SilentlyContinue';" ^
    "Invoke-WebRequest -Uri '%ZIPURL%' -OutFile '%ZIPPATH%'"
if not exist "%ZIPPATH%" (
    echo [X] Download failed. Check internet connection / version number.
    goto :fail
)

rem --- 2. Extract into tools\python-win64\ ---
echo [..] Extracting to %DEST% ...
if not exist "%DEST%" mkdir "%DEST%"
powershell -NoProfile -Command ^
    "Expand-Archive -Path '%ZIPPATH%' -DestinationPath '%DEST%' -Force"
if not exist "%DEST%\python.exe" (
    echo [X] Extraction failed.
    goto :fail
)
del "%ZIPPATH%"

rem --- 3. Patch the ._pth so site-packages AND the project root are on
rem        sys.path. The project root (..\..) is needed so `python -m
rem        skywatch` works from inside tools\python-win64\.
echo [..] Patching python._pth (enable site-packages, add project root) ...
powershell -NoProfile -Command ^
    "Get-ChildItem '%DEST%\python*._pth' | ForEach-Object {" ^
    "    $p = $_.FullName;" ^
    "    $c = (Get-Content $p) -replace '^#import site', 'import site';" ^
    "    if (-not ($c -contains 'import site')) { $c += 'import site' };" ^
    "    if (-not ($c -contains '..\\..')) { $c = ,'..\\..' + $c };" ^
    "    Set-Content -Path $p -Value $c -Encoding ASCII;" ^
    "}"

rem --- 4. Bootstrap pip ---
echo [..] Bootstrapping pip ...
powershell -NoProfile -Command ^
    "$ProgressPreference='SilentlyContinue';" ^
    "Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile '%TEMP%\get-pip.py'"
"%DEST%\python.exe" "%TEMP%\get-pip.py" --no-warn-script-location
if %ERRORLEVEL% NEQ 0 (
    echo [X] pip bootstrap failed.
    goto :fail
)
del "%TEMP%\get-pip.py"

rem --- 5. Install project deps into embeddable Python ---
echo [..] Installing requirements.txt into bundled Python ...
"%DEST%\python.exe" -m pip install --no-warn-script-location -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo [X] pip install failed.
    goto :fail
)

rem --- 6. Apply the pyrtlsdr patch (older librtlsdr DLLs lack newer symbols) ---
echo [..] Patching pyrtlsdr ...
"%DEST%\python.exe" -m skywatch._patch_pyrtlsdr

echo.
echo ============================================================
echo  Bundle ready.
echo  Verify with:    "%DEST%\python.exe" -m skywatch -version
echo  Then run:       start.bat
echo  To ship:        zip the whole project folder (tools\ included).
echo ============================================================
goto :end

:fail
echo.
echo Setup failed. See messages above.
popd
exit /b 1

:end
popd
exit /b 0

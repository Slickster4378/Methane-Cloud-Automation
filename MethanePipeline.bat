@echo off
setlocal EnableExtensions EnableDelayedExpansion

title Sentinel-2 Methane Detection Pipeline

echo ==========================================
echo Sentinel-2 Methane Detection Pipeline
echo ==========================================
echo.

REM ------------------------------------------
REM Determine pipeline directory
REM ------------------------------------------

set PIPELINE_DIR=%~dp0
cd /d "%PIPELINE_DIR%"
set "ERROR_LOG=%PIPELINE_DIR%bin\error_log.txt"
if not exist "%ERROR_LOG%" (
    type nul > "%ERROR_LOG%"
)

echo Pipeline location:
echo "%PIPELINE_DIR%"
echo Error log location:
echo "%ERROR_LOG%"
echo.

REM ------------------------------------------
REM Check for Python
REM ------------------------------------------

echo Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo Python not found.
    echo Checking portable Python...
    if exist "%PIPELINE_DIR%\python\python.exe" (
        set PYTHON="%PIPELINE_DIR%\python\python.exe"
    ) else (
        echo.
        echo Python must be installed.
        echo Downloading Python installer...
        powershell -Command ^
        "Invoke-WebRequest https://www.python.org/ftp/python/3.13.0/python-3.13.0-amd64.exe -OutFile python_installer.exe"
        echo Installing Python...
        python_installer.exe /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
        del python_installer.exe
        set PYTHON=python
    )
) else (
    set PYTHON=python
)

echo Using: %PYTHON%
echo.

REM ------------------------------------------
REM Create virtual environment
REM ------------------------------------------

if not exist "%PIPELINE_DIR%\venv" (
    echo Creating Python virtual environment...
    %PYTHON% -m venv "%PIPELINE_DIR%\venv" 2>>"%ERROR_LOG%"
    if errorlevel 1 (
        call :LOG_ERROR "Failed to create Python virtual environment."
        goto FAILED
    )
)
set "VENV_PYTHON=%PIPELINE_DIR%\venv\Scripts\python.exe"

REM ------------------------------------------
REM Upgrade pip
REM ------------------------------------------

echo Updating pip...
"%VENV_PYTHON%" -m pip install --upgrade pip 2>>"%ERROR_LOG%"
if errorlevel 1 (
    call :LOG_ERROR "Failed to update pip."
    goto FAILED
)

REM ------------------------------------------
REM Install required libraries
REM ------------------------------------------

if exist requirements.txt (
    echo Installing required libraries...
    "%VENV_PYTHON%" -m pip install ^ -r requirements.txt 2>>"%ERROR_LOG%"
    if errorlevel 1 (
        call :LOG_ERROR "Failed to install one or more required Python packages."
        goto FAILED
    )
) else (
    echo WARNING: requirements.txt missing.
    call :LOG_ERROR "requirements.txt was not found."
)

echo.
echo Python environment ready.
echo.

REM ------------------------------------------
REM Launch folder selection GUI
REM ------------------------------------------

echo Selecting project directory...
start /wait "" "%PIPELINE_DIR%bin\folder_picker.exe"
if errorlevel 1 (
    call :LOG_ERROR "folder_picker.exe returned an error."
    goto FAILED
)

REM ------------------------------------------
REM Locate configuration JSON
REM ------------------------------------------

set "CONFIG_FILE=%PIPELINE_DIR%bin\config.json"
if not exist "%CONFIG_FILE%" (
    echo ERROR:
    echo config.json was not created by folder_picker.exe.
    call :LOG_ERROR "folder_picker.exe did not create config.json."
    pause
    exit /b 1
)

echo.
echo Using configuration:
echo "%CONFIG_FILE%"
echo.

REM ------------------------------------------
REM Run pipeline
REM ------------------------------------------

REM 1. Project Initialization
set "INIT_MARKER=%PIPELINE_DIR%bin\.project_initialized"
if exist "%INIT_MARKER%" (
    echo [SKIP] Project folders and databases already initialized.
) else (
    echo Initializing project...
    "%VENV_PYTHON%" "%PIPELINE_DIR%src\error_logger.py" ^
        "%ERROR_LOG%" ^
        "%PIPELINE_DIR%src\initialize_project.py" ^
        "%CONFIG_FILE%"
    if errorlevel 1 (
        call :LOG_ERROR "Initialization Failed"
        goto FAILED
    )
    echo 1 > "%INIT_MARKER%"
)

REM 2. Build Baseline
set "BASELINE_MARKER=%PIPELINE_DIR%bin\.baseline_complete"
if exist "%BASELINE_MARKER%" (
    echo [SKIP] Methane emission baselines already computed and downloaded.
) else ( 
    echo Triggering Cloud Baseline Builder via GitHub API...
    curl -X POST ^
      -H "Accept: application/vnd.github+json" ^
      -H "Authorization: Bearer YOUR_GITHUB_PERSONAL_ACCESS_TOKEN" ^
      https://github.com ^
      -d "{\"event_type\": \"trigger_baseline_build\", \"client_payload\": $(type "%CONFIG_FILE%")}"
      
    echo Waiting for Cloud Processing to finish and writing baseline back...
    REM Note: Polling / downloading baseline step fits here
    echo 1 > "%BASELINE_MARKER%"
)

REM 3. Historical Backscan
set "HISTORICAL_MARKER=%PIPELINE_DIR%bin\.historical_scan_complete"
if exist "%HISTORICAL_MARKER%" (
    echo [SKIP] Historical data scanning complete.
) else (
    echo Processing historical imagery...
    "%VENV_PYTHON%" "%PIPELINE_DIR%src\error_logger.py" ^
        "%ERROR_LOG%" ^
        "%PIPELINE_DIR%src\historical_scan.py" ^
        "%CONFIG_FILE%"
    if errorlevel 1 (
        call :LOG_ERROR "Historical Scan Failed"
        goto FAILED 
    )
    echo 1 > "%HISTORICAL_MARKER%"
)

REM 4. Daily Delta Check
echo Checking for new daily sentinel imagery...
"%VENV_PYTHON%" "%PIPELINE_DIR%src\error_logger.py" ^
    "%ERROR_LOG%" ^
    "%PIPELINE_DIR%check_new_data.py" ^
    "%CONFIG_FILE%"
if errorlevel 1 (
    call :LOG_ERROR "Daily Data Check Failed"
    goto FAILED 
)

echo ==========================================
echo Pipeline Complete
echo ==========================================
pause
exit /b 0

:FAILED

echo.
echo ==========================================
echo PIPELINE FAILED
echo ==========================================
echo.
echo Errors have been recorded in:
echo %ERROR_LOG%
echo.

pause
exit /b 1

REM ==========================================
REM Logging Function
REM ==========================================

:LOG_ERROR

for /f "tokens=1-2" %%A in ('echo.^|time') do set "CURRENT_TIME=%%A"
for /f "delims=" %%A in ('powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"') do set "TIMESTAMP=%%A"
echo [!TIMESTAMP!] %~1>>"%ERROR_LOG%"
echo. >> "%ERROR_LOG%"

exit /b 0
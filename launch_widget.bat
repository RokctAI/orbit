@echo off
setlocal enabledelayedexpansion

echo ========================================================
echo   🛸 Orbit Client Daemon Widget Bootstrapper
echo ========================================================

:: 1. Check Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python was not found on this system.
    echo Please install Python 3.10+ and add it to your PATH.
    pause
    exit /b 1
)

:: 2. Check Git
where git >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Git was not found on this system.
    echo Please install Git and add it to your PATH.
    pause
    exit /b 1
)

:: 3. Target Directory Setup to avoid polluting local folder
set "TARGET_DIR=%USERPROFILE%\.orbit\widget_src"
if not exist "%TARGET_DIR%" (
    mkdir "%TARGET_DIR%"
)

if not exist "%TARGET_DIR%\pyproject.toml" (
    echo [INFO] Orbit codebase not detected. Cloning repository into %TARGET_DIR%...
    git clone https://github.com/RokctAI/orbit.git "%TARGET_DIR%"
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to clone the repository.
        pause
        exit /b 1
    )
)

cd /d "%TARGET_DIR%"

:: 3.5 Check for Updates (Fetch remote origin and compare version.json)
git fetch origin >nul 2>&1
if %errorlevel% equ 0 (
    git show origin/main:version.json > .version_remote.json 2>nul
    if !errorlevel! equ 0 (
        python -c "import json, sys; sys.exit(0 if json.load(open('version.json'))['version'] == json.load(open('.version_remote.json'))['version'] else 1)" >nul 2>&1
        set "VERSION_CHANGED=!errorlevel!"
        del .version_remote.json >nul 2>&1
        if !VERSION_CHANGED! neq 0 (
            echo [INFO] Local version is out of sync with remote. Updating local files...
            git reset --hard origin/main >nul 2>&1
            if exist .venv\installed.tag del .venv\installed.tag >nul 2>&1
        )
    )
)

:: 4. Build Virtual Environment if missing
if not exist ".venv" (
    echo [INFO] Creating Python virtual environment...
    python -m venv .venv
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

:: 5. Install Dependencies and Orbit
if not exist ".venv\installed.tag" (
    echo [INFO] Installing Orbit package and dependencies (this may take a moment)...
    .venv\Scripts\python -m pip install --upgrade pip
    .venv\Scripts\pip install -e .
    if !errorlevel! neq 0 (
        echo [ERROR] Installation failed.
        pause
        exit /b 1
    )
    echo installed > .venv\installed.tag
)

:: 6. Setup Auto-start (Shortcut in Windows Startup folder)
set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT_PATH=%STARTUP_FOLDER%\OrbitWidget.lnk"
if not exist "%SHORTCUT_PATH%" (
    echo [INFO] Registering Orbit Widget for auto-start on Windows startup...
    powershell -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%SHORTCUT_PATH%'); $Shortcut.TargetPath = '%TARGET_DIR%\launch_widget.bat'; $Shortcut.WorkingDirectory = '%TARGET_DIR%'; $Shortcut.WindowStyle = 7; $Shortcut.Save()"
)

:: 7. Launch Widget in background using pythonw
echo [INFO] Launching Orbit Floating Status Bar Widget...
start .venv\Scripts\pythonw.exe -m orbit.cli widget
echo [SUCCESS] Widget launched successfully in the background and registered for auto-start.
exit /b 0

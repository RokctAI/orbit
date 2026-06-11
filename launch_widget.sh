#!/bin/bash

# Exit on error
set -e

echo "========================================================"
echo "  🛸 Orbit Client Daemon Widget Bootstrapper (macOS/Linux)"
echo "========================================================"

# 1. Check Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3 was not found on this system."
    echo "Please install Python 3.10+ using Homebrew or from python.org."
    exit 1
fi

# 2. Check Git
if ! command -v git &> /dev/null; then
    echo "[ERROR] Git was not found on this system."
    echo "Please install Git."
    exit 1
fi

# 3. Target Directory Setup to avoid polluting local folder
TARGET_DIR="$HOME/.orbit/widget_src"
mkdir -p "$TARGET_DIR"

if [ ! -f "$TARGET_DIR/pyproject.toml" ]; then
    echo "[INFO] Orbit codebase not detected. Cloning repository into $TARGET_DIR..."
    git clone https://github.com/RokctAI/orbit.git "$TARGET_DIR"
    if [ $? -ne 0 ]; then
        echo "[ERROR] Failed to clone the repository."
        exit 1
    fi
fi

cd "$TARGET_DIR"

# 3.5 Check for Updates (Fetch remote origin and compare version.json)
if git fetch origin >/dev/null 2>&1; then
    if git show origin/main:version.json > .version_remote.json 2>/dev/null; then
        if python3 -c "import json, sys; sys.exit(0 if json.load(open('version.json'))['version'] == json.load(open('.version_remote.json'))['version'] else 1)" >/dev/null 2>&1; then
            : # Versions match
        else
            echo "[INFO] Local version is out of sync with remote. Updating local files..."
            git reset --hard origin/main >/dev/null 2>&1
            rm -f .venv/installed.tag >/dev/null 2>&1
        fi
        rm -f .version_remote.json >/dev/null 2>&1
    fi
fi

# 4. Build Virtual Environment if missing
if [ ! -d ".venv" ]; then
    echo "[INFO] Creating Python virtual environment..."
    python3 -m venv .venv
    if [ $? -ne 0 ]; then
        echo "[ERROR] Failed to create virtual environment."
        exit 1
    fi
fi

# 5. Install Dependencies and Orbit
if [ ! -f ".venv/installed.tag" ]; then
    echo "[INFO] Installing Orbit package and dependencies..."
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/pip install -e .
    if [ $? -ne 0 ]; then
        echo "[ERROR] Installation failed."
        exit 1
    fi
    echo "installed" > .venv/installed.tag
fi

# 6. Setup Auto-start (macOS Launch Agent)
if [ "$(uname)" == "Darwin" ]; then
    PLIST_PATH="$HOME/Library/LaunchAgents/com.rokctai.orbit.widget.plist"
    if [ ! -f "$PLIST_PATH" ]; then
        echo "[INFO] Registering Orbit Widget for auto-start on macOS..."
        mkdir -p "$HOME/Library/LaunchAgents"
        cat <<EOF > "$PLIST_PATH"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.rokctai.orbit.widget</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$TARGET_DIR/launch_widget.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
EOF
        launchctl load "$PLIST_PATH" 2>/dev/null || true
    fi
fi

# 7. Launch Widget in background
echo "[INFO] Launching Orbit Floating Status Bar Widget..."
nohup .venv/bin/python -m orbit.cli widget >/dev/null 2>&1 &
echo "[SUCCESS] Widget launched successfully in the background and registered for auto-start."

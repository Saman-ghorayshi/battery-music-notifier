#!/bin/env bash

# Stop execution if any single command fails
set -e

echo "🎵 Initializing Battery Music Notifier setup..."

# Detect if the runtime environment is Android Termux
if [ -n "$TERMUX_VERSION" ]; then
    echo "🤖 Android Termux environment detected!"
    echo "📦 Auto-provisioning pre-compiled platform binaries..."
    
    # Synchronize package indexes and install pre-compiled system ports
    pkg update -y
    pkg install -y python python-psutil termux-api git clang binutils
    
    echo "✅ System binaries successfully mapped."
else
    echo "💻 Desktop operating system environment detected. Skipping system package injection."
fi

# Execute the local packaging installation cleanly
echo "🐍 Bundling Python dependencies and creating executable commands..."
pip install -e .

echo "============================================================"
echo "🎉 SUCCESS: Installation complete!"
echo "👉 Run 'battery-music doctor' to verify your configurations."
echo "============================================================"
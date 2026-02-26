#!/usr/bin/env bash
# Build script for Render.com - installs Chrome + Python deps

set -e

echo "=== Installing Python dependencies ==="
pip install --upgrade pip
pip install -r requirements.txt

echo "=== Installing Google Chrome ==="
apt-get update -qq
apt-get install -y -qq wget gnupg2
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add -
echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list
apt-get update -qq
apt-get install -y -qq google-chrome-stable

echo "=== Chrome version ==="
google-chrome --version

echo "=== Build complete ==="

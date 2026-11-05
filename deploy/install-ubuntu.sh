#!/usr/bin/env bash
set -euo pipefail
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip ffmpeg espeak-ng git curl
sudo mkdir -p /opt/linguacall
sudo chown "$(id -un):$(id -gn)" /opt/linguacall
echo 'Copy the repository into /opt/linguacall then run: cd /opt/linguacall/ai-server && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt'

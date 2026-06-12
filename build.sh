#!/usr/bin/env bash
set -e

pip install -r requirements.txt

# Install ffmpeg — Render free tier runs Ubuntu so apt is available
apt-get install -y ffmpeg

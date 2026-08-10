#!/bin/bash
echo "=========================================="
echo "MINITRON Server Installation"
echo "=========================================="

cd "$(dirname "$0")"

# Install Python 3.11 (matching your working version)
sudo apt update
sudo apt install -y software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev

# Install Chrome (headless for server)
wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install -y ./google-chrome-stable_current_amd64.deb
rm google-chrome-stable_current_amd64.deb

# Create virtual environment with Python 3.11
python3.11 -m venv minitron_env

# Activate and install packages
source minitron_env/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

echo ""
echo "=========================================="
echo "Installation Complete!"
echo "=========================================="
echo ""
echo "To start MINITRON: ./launch.sh"
echo "Access at: http://SERVER_IP:8501"
echo ""

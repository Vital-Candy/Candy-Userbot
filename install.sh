#!/usr/bin/env bash
# install.sh — установка и запуск Candy-Userbot одной командой
set -e

REPO_URL="https://github.com/Vital-Candy/Candy-Userbot.git"
REPO_DIR="Candy-Userbot"

# Если запущен не изнутри клонированного репозитория — клонируем его
if [ ! -f "main.py" ] || [ ! -f "requirements.txt" ]; then
    if [ -d "$REPO_DIR" ]; then
        cd "$REPO_DIR"
    else
        echo "📥 Клонирую репозиторий..."
        git clone "$REPO_URL"
        cd "$REPO_DIR"
    fi
fi

echo "=============================================="
echo "  Установка Candy-Userbot"
echo "=============================================="

PIP_FLAGS=""

if command -v pkg >/dev/null 2>&1; then
    echo "[1/3] Termux: обновление пакетов..."
    pkg update -y && pkg upgrade -y
    pkg install -y python git
elif command -v apt >/dev/null 2>&1; then
    echo "[1/3] Debian/Ubuntu: проверка python3/pip/git..."
    command -v python3 >/dev/null 2>&1 || sudo apt install -y python3
    command -v pip3 >/dev/null 2>&1 || sudo apt install -y python3-pip
    command -v git >/dev/null 2>&1 || sudo apt install -y git
    PIP_FLAGS="--break-system-packages"
else
    echo "[1/3] Убедитесь, что установлены python3, pip3 и git."
fi

echo "[2/3] Установка зависимостей Python..."
python3 -m pip install --upgrade pip $PIP_FLAGS
python3 -m pip install -r requirements.txt $PIP_FLAGS

echo "[3/3] Первый запуск (потребуются api_id/api_hash с my.telegram.org/apps)..."
python3 main.py

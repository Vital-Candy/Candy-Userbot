#!/bin/bash

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}🍬 Candy-Userbot Installer${NC}"
echo "=============================="

# Определяем пакетный менеджер
if [ -d "/data/data/com.termux" ]; then
    echo -e "${YELLOW}Обнаружен Termux${NC}"
    PKG="pkg"

    if [ ! -d "/sdcard" ]; then
        echo "Запустите:"
        echo "termux-setup-storage"
        echo "и выдайте доступ к памяти."
        exit 1
    fi
else
    PKG="apt"
fi

# Python
if ! command -v python3 >/dev/null 2>&1; then
    echo "Устанавливаю Python..."
    $PKG update -y
    $PKG install -y python
fi

# Git
if ! command -v git >/dev/null 2>&1; then
    echo "Устанавливаю Git..."
    $PKG install -y git
fi

# Проверка версии Python (без bc)
PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 9 ]; }; then
    echo -e "${RED}Нужен Python 3.9+, у вас ${PY_MAJOR}.${PY_MINOR}${NC}"
    exit 1
fi

INSTALL_DIR="$HOME/Candy-Userbot"

# Если проекта нет — клонируем
if [ ! -d "$INSTALL_DIR/.git" ]; then
    echo "Клонирование Candy-Userbot..."
    git clone https://github.com/Vital-Candy/Candy-Userbot.git "$INSTALL_DIR"

    if [ $? -ne 0 ]; then
        echo -e "${RED}Ошибка клонирования репозитория.${NC}"
        exit 1
    fi
else
    echo "Candy-Userbot уже установлен."
fi

cd "$INSTALL_DIR" || exit 1

echo -e "${YELLOW}Установка зависимостей...${NC}"
pip install -r requirements.txt

if [ $? -ne 0 ]; then
    echo -e "${RED}Ошибка установки зависимостей.${NC}"
    exit 1
fi

echo
echo -e "${GREEN}✅ Установка завершена!${NC}"
echo
echo "Проект установлен в:"
echo "$INSTALL_DIR"
echo
echo "Запуск:"
echo "cd \"$INSTALL_DIR\""
echo "python3 main.py"
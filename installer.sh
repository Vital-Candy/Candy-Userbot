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
    INSTALL_DIR="$HOME/Candy-Userbot"
else
    PKG="apt"
    INSTALL_DIR="$(pwd)/Candy-Userbot"
fi

# Проверка Python
if ! command -v python3 >/dev/null 2>&1; then
    echo "Устанавливаем Python..."
    $PKG update -y && $PKG install python3 -y
fi

# Проверка Git
if ! command -v git >/dev/null 2>&1; then
    echo "Устанавливаем Git..."
    $PKG install git -y
fi

# Проверка версии Python
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if [[ $(echo "$PY_VER < 3.9" | bc) -eq 1 ]]; then
    echo -e "${RED}Нужна Python 3.9+, у вас $PY_VER${NC}"
    exit 1
fi

# Клонирование проекта
if [ ! -d "$INSTALL_DIR/.git" ]; then
    echo -e "${YELLOW}Клонирование Candy-Userbot...${NC}"
    rm -rf "$INSTALL_DIR"
    git clone https://github.com/Vital-Candy/Candy-Userbot.git "$INSTALL_DIR"
    if [ $? -ne 0 ]; then
        echo -e "${RED}Не удалось клонировать репозиторий.${NC}"
        exit 1
    fi
fi

cd "$INSTALL_DIR" || exit 1

# Установка зависимостей
echo -e "${YELLOW}Установка зависимостей...${NC}"
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

echo
echo -e "${GREEN}✅ Установка завершена!${NC}"
echo
echo "Проект установлен в:"
echo "$INSTALL_DIR"
echo
echo "Запуск:"
echo "cd \"$INSTALL_DIR\""
echo "python3 main.py"
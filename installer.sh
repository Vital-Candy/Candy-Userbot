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
    # Даём доступ к /sdcard, если ещё не дали
    if [ ! -d "/sdcard" ]; then
        echo "Запустите termux-setup-storage и дайте разрешение."
        exit 1
    fi
else
    PKG="apt"
fi

# Проверка Python
if ! command -v python3 &> /dev/null; then
    echo "Устанавливаем Python..."
    $PKG update -y && $PKG install python3 -y
fi

# Проверка Git
if ! command -v git &> /dev/null; then
    echo "Устанавливаем Git..."
    $PKG install git -y
fi

# Проверка версии Python
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if [[ $(echo "$PY_VER < 3.9" | bc) -eq 1 ]]; then
    echo -e "${RED}Нужна Python 3.9+, у вас $PY_VER${NC}"
    exit 1
fi

# Проверяем, что мы в папке проекта
if [ ! -f "main.py" ]; then
    echo -e "${YELLOW}Похоже, мы не в папке Candy-Userbot.${NC}"
    echo "Клонирую репозиторий в текущую директорию..."
    git clone https://github.com/Vital-Candy/Candy-Userbot.git temp
    cp -r temp/* .
    cp -r temp/.[!.]* . 2>/dev/null || true
    rm -rf temp
fi

# Установка зависимостей
echo -e "${YELLOW}Установка зависимостей...${NC}"
pip install --upgrade pip
pip install -r requirements.txt

# Создаём скрипт для простого запуска
cat > run.sh << 'EOF'
#!/bin/bash
python3 main.py
EOF
chmod +x run.sh

echo -e "${GREEN}✅ Установка завершена!${NC}"
echo "Теперь запустите: ./run.sh"
echo "Если вы в Termux, убедитесь, что дали доступ к хранилищу (termux-setup-storage)."
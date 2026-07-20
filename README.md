<div align="center">

# 🍬 Candy-Userbot

**Модульный Telegram userbot на Telethon**

Горячая перезагрузка модулей · Обновление через `git pull` · Кроссплатформенность (Linux / macOS / Windows / Termux)

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Telethon](https://img.shields.io/badge/Telethon-1.36%2B-2CA5E0?logo=telegram&logoColor=white)](https://docs.telethon.dev/)
[![License](https://img.shields.io/badge/License-Attribution--Required-orange)](./LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20macOS%20%7C%20Windows%20%7C%20Termux-lightgrey)](#)

</div>

---

## ⚡ Установка одной командой

```bash
curl -fsSL https://raw.githubusercontent.com/Vital-Candy/Candy-Userbot/main/install.sh | bash
```

Или вручную:

```bash
git clone https://github.com/Vital-Candy/Candy-Userbot.git
cd Candy-Userbot
bash install.sh
```

Скрипт сам поставит зависимости (на Termux и Debian/Ubuntu — автоматически; на других системах нужны Python 3.9+, pip и git) и запустит бота.
При первом запуске бот попросит `api_id` и `api_hash` — получить их можно на [my.telegram.org/apps](https://my.telegram.org/apps).

> 🔒 Никакие ключи, токены и сессии в репозитории не хранятся. `config.json` и `*.session` создаются локально при первом запуске и исключены через `.gitignore`.

## 🚀 Запуск в дальнейшем

```bash
cd Candy-Userbot
python3 main.py
```

## 🧩 Команды ядра

| Команда | Описание |
|---|---|
| `.help [команда]` | Список команд / справка по команде |
| `.ping` | Задержка |
| `.alive` | Статус бота |
| `.reload` | Горячая перезагрузка всех модулей |
| `.restart` | Полный перезапуск процесса |
| `.stop` | Остановка бота |
| `.clear` | Очистка кеша, `__pycache__` и логов |
| `.update` | Обновление из GitHub (`git pull`) и перезапуск |

Остальные команды — по модулям в `modules/` (`.download`, `.qr`, `.tag`, `.timer`, `.purge`, `.spam`, `.user`, `.time`, `.roast`/`.praise`). Полный список и синтаксис — через `.help`.

## 📁 Структура проекта

```
core/       — клиент, диспетчер команд, загрузчик модулей
modules/    — функциональные модули (каждый: init()/shutdown())
utils/      — общие пути, логгер, вспомогательные функции
assets/     — баннер, логотип для .alive
```

## 🔄 Обновление

`.update` выполняет `git fetch` + `git reset --hard @{u}` в папке бота и перезапускает процесс. Работает только если бот установлен через `git clone`. `config.json`, файлы сессии и кеш в `.gitignore` — обновление их не затронет.

## 🛠 Разработка модулей

Модуль — файл в `modules/`. Обязателен `def init()`, желателен `def shutdown()` (или `async def shutdown()`), который снимает зарегистрированные обработчики через `client.remove_event_handler(...)`. Без этого при `.reload` обработчики будут дублироваться.

## 📜 Лицензия и авторство

Проект распространяется по [собственной лицензии с обязательным указанием авторства](./LICENSE) — использовать, форкать и изменять код можно свободно, но **любая публичная копия или производная работа обязана указывать автора и ссылку на оригинал**:

> Автор: **Abdurahmon** ([@Vital-Candy](https://github.com/Vital-Candy)) · Оригинал: https://github.com/Vital-Candy/Candy-Userbot

Публикация форка без указания авторства нарушает условия лицензии.

---

<div align="center">Сделано с 🍬 · <a href="https://github.com/Vital-Candy">Vital-Candy</a></div>

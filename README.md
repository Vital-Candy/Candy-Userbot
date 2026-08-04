<div align="center">

<img src="assets/banner.txt" alt="" />

# 🍬 Candy Userbot

**Модульный Telegram userbot на Python + Telethon**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![Telethon](https://img.shields.io/badge/Telethon-1.36%2B-2CA5E0?logo=telegram&logoColor=white)](https://docs.telethon.dev)
[![License](https://img.shields.io/badge/License-Attribution--Required-orange)](./LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Termux%20%7C%20Linux%20%7C%20macOS-lightgrey)](#)

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

> Скрипт автоматически установит зависимости (Termux и Debian/Ubuntu).  
> При первом запуске добавь аккаунт через меню, введя `api_id` и `api_hash` с [my.telegram.org/apps](https://my.telegram.org/apps).

---

## 🚀 Запуск

```bash
cd Candy-Userbot
python3 main.py
```

При запуске откроется **консольное меню**:

```
  АККАУНТЫ

  [1]  Ivan Petrov  @ivanpetrov
  [2]  Work Account @workaccount

  A  — Добавить аккаунт
  B  — Восстановить из бэкапа
  0  — Выход
```

Выбери цифру → бот запустится для этого аккаунта.  
`.stop` или `Ctrl+C` → вернуться в меню и сменить аккаунт.

---

## 👥 Мультиаккаунт

Candy Userbot поддерживает несколько аккаунтов одновременно — каждый хранится отдельно в `accounts/<username>/`. Сессии никогда не попадают в git.

| Действие | Как |
|---|---|
| Добавить аккаунт | `A` в меню → введи API данные |
| Переключить аккаунт | `.stop` → выбери другой номер |
| Создать бэкап | `.backup` в чате → файл на `/sdcard` |
| Восстановить на другом устройстве | `B` в меню → укажи путь к zip |

---

## 📋 Команды

### Система (встроены в ядро)

| Команда | Описание |
|---|---|
| `.help [команда]` | Список всех команд / справка |
| `.ping` | Задержка бота |
| `.alive` | Статус и аптайм |
| `.reload` | Горячая перезагрузка модулей |
| `.restart` | Перезапустить процесс |
| `.stop` | Остановить → вернуться в меню |
| `.clear` | Очистить кеш и логи |
| `.backup` | Бэкап аккаунта на `/sdcard` |
| `.update` | Обновить из GitHub (`git pull`) |

### Модули

| Команда | Описание |
|---|---|
| `.save` | Сохранить исчезающее фото / видео / кружочек |
| `.user [@username]` | Информация о пользователе |
| `.purge <N> [all]` | Удалить N сообщений |
| `.spam <N> <текст>` | Отправить сообщение N раз |
| `.tag all / random N` | Упомянуть участников группы |
| `.time on [1-5]` | Живые часы в имени (5 стилей) |
| `.time off` | Выключить часы, восстановить имя |
| `.timer 10 / 1.30 / 2.00.00` | Таймер с уведомлением |

---

## 📁 Структура проекта

```
Candy-Userbot/
├── core/
│   ├── accounts.py   — мультиаккаунт: добавление, бэкап, восстановление
│   ├── client.py     — прокси-клиент (смена аккаунта без перезапуска)
│   ├── dispatcher.py — встроенные команды, реестр для .help
│   └── loader.py     — загрузка / горячая перезагрузка модулей
├── modules/          — подключаемые модули (init / shutdown)
├── utils/            — пути, логгер, вспомогательные функции
├── assets/           — баннер, логотип для .alive
├── accounts/         — сессии аккаунтов (в .gitignore)
├── main.py           — точка входа, консольное меню
├── config.py         — версия, автор
├── install.sh        — установка одной командой
└── requirements.txt
```

---

## 🔧 Разработка модулей

Модуль — это `.py` файл в `modules/`. Минимальный шаблон:

```python
from telethon import events
from core.client import client
from core.dispatcher import register_command

_registered_handlers = []

def init():
    global _registered_handlers
    for h in _registered_handlers:
        client.remove_event_handler(h)
    _registered_handlers = []

    register_command("mycommand", "Описание", ".mycommand", category="инструменты")
    h = client.add_event_handler(my_handler,
        events.NewMessage(outgoing=True, pattern=r"^\.mycommand$"))
    _registered_handlers.append(h)

def shutdown():
    for h in _registered_handlers:
        client.remove_event_handler(h)
    _registered_handlers.clear()

async def my_handler(event):
    await event.edit("✅ Работает!")
```

Кинь файл в `modules/` → `.reload` подхватит без перезапуска.

---

## 🔒 Безопасность

- `accounts/`, `*.session`, `config.json` в `.gitignore` — ключи никогда не попадут в репозиторий
- Бэкапы создаются локально на устройстве, не передаются никуда

---

## 📜 Лицензия

Распространяется по [лицензии с обязательным указанием авторства](./LICENSE).  
Использовать, форкать и изменять — свободно, но любая публичная копия обязана указывать:

> Автор: [@Vital-Candy](https://github.com/Vital-Candy) · Оригинал: https://github.com/Vital-Candy/Candy-Userbot

---

<div align="center">Сделано с 🍬 · <a href="https://github.com/Vital-Candy">Vital-Candy</a></div>

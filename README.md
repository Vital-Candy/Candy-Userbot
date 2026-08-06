# 🍬 Candy-Userbot

<p align="center">
  <b>Мощный Telegram Userbot на Telethon с модульной архитектурой, поддержкой нескольких аккаунтов и фоновыми задачами.</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9+-blue?logo=python">
  <img src="https://img.shields.io/badge/Telethon-1.36+-26A5E4?logo=telegram">
  <img src="https://img.shields.io/badge/Platform-Termux%20%7C%20Linux-success">
  <img src="https://img.shields.io/badge/License-Apache%202.0-green">
</p>

---

## ✨ Возможности

- 🚀 Высокая производительность благодаря `asyncio`.
- 👤 Поддержка нескольких Telegram-аккаунтов.
- 🧩 Простая модульная архитектура.
- 🔄 Горячая перезагрузка модулей.
- ⚙️ Фоновые задачи с сохранением состояния.
- 💾 Backup и восстановление аккаунтов.
- 🔄 Автоматическое обновление через GitHub.
- 📱 Полная поддержка Android (Termux) и Linux.

---

## 🚀 Установка

### Termux

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Vital-Candy/Candy-Userbot/main/installer.sh)"
```

### Linux

```bash
git clone https://github.com/Vital-Candy/Candy-Userbot.git
cd Candy-Userbot
pip install -r requirements.txt
python3 main.py
```

---

## 📖 Основные команды

| Команда | Описание |
|---------|----------|
| `.help` | Список команд |
| `.alive` | Информация о боте |
| `.ping` | Проверка задержки |
| `.spam` | Массовая отправка сообщений |
| `.time` | Часы в имени |
| `.reload` | Перезагрузить модули |
| `.update` | Обновить Userbot |
| `.restart` | Перезапустить Userbot |
| `.stop` | Вернуться в меню |
| `.clear` | Очистить кэш и лог |

---

## 📂 Структура проекта

```text
Candy-Userbot/
├── accounts/
├── assets/
├── core/
├── modules/
├── utils/
├── config.py
├── main.py
└── requirements.txt
```

---

## 🧩 Создание собственного модуля

1. Создай файл в `modules/`.
2. Реализуй функцию `init()`.
3. При необходимости добавь `shutdown()`.
4. Зарегистрируй команду через `register_command()`.
5. Используй `BackgroundManager` для фоновых задач.

Все модули автоматически загружаются при запуске.

---

## 🔄 Обновление

Userbot умеет обновляться напрямую из GitHub.

Во время обновления:

- проверяется новая версия;
- создаётся резервная копия;
- выполняется обновление через Git;
- при ошибке выполняется автоматический откат;
- личные данные пользователя не затрагиваются.

Не изменяются:

- `accounts/`
- `backups/`
- `*.session`
- `*.session-journal`
- `__pycache__/`
- `*.pyc`
- `userbot.log`

---

## 💾 Backup

Поддерживается создание резервных копий аккаунтов и их быстрое восстановление через встроенное меню.

---

## 🤝 Разработка

Проект имеет полностью модульную архитектуру.

Каждый модуль изолирован и может:

- регистрировать команды;
- запускать фоновые задачи;
- сохранять собственное состояние;
- корректно выгружаться без перезапуска всего Userbot.

---

## 📄 Лицензия

Проект распространяется по лицензии **Apache License 2.0**.

© Vital-Candy

---

<p align="center">
  <b>🍬 Candy-Userbot — быстрый, модульный и удобный Userbot для Telegram.</b>
</p>
# 🍬 Candy-Userbot

![Python](https://img.shields.io/badge/Python-3.9%2B-blue?logo=python)
![Telethon](https://img.shields.io/badge/Telethon-1.36%2B-26A5E4?logo=telegram)
![Platform](https://img.shields.io/badge/Platform-Android%20%7C%20Linux-success)
![License](https://img.shields.io/badge/License-Apache%202.0-green)

**Candy-Userbot** — современный асинхронный Telegram Userbot, построенный на **Telethon** с модульной архитектурой, поддержкой нескольких аккаунтов и системой фоновых задач.

Проект разработан с упором на производительность, стабильность и удобство расширения. Работает в **Termux**, Linux и других Unix-подобных системах.

---

# ✨ Возможности

- 🚀 Поддержка нескольких аккаунтов.
- 🧩 Полностью модульная архитектура.
- ⚡ Горячая перезагрузка модулей без перезапуска.
- 🔄 Фоновые задачи с сохранением состояния.
- 💾 Автоматические резервные копии.
- 📦 Обновление прямо из GitHub.
- 📱 Полная совместимость с Android (Termux).
- 🛠 Простое создание собственных модулей.
- 📂 Независимое состояние для каждого аккаунта.
- 📜 Подробное логирование.

---

# 🚀 Быстрая установка

## Android (Termux)

```bash
pkg update
pkg install git python -y
termux-setup-storage

bash -c "$(curl -fsSL https://raw.githubusercontent.com/Vital-Candy/Candy-Userbot/main/installer.sh)"
🍬 Candy‑Userbot

https://img.shields.io/badge/Python-3.9%2B-blue?logo=python
https://img.shields.io/badge/Telethon-1.36+-blue?logo=telegram
https://img.shields.io/badge/License-Apache%202.0-green.svg
https://img.shields.io/badge/Platform-Android%20%7C%20Linux-lightgrey

Candy‑Userbot — мощный асинхронный юзербот для Telegram с поддержкой нескольких аккаунтов, модульной архитектурой и фоновыми задачами. Работает на Android (Termux) и Linux.

---

🚀 Установка за 1 минуту

Скопируйте и выполните в Termux (или в терминале Linux):

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Vital-Candy/Candy-Userbot/main/installer.sh)"
```

Или вручную:

```bash
git clone https://github.com/Vital-Candy/Candy-Userbot.git
cd Candy-Userbot
pip install -r requirements.txt
python main.py
```

Для Termux предварительно выполните termux-setup-storage и дайте доступ к хранилищу.

---

✨ Возможности

· ✅ Мультиаккаунтность — лёгкое переключение между аккаунтами.
· ✅ Модульная система — добавляйте свои команды без перезапуска.
· ✅ Фоновые задачи — например, часы в имени, автоответчики.
· ✅ Встроенные команды:
  · .help — справка
  · .alive — статус
  · .ping — задержка
  · .spam — массовая рассылка
  · .time — стильные часы в имени
  · .reload, .restart, .stop, .clear
· ✅ Бэкапы — создание и восстановление аккаунтов.

---

📚 Команды

Команда Описание
.help [команда] Справка
.alive Статус и аптайм
.ping Проверка задержки
.spam текст [-c кол-во] [-s задержка] Отправить несколько сообщений (по умолч. 5, макс 50)
.spam stop Остановить спам
.time [on <1-5>/off] Часы в имени (5 стилей)
.reload Перезагрузить модули
.restart Перезапустить юзербота
.stop Вернуться в меню выбора аккаунта
.clear Очистить кеш и лог

---

🧩 Структура проекта

```
Candy-Userbot/
├── assets/                 # баннер, лого
├── core/                   # ядро (менеджеры, клиент, загрузчик)
├── modules/                # плагины (команды)
├── utils/                  # утилиты (пути, логгер)
├── accounts/               # данные аккаунтов (создаётся автоматически)
├── backup/                 # резервные копии
├── config.py               # версия, владелец, префикс
├── main.py                 # точка входа
└── requirements.txt
```

---

🛠 Для разработчиков

Добавление своего модуля

1. Создайте modules/my_module.py.
2. Реализуйте синхронные или асинхронные init() и shutdown().
3. Зарегистрируйте команду через register_command().
4. Используйте глобальный клиент: import core.client as client_state.

Пример: смотрите modules/ping.py.

Фоновые задачи

Используйте BackgroundManager вашего аккаунта:

```python
manager = _account.background
await manager.start("task_name", worker)
manager.set_state("task_name", {"enabled": True})
```

---

📄 Лицензия

Этот проект распространяется под лицензией Apache License 2.0 — подробности в файле LICENSE.
Вы обязаны указывать оригинальное авторство (© Vital-Candy) и не удалять уведомления о лицензии.

---

🙏 Благодарности

· Telethon — за основу.
· Всем, кто тестирует и предлагает идеи.

---

🍬 Candy‑Userbot — сделано с ❤️ в Termux
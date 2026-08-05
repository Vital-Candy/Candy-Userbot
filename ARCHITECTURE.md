# Candy-Userbot: архитектура фоновых задач

## Что добавлено

`core/background_manager.py` — универсальная система фоновых задач.

Каждый аккаунт создаёт собственный:

```text
accounts/<account>/background_state.json
```

Менеджер умеет:

- запускать задачу по имени;
- не создавать дубликат;
- проверять состояние;
- останавливать одну задачу;
- останавливать все задачи;
- хранить JSON-состояние;
- атомарно записывать состояние через временный файл;
- корректно обрабатывать `CancelledError`.

## Как будущий модуль будет использовать систему

Пример:

```python
from core.client import client

# В будущем контекст аккаунта будет передаваться модулю.
# Пока BackgroundManager доступен через Account:
manager = account.background

await manager.start(
    "time_name",
    worker,
)

manager.set_state(
    "time_name",
    {
        "enabled": True,
        "original_name": "Candy",
        "style": "normal",
    },
)
```

## Важное правило

`BackgroundManager` не знает, что такое часы.

- `time_name` сам сохраняет `original_name`;
- `time_name` сам восстанавливает имя при `.stop`;
- `time_bio` будет отдельным модулем;
- менеджер только управляет задачами и состоянием.

## Проверка

```bash
cd ~/Candy-Userbot
python -m compileall -q .
python main.py
```

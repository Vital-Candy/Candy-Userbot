-- Начальная схема: метки сообщений и права доступа.
-- Все данные изолированы по Telegram account_id.

-- Метки: именованная пометка конкретного сообщения (одно сообщение может иметь много меток).
-- metadata_json хранит произвольные данные метки в виде JSON-объекта.
CREATE TABLE IF NOT EXISTS labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    creator_id INTEGER,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(account_id, chat_id, message_id, name)
);

-- Поиск и перебор меток по имени (.label list, .goto).
CREATE INDEX IF NOT EXISTS idx_labels_account_name
    ON labels(account_id, name);
-- Все метки одного сообщения. Покрывает и выборку по чату целиком (общий префикс).
CREATE INDEX IF NOT EXISTS idx_labels_message
    ON labels(account_id, chat_id, message_id);

-- Права: каким пользователям (subject_id) разрешены команды userbot; уровень в поле permission.
CREATE TABLE IF NOT EXISTS permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    subject_id INTEGER NOT NULL,
    permission TEXT NOT NULL,
    granted_by INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(account_id, subject_id, permission)
);

-- Все права одного пользователя. Частично дублирует префикс UNIQUE(account_id, subject_id, ...).
CREATE INDEX IF NOT EXISTS idx_permissions_subject
    ON permissions(account_id, subject_id);

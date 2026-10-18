-- Собственное пространство плагинов: ключ-значение (JSON), отдельно для каждого
-- аккаунта и плагина.

-- WITHOUT ROWID: строки адресуются составным первичным ключом, отдельный rowid не нужен.
CREATE TABLE IF NOT EXISTS plugin_data (
    account_id INTEGER NOT NULL,
    plugin TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(account_id, plugin, key)
) WITHOUT ROWID;

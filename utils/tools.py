def get_args(event):
    """Извлекает список аргументов из сообщения после команды.
    Пример: .user @username → ['@username']
    """
    text = event.raw_text
    parts = text.strip().split(maxsplit=1)
    if len(parts) > 1:
        return parts[1].split()
    return []
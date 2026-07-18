import json

def is_allowed(user_id: int) -> bool:
    """Проверяет, разрешён ли пользователь."""
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
        ALLOWED_USERS = config.get("allowed_users", [])
        return user_id in ALLOWED_USERS
    except Exception:
        return False
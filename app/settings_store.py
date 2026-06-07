"""settings 配置项读写数据访问层（按用户隔离）。"""
from app.db import get_connection

KEY_API_KEY = "deepseek_api_key"

DEFAULT_EMBED_MODEL = "BAAI/bge-small-zh-v1.5"
DEFAULT_LLM_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_LLM_MODEL = "deepseek-chat"


def get_setting(user_id: int, key: str, default: str = "") -> str:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT value FROM settings WHERE user_id = ? AND key = ?",
            (user_id, key),
        ).fetchone()
        return row["value"] if row and row["value"] is not None else default
    finally:
        conn.close()


def set_setting(user_id: int, key: str, value: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO settings (user_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value",
            (user_id, key, value),
        )
        conn.commit()
    finally:
        conn.close()


def get_all_settings(user_id: int) -> dict:
    return {
        KEY_API_KEY: get_setting(user_id, KEY_API_KEY),
    }

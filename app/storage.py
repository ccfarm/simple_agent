"""资料本地文件存储与分类目录管理（按用户隔离）。"""
import re
from pathlib import Path

DOC_TYPES = ("report", "news", "announcement")

TYPE_DIR = {
    "report": "reports",
    "news": "news",
    "announcement": "announcements",
}

TYPE_LABEL = {
    "report": "研报",
    "news": "新闻",
    "announcement": "公告",
}

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_ROOT = BASE_DIR / "data" / "users"


def get_user_data_root(user_id: int) -> Path:
    """某个用户的资料根目录：data/users/{user_id}/stocks。"""
    return DATA_ROOT / str(user_id) / "stocks"


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff-]", "_", name).strip("_")


def safe_filename(name: str) -> str:
    return _safe_name(name)


def get_stock_dir(user_id: int, code: str, name: str) -> Path:
    return get_user_data_root(user_id) / f"{code}_{_safe_name(name)}"


def ensure_stock_dirs(user_id: int, code: str, name: str) -> Path:
    base = get_stock_dir(user_id, code, name)
    for sub in TYPE_DIR.values():
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def get_type_dir(user_id: int, code: str, name: str, doc_type: str) -> Path:
    return get_stock_dir(user_id, code, name) / TYPE_DIR[doc_type]


def save_text_file(
    user_id: int, code: str, name: str, doc_type: str, filename: str,
    content: str, ext: str = ".txt",
) -> Path:
    target_dir = get_type_dir(user_id, code, name, doc_type)
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_file = _safe_name(filename)
    if not safe_file.endswith(ext):
        safe_file += ext
    path = target_dir / safe_file
    path.write_text(content, encoding="utf-8")
    return path

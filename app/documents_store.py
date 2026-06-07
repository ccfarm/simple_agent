"""documents 资料数据访问层（按用户隔离）。"""
from typing import Optional

from app.db import get_connection


def exists_by_url(user_id: int, stock_id: int, doc_type: str, url: str) -> bool:
    if not url:
        return False
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM documents WHERE user_id = ? AND stock_id = ? AND doc_type = ? "
            "AND url = ? LIMIT 1",
            (user_id, stock_id, doc_type, url),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def exists_by_title(user_id: int, stock_id: int, doc_type: str, title: str) -> bool:
    if not title:
        return False
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM documents WHERE user_id = ? AND stock_id = ? AND doc_type = ? "
            "AND title = ? LIMIT 1",
            (user_id, stock_id, doc_type, title),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def create_document(
    user_id: int,
    stock_id: int,
    doc_type: str,
    title: str,
    source: str = "",
    url: str = "",
    file_path: str = "",
    published_at: Optional[str] = None,
) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO documents "
            "(user_id, stock_id, doc_type, title, source, url, file_path, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, stock_id, doc_type, title, source, url, file_path, published_at),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_documents(user_id: int, stock_id: int, doc_type: Optional[str] = None) -> list:
    conn = get_connection()
    try:
        if doc_type:
            rows = conn.execute(
                "SELECT * FROM documents WHERE user_id = ? AND stock_id = ? AND doc_type = ? "
                "ORDER BY published_at DESC, id DESC",
                (user_id, stock_id, doc_type),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM documents WHERE user_id = ? AND stock_id = ? "
                "ORDER BY doc_type, published_at DESC, id DESC",
                (user_id, stock_id),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def count_documents(user_id: int, stock_id: int, doc_type: str) -> int:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM documents WHERE user_id = ? AND stock_id = ? AND doc_type = ?",
            (user_id, stock_id, doc_type),
        ).fetchone()
        return row["c"]
    finally:
        conn.close()


def get_document(user_id: int, doc_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ? AND user_id = ?",
            (doc_id, user_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

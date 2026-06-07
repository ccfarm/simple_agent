"""stocks 股票数据访问层（按用户隔离）。"""
from typing import Optional

from app.db import get_connection


def list_stocks(user_id: int) -> list:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM stocks WHERE user_id = ? ORDER BY created_at DESC, id DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_stock(user_id: int, stock_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM stocks WHERE id = ? AND user_id = ?",
            (stock_id, user_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_stock_by_code(user_id: int, code: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM stocks WHERE code = ? AND user_id = ?",
            (code, user_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_stock(user_id: int, code: str, name: str, market: str, note: str = "") -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO stocks (user_id, code, name, market, note) VALUES (?, ?, ?, ?, ?)",
            (user_id, code, name, market, note),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_stock(user_id: int, stock_id: int, name: str, market: str, note: str = "") -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE stocks SET name = ?, market = ?, note = ?, "
            "updated_at = datetime('now') WHERE id = ? AND user_id = ?",
            (name, market, note, stock_id, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_stock(user_id: int, stock_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM stocks WHERE id = ? AND user_id = ?",
            (stock_id, user_id),
        )
        conn.commit()
    finally:
        conn.close()

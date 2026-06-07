"""资料正文提取：PDF 下载+解析、网页正文抽取。"""
from pathlib import Path
from typing import Optional

import requests

TIMEOUT = 20.0
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": "https://www.eastmoney.com/",
}

NEWS_CONTENT_SELECTORS = (
    "div#ContentBody",
    "div.txtinfos",
    "div.txtinfo",
    "div.article-body",
    "div.newsContent",
)


def download_pdf(url: str, dest: Path) -> Optional[Path]:
    """下载 PDF 到指定路径，成功返回路径，失败返回 None。"""
    if not url:
        return None
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        if not resp.content:
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return dest
    except requests.RequestException:
        return None


def parse_pdf_text(path: Path) -> str:
    """用 PyMuPDF 解析 PDF 纯文本。"""
    try:
        import fitz
    except ImportError:
        return ""
    try:
        text_parts = []
        with fitz.open(path) as doc:
            for page in doc:
                text_parts.append(page.get_text())
        return "\n".join(text_parts).strip()
    except Exception:
        return ""


def parse_pdf_markdown(path: Path) -> str:
    """用 pymupdf4llm 将 PDF 解析为 Markdown（含标题层级与表格）。

    失败时回退到纯文本解析，便于后续 RAG chunk。
    """
    try:
        import pymupdf4llm
    except ImportError:
        return parse_pdf_text(path)
    try:
        md = pymupdf4llm.to_markdown(str(path))
        md = (md or "").strip()
        return md or parse_pdf_text(path)
    except Exception:
        return parse_pdf_text(path)


def extract_web_content(url: str) -> str:
    """抓取网页并提取正文主要文字。"""
    if not url:
        return ""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or resp.encoding
        html = resp.text
    except requests.RequestException:
        return ""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for selector in NEWS_CONTENT_SELECTORS:
        node = soup.select_one(selector)
        if node:
            text = node.get_text("\n", strip=True)
            if text:
                return text
    body = soup.body
    if body:
        return body.get_text("\n", strip=True)
    return ""

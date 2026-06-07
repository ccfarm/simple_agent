"""东方财富资料抓取器（单一数据源）。

统一抓取接口：每个抓取函数输入股票 code/market，输出标准化条目列表。
条目结构：{"title", "source", "url", "published_at", "content"}
"""
import re
from typing import Optional

import requests

TIMEOUT = 8.0
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/",
}


class FetchError(Exception):
    """抓取失败异常。"""


def _market_prefix(market: str) -> str:
    return {"SH": "1", "SZ": "0", "BJ": "0"}.get(market.upper(), "0")


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _get(url: str, params: Optional[dict] = None) -> requests.Response:
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp
    except requests.RequestException as exc:
        raise FetchError(f"请求东方财富失败：{exc.__class__.__name__}")


def fetch_reports(code: str, market: str, limit: int = 10) -> list:
    """研报：reportapi.eastmoney.com/report/list"""
    resp = _get(
        "https://reportapi.eastmoney.com/report/list",
        params={
            "industryCode": "*",
            "pageSize": limit,
            "pageNo": 1,
            "qType": "0",
            "code": code,
            "beginTime": "2020-01-01",
            "endTime": "2030-12-31",
        },
    )
    try:
        data = resp.json().get("data", []) or []
    except ValueError:
        raise FetchError("研报接口返回非 JSON 数据")
    items = []
    for d in data:
        info_code = d.get("infoCode", "")
        items.append({
            "title": d.get("title", "").strip(),
            "source": d.get("orgSName") or d.get("orgName") or "",
            "url": f"https://data.eastmoney.com/report/info/{info_code}.html" if info_code else "",
            "pdf_url": f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf" if info_code else "",
            "published_at": (d.get("publishDate") or "")[:10],
            "content": "",
        })
    return items


def fetch_announcements(code: str, market: str, limit: int = 10) -> list:
    """公告：np-anotice-stock.eastmoney.com/api/security/ann"""
    resp = _get(
        "https://np-anotice-stock.eastmoney.com/api/security/ann",
        params={
            "sr": -1,
            "page_size": limit,
            "page_index": 1,
            "ann_type": "A",
            "stock_list": code,
        },
    )
    try:
        payload = resp.json().get("data") or {}
        data = payload.get("list", []) or []
    except ValueError:
        raise FetchError("公告接口返回非 JSON 数据")
    items = []
    for d in data:
        art_code = d.get("art_code", "")
        pdf_url = f"https://pdf.dfcfw.com/pdf/H2_{art_code}_1.pdf" if art_code else ""
        page_url = (
            f"https://data.eastmoney.com/notices/detail/{code}/{art_code}.html"
            if art_code else ""
        )
        items.append({
            "title": (d.get("title") or "").strip(),
            "source": "东方财富-公告",
            "url": page_url,
            "pdf_url": pdf_url,
            "published_at": (d.get("notice_date") or "")[:10],
            "content": "",
        })
    return items


def fetch_news(code: str, market: str, limit: int = 10) -> list:
    """新闻：search-api-web.eastmoney.com 搜索接口"""
    import json

    param = {
        "uid": "",
        "keyword": code,
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "param": {
            "cmsArticleWebOld": {
                "searchScope": "default",
                "sort": "default",
                "pageIndex": 1,
                "pageSize": limit,
            }
        },
    }
    resp = _get(
        "https://search-api-web.eastmoney.com/search/jsonp",
        params={"cb": "", "param": json.dumps(param, ensure_ascii=False)},
    )
    text = resp.text.strip()
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1]
    try:
        result = json.loads(text).get("result", {}) or {}
        data = result.get("cmsArticleWebOld", []) or []
    except ValueError:
        raise FetchError("新闻接口返回非 JSON 数据")
    items = []
    for d in data:
        items.append({
            "title": _strip_html(d.get("title", "")),
            "source": d.get("mediaName", "") or "东方财富-新闻",
            "url": d.get("url", "") or "",
            "pdf_url": "",
            "published_at": (d.get("date") or "")[:10],
            "content": _strip_html(d.get("content", "")),
        })
    return items


FETCHERS = {
    "report": fetch_reports,
    "news": fetch_news,
    "announcement": fetch_announcements,
}


def fetch(doc_type: str, code: str, market: str, limit: int = 10) -> list:
    fetcher = FETCHERS.get(doc_type)
    if not fetcher:
        raise FetchError(f"未知资料类型：{doc_type}")
    return fetcher(code, market, limit)

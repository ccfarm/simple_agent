"""股票代码校验：离线格式校验 + 在线存在性校验。"""
import re

import requests

CODE_PATTERN = re.compile(r"^\d{6}$")

MARKET_PREFIXES = {
    "SH": ("600", "601", "603", "605", "688"),
    "SZ": ("000", "001", "002", "003", "300", "301"),
    "BJ": ("43", "83", "87", "88", "920"),
}

VALID_MARKETS = tuple(MARKET_PREFIXES.keys())


class ValidationError(Exception):
    """校验失败异常。"""


def validate_offline(code: str, market: str) -> None:
    """离线格式校验：6 位数字 + 代码段与市场一致性。"""
    if not CODE_PATTERN.match(code):
        raise ValidationError("股票代码必须为 6 位数字")
    if market not in VALID_MARKETS:
        raise ValidationError("市场必须为 SH / SZ / BJ 之一")
    prefixes = MARKET_PREFIXES[market]
    if not code.startswith(prefixes):
        raise ValidationError(
            f"代码 {code} 与市场 {market} 不匹配（{market} 应以 {'/'.join(prefixes)} 开头）"
        )


def _sina_symbol(code: str, market: str) -> str:
    return f"{market.lower()}{code}"


def fetch_stock_name(code: str, market: str, timeout: float = 3.0) -> str:
    """在线存在性校验：查到返回股票名称，否则抛出 ValidationError（严格模式）。"""
    symbol = _sina_symbol(code, market)
    url = f"https://hq.sinajs.cn/list={symbol}"
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"Referer": "https://finance.sina.com.cn"},
        )
        resp.encoding = "gbk"
        text = resp.text
    except requests.RequestException as exc:
        raise ValidationError(f"无法连接行情接口校验代码，请检查网络后重试（{exc.__class__.__name__}）")

    match = re.search(r'="([^"]*)"', text)
    if not match:
        raise ValidationError("行情接口返回异常，无法校验该代码")
    payload = match.group(1)
    if not payload:
        raise ValidationError(f"未找到代码 {code}（{market}）对应的股票，请确认代码是否正确")
    name = payload.split(",")[0].strip()
    if not name:
        raise ValidationError(f"未找到代码 {code}（{market}）对应的股票，请确认代码是否正确")
    return name


def validate_and_resolve_name(code: str, market: str) -> str:
    """完整校验：先离线再在线，返回自动解析出的股票名称。"""
    validate_offline(code, market)
    return fetch_stock_name(code, market)

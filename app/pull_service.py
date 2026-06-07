"""资料拉取服务：抓取 + 增量去重 + 下载PDF/抓正文 + 写文件 + 落库。"""
from app import content_extractor, documents_store, fetchers, index_service, storage


def _yaml_escape(value: str) -> str:
    """将字段值转为 YAML 安全的双引号字符串。"""
    return '"' + str(value or "").replace("\\", "\\\\").replace('"', '\\"') + '"'


def _build_markdown(item: dict, label: str, body: str, pdf_path: str = "") -> str:
    """组装 YAML front matter + Markdown 正文，便于 RAG chunk。"""
    front = [
        "---",
        f"title: {_yaml_escape(item.get('title', ''))}",
        f"type: {_yaml_escape(label)}",
        f"source: {_yaml_escape(item.get('source', ''))}",
        f"published_at: {_yaml_escape(item.get('published_at', ''))}",
        f"url: {_yaml_escape(item.get('url', ''))}",
    ]
    if pdf_path:
        front.append(f"pdf_path: {_yaml_escape(pdf_path)}")
    front.append("---")
    front.append("")
    front.append(f"# {item.get('title', '')}")
    front.append("")
    front.append(body or "（正文未抓取，可通过链接查看原文）")
    return "\n".join(front)


def _resolve_body(doc_type: str, item: dict, user_id: int, code: str, name: str, filename: str) -> tuple:
    """按类型获取正文内容与本地 PDF 路径。返回 (body, pdf_path_str)。"""
    pdf_url = item.get("pdf_url", "")
    if doc_type in ("report", "announcement") and pdf_url:
        pdf_dir = storage.get_type_dir(user_id, code, name, doc_type)
        pdf_dest = pdf_dir / (storage.safe_filename(filename) + ".pdf")
        saved = content_extractor.download_pdf(pdf_url, pdf_dest)
        if saved:
            body = content_extractor.parse_pdf_markdown(saved)
            return body, str(saved)
        return item.get("content", ""), ""

    if doc_type == "news":
        body = content_extractor.extract_web_content(item.get("url", ""))
        if not body:
            body = item.get("content", "")
        return body, ""

    return item.get("content", ""), ""


def pull_stock_documents(user_id: int, stock: dict, doc_types: list, limit: int = 10) -> dict:
    """按选定类型拉取资料，返回各类型 added/skipped 统计与错误信息。"""
    code = stock["code"]
    name = stock["name"]
    market = stock["market"]
    stock_id = stock["id"]

    storage.ensure_stock_dirs(user_id, code, name)
    result = {"added": {}, "skipped": {}, "errors": {}}

    for doc_type in doc_types:
        if doc_type not in storage.DOC_TYPES:
            continue
        label = storage.TYPE_LABEL[doc_type]
        added = 0
        skipped = 0
        try:
            items = fetchers.fetch(doc_type, code, market, limit)
        except fetchers.FetchError as exc:
            result["errors"][doc_type] = str(exc)
            continue

        for item in items:
            title = item.get("title", "")
            url = item.get("url", "")
            if not title:
                continue
            if (url and documents_store.exists_by_url(user_id, stock_id, doc_type, url)) or \
               documents_store.exists_by_title(user_id, stock_id, doc_type, title):
                skipped += 1
                continue
            filename = f"{item.get('published_at', '')}_{title}"
            body, pdf_path = _resolve_body(doc_type, item, user_id, code, name, filename)
            file_path = storage.save_text_file(
                user_id, code, name, doc_type, filename,
                _build_markdown(item, label, body, pdf_path), ext=".md"
            )
            documents_store.create_document(
                user_id=user_id,
                stock_id=stock_id,
                doc_type=doc_type,
                title=title,
                source=item.get("source", ""),
                url=url,
                file_path=str(file_path),
                published_at=item.get("published_at") or None,
            )
            added += 1

        result["added"][doc_type] = added
        result["skipped"][doc_type] = skipped

    total_added = sum(result["added"].values())
    if total_added > 0:
        result["index"] = index_service.sync_stock_index(user_id, stock)
    else:
        result["index"] = {"ok": True, "indexed": 0, "skipped": 0, "error": ""}

    return result

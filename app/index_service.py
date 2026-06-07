"""向量索引服务：基于 LlamaIndex 对资料 Markdown 切分、向量化并本地持久化。

索引在「拉取 / 重新拉取」资料落地后自动触发，仅对未入索引的新增资料增量入库；
同一索引对象供 AI 问答（M7）检索复用。
"""
import threading
from pathlib import Path
from typing import Optional

from app import documents_store, settings_store, storage

INDEX_DIR_NAME = ".index"

_embed_model = None
_embed_lock = threading.Lock()


class IndexError(Exception):
    """索引相关异常。"""


def embedding_configured() -> bool:
    """是否可用本地 embedding（使用内置默认模型，始终可用）。"""
    return True


def _build_embed_model():
    """进程内单例加载本地 embedding 模型。

    模型仅构造一次并复用，避免长驻服务进程反复初始化触发
    torch "Cannot copy out of meta tensor" 错误，同时提升性能。
    """
    global _embed_model
    if _embed_model is not None:
        return _embed_model
    with _embed_lock:
        if _embed_model is None:
            from llama_index.embeddings.huggingface import HuggingFaceEmbedding

            _embed_model = HuggingFaceEmbedding(
                model_name=settings_store.DEFAULT_EMBED_MODEL
            )
    return _embed_model


def get_index_dir(user_id: int, stock: dict) -> Path:
    return storage.get_stock_dir(user_id, stock["code"], stock["name"]) / INDEX_DIR_NAME


def _load_index(index_dir: Path, embed_model):
    """加载已持久化索引，不存在返回 None。"""
    from llama_index.core import StorageContext, load_index_from_storage

    if not (index_dir / "docstore.json").exists():
        return None
    storage_context = StorageContext.from_defaults(persist_dir=str(index_dir))
    return load_index_from_storage(storage_context, embed_model=embed_model)


def load_stock_index(user_id: int, stock: dict):
    """加载某只股票的向量索引对象，供 AI 问答复用；无索引返回 None。"""
    embed_model = _build_embed_model()
    return _load_index(get_index_dir(user_id, stock), embed_model)


def _indexed_doc_ids(index) -> set:
    """从索引 docstore 中提取已入库的 doc_id 集合，用于增量判重。"""
    ids = set()
    if index is None:
        return ids
    for node in index.docstore.docs.values():
        doc_id = node.metadata.get("doc_id")
        if doc_id is not None:
            ids.add(int(doc_id))
    return ids


def _read_markdown(path_str: str) -> str:
    if not path_str:
        return ""
    path = Path(path_str)
    if not path.exists() or path.suffix != ".md":
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _build_nodes(docs: list):
    """将 documents 记录读成 Markdown 文本并切分为节点。"""
    from llama_index.core import Document
    from llama_index.core.node_parser import MarkdownNodeParser

    li_docs = []
    for d in docs:
        text = _read_markdown(d.get("file_path", ""))
        if not text:
            continue
        li_docs.append(
            Document(
                text=text,
                metadata={
                    "doc_id": d["id"],
                    "stock_id": d["stock_id"],
                    "doc_type": d.get("doc_type", ""),
                    "title": d.get("title", ""),
                    "source": d.get("source", ""),
                    "url": d.get("url", ""),
                    "published_at": d.get("published_at", "") or "",
                    "file_path": d.get("file_path", ""),
                },
            )
        )
    if not li_docs:
        return []
    parser = MarkdownNodeParser()
    return parser.get_nodes_from_documents(li_docs)


def sync_stock_index(user_id: int, stock: dict) -> dict:
    """对单只股票增量建立/更新向量索引。

    返回 {"ok", "indexed"(本次新增文档数), "skipped", "error"}。
    """
    result = {"ok": False, "indexed": 0, "skipped": 0, "error": ""}
    if not embedding_configured():
        result["error"] = "未配置 embedding，跳过索引"
        return result

    try:
        from llama_index.core import VectorStoreIndex

        embed_model = _build_embed_model()
        index_dir = get_index_dir(user_id, stock)
        index = _load_index(index_dir, embed_model)
        indexed_ids = _indexed_doc_ids(index)

        all_docs = documents_store.list_documents(user_id, stock["id"])
        new_docs = [d for d in all_docs if d["id"] not in indexed_ids]
        result["skipped"] = len(all_docs) - len(new_docs)
        if not new_docs:
            result["ok"] = True
            return result

        nodes = _build_nodes(new_docs)
        if not nodes:
            result["ok"] = True
            return result

        if index is None:
            index = VectorStoreIndex(nodes, embed_model=embed_model)
        else:
            index.insert_nodes(nodes)

        index_dir.mkdir(parents=True, exist_ok=True)
        index.storage_context.persist(persist_dir=str(index_dir))
        result["ok"] = True
        result["indexed"] = len(new_docs)
        return result
    except IndexError as exc:
        result["error"] = str(exc)
        return result
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"索引失败：{exc}"
        return result


def search(user_id: int, stock: dict, query: str, top_k: int = 5) -> list:
    """语义检索，返回相关片段列表。

    每个元素：{"text", "score", "title", "doc_type", "source", "url", "file_path"}。
    """
    if not query.strip() or not embedding_configured():
        return []
    try:
        embed_model = _build_embed_model()
        index = _load_index(get_index_dir(user_id, stock), embed_model)
        if index is None:
            return []
        retriever = index.as_retriever(similarity_top_k=top_k)
        nodes = retriever.retrieve(query)
    except Exception:  # noqa: BLE001
        return []

    results = []
    for n in nodes:
        meta = n.node.metadata
        results.append({
            "text": n.node.get_content(),
            "score": round(float(n.score), 4) if n.score is not None else None,
            "title": meta.get("title", ""),
            "doc_type": meta.get("doc_type", ""),
            "source": meta.get("source", ""),
            "url": meta.get("url", ""),
            "file_path": meta.get("file_path", ""),
        })
    return results

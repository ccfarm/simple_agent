"""LLM 服务：基于 LlamaIndex 的 OpenAILike 封装 DeepSeek 对话模型。

供 AI 问答（M7）的 ChatEngine 使用；从 settings 读取 API Key，
未配置或调用失败时由上层捕获并返回明确错误。
"""
from app import index_service, settings_store

CAN_ANSWER_TAG = "[CAN_ANSWER]"
NO_ANSWER_TAG = "[NO_ANSWER]"

SYSTEM_PROMPT = (
    "你是一名严谨的 A 股投资研究助手，回答用户关于该股票的问题。\n"
    "判定与输出规则：\n"
    "1. 你的回答第一行必须是一个判定标记，且只能是 [CAN_ANSWER] 或 [NO_ANSWER] 之一，单独成行。\n"
    "2. 若提供的资料片段足以回答问题：第一行输出 [CAN_ANSWER]，"
    "随后用简体中文、仅依据资料片段作答，条理清晰，必要时分点，不要编造。\n"
    "3. 若资料片段与问题无关、或缺少回答所需的关键信息："
    "第一行输出 [NO_ANSWER]，且不要输出其他任何内容。\n"
    "4. 不要解释这两个标记的含义，不要把标记写在正文中间。"
)

FALLBACK_SYSTEM_PROMPT = (
    "你是一名 A 股投资研究助手。本次没有可用的本地资料，"
    "请基于你已有的通用知识，回答用户关于「{name}（{code}）」的问题。\n"
    "要求：\n"
    "- 用简体中文，条理清晰，必要时分点；\n"
    "- 只陈述你确信的通用、长期性常识（如公司主营业务、行业地位、历史沿革等）；\n"
    "- 不要编造具体的最新数字、财报、公告、股价等时效性内容；\n"
    "- 回答精简到100字以内;\n"
    "- 若问题涉及时效信息，提醒用户以官方公告与最新数据为准。"
)


class LLMError(Exception):
    """LLM 相关异常。"""


def llm_configured(user_id: int) -> bool:
    """是否已配置 DeepSeek API Key。"""
    return bool(settings_store.get_setting(user_id, settings_store.KEY_API_KEY).strip())


def build_llm(user_id: int):
    """构建 DeepSeek LLM 客户端，未配置 Key 抛 LLMError。"""
    api_key = settings_store.get_setting(user_id, settings_store.KEY_API_KEY).strip()
    if not api_key:
        raise LLMError("未配置 DeepSeek API Key，请前往设置页填写")

    from llama_index.llms.openai_like import OpenAILike

    return OpenAILike(
        model=settings_store.DEFAULT_LLM_MODEL,
        api_base=settings_store.DEFAULT_LLM_BASE_URL,
        api_key=api_key,
        is_chat_model=True,
        temperature=0.3,
        timeout=60,
    )


def _to_chat_messages(history: list):
    """将前端传入的对话历史转为 LlamaIndex ChatMessage 列表。

    history 元素形如 {"role": "user"|"assistant", "content": "..."}。
    """
    from llama_index.core.llms import ChatMessage, MessageRole

    role_map = {"user": MessageRole.USER, "assistant": MessageRole.ASSISTANT}
    messages = []
    for item in history or []:
        role = role_map.get((item.get("role") or "").strip())
        content = (item.get("content") or "").strip()
        if role and content:
            messages.append(ChatMessage(role=role, content=content))
    return messages


def _extract_sources(response) -> list:
    """从 ChatEngine 响应的 source_nodes 提取去重后的引用资料。"""
    sources = []
    seen = set()
    for sn in getattr(response, "source_nodes", []) or []:
        meta = sn.node.metadata
        doc_id = meta.get("doc_id")
        if doc_id in seen:
            continue
        seen.add(doc_id)
        sources.append({
            "doc_id": doc_id,
            "title": meta.get("title", ""),
            "doc_type": meta.get("doc_type", ""),
            "source": meta.get("source", ""),
            "url": meta.get("url", ""),
            "file_path": meta.get("file_path", ""),
            "score": round(float(sn.score), 4) if sn.score is not None else None,
        })
    return sources


def _parse_sentinel(text: str):
    """解析回答首行的判定标记，返回 (can_answer, body)。

    - 首行为 [NO_ANSWER] -> (False, "")
    - 首行为 [CAN_ANSWER] -> (True, 去掉首行后的正文)
    - 未按格式输出标记 -> 默认 (True, 原文)，避免误判为兜底
    """
    text = (text or "").strip()
    if text.startswith(NO_ANSWER_TAG):
        return False, ""
    if text.startswith(CAN_ANSWER_TAG):
        return True, text[len(CAN_ANSWER_TAG):].lstrip("\n").strip()
    return True, text


def _fallback_answer(user_id: int, stock: dict, question: str, history: list) -> dict:
    """阶段2 兜底：不带本地资料，基于大模型通用知识作答。"""
    result = {"ok": False, "answer": "", "sources": [], "error": "", "from_docs": False}
    try:
        from llama_index.core.llms import ChatMessage, MessageRole

        llm = build_llm(user_id)
        system_prompt = FALLBACK_SYSTEM_PROMPT.format(
            name=stock.get("name", ""), code=stock.get("code", "")
        )
        messages = [ChatMessage(role=MessageRole.SYSTEM, content=system_prompt)]
        messages.extend(_to_chat_messages(history))
        messages.append(ChatMessage(role=MessageRole.USER, content=question))
        response = llm.chat(messages)
        result["ok"] = True
        result["answer"] = str(response.message.content or "").strip()
        return result
    except LLMError as exc:
        result["error"] = str(exc)
        return result
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"AI 兜底问答失败：{exc}"
        return result


def answer(user_id: int, stock: dict, question: str, history: list, top_k: int = 5) -> dict:
    """两阶段问答：先严格 RAG，资料不足时用大模型通用知识兜底。

    返回 {"ok", "answer", "sources", "error", "from_docs"}。
    from_docs=True 表示回答基于本地资料，False 表示通用知识兜底。
    """
    result = {"ok": False, "answer": "", "sources": [], "error": "", "from_docs": True}
    question = (question or "").strip()
    if not question:
        result["error"] = "问题不能为空"
        return result
    if not llm_configured(user_id):
        result["error"] = "未配置 DeepSeek API Key，请前往设置页填写"
        return result

    try:
        index = index_service.load_stock_index(user_id, stock)
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"加载索引失败：{exc}"
        return result
    if index is None:
        result["error"] = "该股票暂无资料索引，请先在详情页拉取资料"
        return result

    try:
        from llama_index.core.chat_engine import CondensePlusContextChatEngine

        llm = build_llm(user_id)
        chat_history = _to_chat_messages(history)
        chat_engine = CondensePlusContextChatEngine.from_defaults(
            retriever=index.as_retriever(similarity_top_k=top_k),
            llm=llm,
            system_prompt=SYSTEM_PROMPT,
        )
        response = chat_engine.chat(question, chat_history=chat_history)
        can_answer, body = _parse_sentinel(str(response))
        if not can_answer:
            return _fallback_answer(user_id, stock, question, history)
        result["ok"] = True
        result["answer"] = body
        result["sources"] = _extract_sources(response)
        return result
    except LLMError as exc:
        result["error"] = str(exc)
        return result
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"AI 问答失败：{exc}"
        return result


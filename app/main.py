"""个人 A 股投资助手 MVP —— FastAPI 应用入口。"""
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app import (
    auth_store,
    documents_store,
    llm_service,
    pull_service,
    settings_store,
    stocks_store,
    storage,
)
from app.db import init_db
from app.stock_validator import (
    VALID_MARKETS,
    ValidationError,
    validate_and_resolve_name,
)

BASE_DIR = Path(__file__).resolve().parent
SECRET_KEY = os.environ.get("APP_SECRET_KEY", "dev-secret-change-me-in-production")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="个人 A 股投资助手", version="0.1.0", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=30 * 24 * 3600)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


class NotAuthenticated(Exception):
    """未登录异常，由全局处理器重定向到登录页。"""


def require_login(request: Request) -> dict:
    """认证依赖：返回当前登录用户，未登录抛 NotAuthenticated。"""
    user_id = request.session.get("user_id")
    if not user_id:
        raise NotAuthenticated()
    user = auth_store.get_user(user_id)
    if not user:
        request.session.clear()
        raise NotAuthenticated()
    return user


@app.exception_handler(NotAuthenticated)
async def _not_authenticated_handler(request: Request, exc: NotAuthenticated):
    return RedirectResponse(url="/login", status_code=303)


def _ctx(request: Request, user: dict, **extra) -> dict:
    base = {"request": request, "user": user}
    base.update(extra)
    return base


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return RedirectResponse(url="/stocks")


# ---------------------------------------------------------------------------
# 认证：注册 / 登录 / 退出
# ---------------------------------------------------------------------------
@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request) -> HTMLResponse:
    if request.session.get("user_id"):
        return RedirectResponse(url="/stocks")
    return templates.TemplateResponse(
        "register.html",
        {"request": request, "user": None, "title": "注册", "error": None},
    )


@app.post("/register")
def register(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    password2: str = Form(""),
) -> HTMLResponse:
    username = username.strip()
    password = password.strip()

    def fail(msg: str) -> HTMLResponse:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "user": None, "title": "注册",
             "error": msg, "username": username},
        )

    if not username or not password:
        return fail("用户名和密码不能为空")
    if len(username) < 2 or len(username) > 32:
        return fail("用户名长度需在 2-32 字符之间")
    if len(password) < 6:
        return fail("密码至少 6 位")
    if password != password2:
        return fail("两次输入的密码不一致")
    if auth_store.get_user_by_username(username):
        return fail("该用户名已被注册")

    user_id = auth_store.create_user(username, password)
    request.session["user_id"] = user_id
    return RedirectResponse(url="/stocks", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    if request.session.get("user_id"):
        return RedirectResponse(url="/stocks")
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "user": None, "title": "登录", "error": None},
    )


@app.post("/login")
def login(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
) -> HTMLResponse:
    username = username.strip()
    user = auth_store.authenticate(username, password.strip())
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "user": None, "title": "登录",
             "error": "用户名或密码错误", "username": username},
        )
    request.session["user_id"] = user["id"]
    return RedirectResponse(url="/stocks", status_code=303)


@app.post("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


# ---------------------------------------------------------------------------
# 股票列表 / 详情
# ---------------------------------------------------------------------------
@app.get("/stocks", response_class=HTMLResponse)
def stocks_page(request: Request, user: dict = Depends(require_login)) -> HTMLResponse:
    uid = user["id"]
    stocks = stocks_store.list_stocks(uid)
    doc_counts = {}
    for s in stocks:
        counts = {
            dt: documents_store.count_documents(uid, s["id"], dt)
            for dt in storage.DOC_TYPES
        }
        counts["total"] = sum(counts.values())
        doc_counts[s["id"]] = counts
    return templates.TemplateResponse(
        "stocks.html",
        _ctx(
            request, user,
            active="stocks",
            title="股票列表",
            stocks=stocks,
            markets=VALID_MARKETS,
            error=request.query_params.get("error"),
            pull_summary=request.query_params.get("pull"),
            doc_counts=doc_counts,
            doc_types=storage.DOC_TYPES,
            type_labels=storage.TYPE_LABEL,
        ),
    )


@app.post("/stocks")
def create_stock(
    user: dict = Depends(require_login),
    code: str = Form(""),
    market: str = Form(""),
    note: str = Form(""),
) -> RedirectResponse:
    uid = user["id"]
    code = code.strip()
    market = market.strip().upper()
    try:
        if stocks_store.get_stock_by_code(uid, code):
            raise ValidationError(f"代码 {code} 已存在于列表中")
        name = validate_and_resolve_name(code, market)
        stocks_store.create_stock(uid, code, name, market, note.strip())
    except ValidationError as exc:
        return RedirectResponse(url=f"/stocks?error={quote(str(exc))}", status_code=303)
    return RedirectResponse(url="/stocks", status_code=303)


@app.get("/stocks/{stock_id}", response_class=HTMLResponse)
def stock_detail_page(
    request: Request, stock_id: int, user: dict = Depends(require_login)
) -> HTMLResponse:
    uid = user["id"]
    stock = stocks_store.get_stock(uid, stock_id)
    if not stock:
        return RedirectResponse(url="/stocks")
    counts = {
        dt: documents_store.count_documents(uid, stock_id, dt) for dt in storage.DOC_TYPES
    }
    documents = {}
    for dt in storage.DOC_TYPES:
        docs = documents_store.list_documents(uid, stock_id, dt)
        for d in docs:
            d["file_exists"] = bool(d.get("file_path")) and Path(d["file_path"]).exists()
        documents[dt] = docs
    return templates.TemplateResponse(
        "stock_detail.html",
        _ctx(
            request, user,
            active="stocks",
            title="股票详情",
            stock=stock,
            markets=VALID_MARKETS,
            error=request.query_params.get("error"),
            doc_types=storage.DOC_TYPES,
            type_labels=storage.TYPE_LABEL,
            counts=counts,
            pull_summary=request.query_params.get("pull"),
            documents=documents,
        ),
    )


@app.post("/stocks/{stock_id}/pull")
def pull_documents(
    stock_id: int,
    user: dict = Depends(require_login),
    doc_types: list = Form(default=[]),
) -> RedirectResponse:
    uid = user["id"]
    stock = stocks_store.get_stock(uid, stock_id)
    if not stock:
        return RedirectResponse(url="/stocks", status_code=303)
    selected = [dt for dt in doc_types if dt in storage.DOC_TYPES]
    if not selected:
        return RedirectResponse(
            url=f"/stocks/{stock_id}?error={quote('请至少选择一种资料类型')}",
            status_code=303,
        )
    result = pull_service.pull_stock_documents(uid, stock, selected)
    parts = []
    for dt in selected:
        label = storage.TYPE_LABEL[dt]
        if dt in result["errors"]:
            parts.append(f"{label}失败({result['errors'][dt]})")
        else:
            parts.append(
                f"{label}新增{result['added'].get(dt, 0)}/跳过{result['skipped'].get(dt, 0)}"
            )
    summary = "；".join(parts)
    return RedirectResponse(
        url=f"/stocks/{stock_id}?pull={quote(summary)}", status_code=303
    )


@app.post("/stocks/{stock_id}/pull-all")
def pull_documents_all(
    stock_id: int, user: dict = Depends(require_login)
) -> RedirectResponse:
    uid = user["id"]
    stock = stocks_store.get_stock(uid, stock_id)
    if not stock:
        return RedirectResponse(url="/stocks", status_code=303)
    result = pull_service.pull_stock_documents(uid, stock, list(storage.DOC_TYPES))
    parts = [f"{stock['code']} {stock['name']}"]
    for dt in storage.DOC_TYPES:
        label = storage.TYPE_LABEL[dt]
        if dt in result["errors"]:
            parts.append(f"{label}失败({result['errors'][dt]})")
        else:
            parts.append(
                f"{label}新增{result['added'].get(dt, 0)}/跳过{result['skipped'].get(dt, 0)}"
            )
    summary = "；".join(parts)
    return RedirectResponse(url=f"/stocks?pull={quote(summary)}", status_code=303)


@app.post("/api/stocks/{stock_id}/pull")
def api_pull_documents(stock_id: int, user: dict = Depends(require_login)) -> dict:
    uid = user["id"]
    stock = stocks_store.get_stock(uid, stock_id)
    if not stock:
        return {"ok": False, "error": "股票不存在"}
    result = pull_service.pull_stock_documents(uid, stock, list(storage.DOC_TYPES))
    counts = {dt: documents_store.count_documents(uid, stock_id, dt) for dt in storage.DOC_TYPES}
    counts["total"] = sum(counts.values())
    types = []
    for dt in storage.DOC_TYPES:
        types.append({
            "type": dt,
            "label": storage.TYPE_LABEL[dt],
            "added": result["added"].get(dt, 0),
            "skipped": result["skipped"].get(dt, 0),
            "error": result["errors"].get(dt, ""),
        })
    return {
        "ok": True,
        "stock": {"code": stock["code"], "name": stock["name"]},
        "types": types,
        "counts": counts,
        "index": result.get("index", {"ok": True, "indexed": 0, "error": ""}),
    }


@app.get("/documents/{doc_id}/open")
def open_document(doc_id: int, user: dict = Depends(require_login)) -> FileResponse:
    uid = user["id"]
    doc = documents_store.get_document(uid, doc_id)
    if not doc or not doc.get("file_path"):
        return RedirectResponse(url="/stocks")
    path = Path(doc["file_path"]).resolve()
    data_root = storage.get_user_data_root(uid).resolve()
    if data_root not in path.parents or not path.exists():
        return RedirectResponse(url=f"/stocks/{doc['stock_id']}?error={quote('本地文件不存在或路径非法')}")
    return FileResponse(str(path), filename=path.name)


@app.get("/documents/{doc_id}/view", response_class=HTMLResponse)
def view_document(
    request: Request, doc_id: int, user: dict = Depends(require_login)
) -> HTMLResponse:
    uid = user["id"]
    doc = documents_store.get_document(uid, doc_id)
    if not doc:
        return RedirectResponse(url="/stocks")
    stock = stocks_store.get_stock(uid, doc["stock_id"])
    content = ""
    missing = False
    path_str = doc.get("file_path", "")
    if path_str:
        path = Path(path_str).resolve()
        data_root = storage.get_user_data_root(uid).resolve()
        if data_root in path.parents and path.suffix in (".md", ".txt") and path.exists():
            content = path.read_text(encoding="utf-8", errors="replace")
        else:
            missing = True
    else:
        missing = True
    return templates.TemplateResponse(
        "document_view.html",
        _ctx(
            request, user,
            active="stocks",
            title=doc.get("title", "资料详情"),
            doc=doc,
            stock=stock,
            type_labels=storage.TYPE_LABEL,
            content=content,
            missing=missing,
        ),
    )


@app.post("/stocks/{stock_id}/edit")
def edit_stock(
    stock_id: int,
    user: dict = Depends(require_login),
    market: str = Form(""),
    note: str = Form(""),
) -> RedirectResponse:
    uid = user["id"]
    stock = stocks_store.get_stock(uid, stock_id)
    if not stock:
        return RedirectResponse(url="/stocks", status_code=303)
    market = market.strip().upper()
    try:
        name = validate_and_resolve_name(stock["code"], market)
        stocks_store.update_stock(uid, stock_id, name, market, note.strip())
    except ValidationError as exc:
        return RedirectResponse(
            url=f"/stocks/{stock_id}?error={quote(str(exc))}", status_code=303
        )
    return RedirectResponse(url=f"/stocks/{stock_id}", status_code=303)


@app.post("/stocks/{stock_id}/delete")
def remove_stock(stock_id: int, user: dict = Depends(require_login)) -> RedirectResponse:
    stocks_store.delete_stock(user["id"], stock_id)
    return RedirectResponse(url="/stocks", status_code=303)


# ---------------------------------------------------------------------------
# AI 问答
# ---------------------------------------------------------------------------
@app.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request, user: dict = Depends(require_login)) -> HTMLResponse:
    uid = user["id"]
    stocks = stocks_store.list_stocks(uid)
    selected_id = request.query_params.get("stock_id")
    try:
        selected_id = int(selected_id) if selected_id else None
    except ValueError:
        selected_id = None
    return templates.TemplateResponse(
        "chat.html",
        _ctx(
            request, user,
            active="chat",
            title="AI 问答",
            stocks=stocks,
            selected_id=selected_id,
            llm_configured=bool(settings_store.get_setting(uid, settings_store.KEY_API_KEY).strip()),
        ),
    )


@app.post("/api/stocks/{stock_id}/ask")
async def api_ask(
    stock_id: int, request: Request, user: dict = Depends(require_login)
) -> dict:
    uid = user["id"]
    stock = stocks_store.get_stock(uid, stock_id)
    if not stock:
        return {"ok": False, "error": "股票不存在"}
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        payload = {}
    question = (payload.get("question") or "").strip()
    history = payload.get("history") or []
    if not question:
        return {"ok": False, "error": "问题不能为空"}
    result = llm_service.answer(uid, stock, question, history)
    return {
        "ok": result["ok"],
        "answer": result["answer"],
        "sources": result["sources"],
        "error": result["error"],
        "from_docs": result.get("from_docs", True),
    }


# ---------------------------------------------------------------------------
# 设置
# ---------------------------------------------------------------------------
@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, user: dict = Depends(require_login)) -> HTMLResponse:
    values = settings_store.get_all_settings(user["id"])
    return templates.TemplateResponse(
        "settings.html",
        _ctx(
            request, user,
            active="settings",
            title="设置",
            api_key=values[settings_store.KEY_API_KEY],
            saved=request.query_params.get("saved") == "1",
        ),
    )


@app.post("/settings")
def save_settings(
    user: dict = Depends(require_login),
    api_key: str = Form(""),
) -> RedirectResponse:
    settings_store.set_setting(user["id"], settings_store.KEY_API_KEY, api_key.strip())
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}

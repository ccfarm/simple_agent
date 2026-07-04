# 个人 A 股投研助手

一个面向个人 A 股投资者的投研助手：维护关注股票列表，自动拉取指定股票的**研报 / 新闻 / 公告**，并基于这些本地资料用 AI（DeepSeek）进行 RAG 问答分析。多用户隔离，可本机运行，也可部署到一台云主机随时访问。

![效果图2](./screenshots/截屏2026-07-04%2016.41.34.png)

![效果图1](./screenshots/截屏2026-07-04%2016.41.27.png)

## 功能特性

- **股票列表管理**：增删改查关注的 A 股股票，按代码自动校验并解析名称
- **资料自动拉取**：按股票拉取研报 / 新闻 / 公告，下载 PDF 并解析为 Markdown，增量去重落库
- **RAG 智能问答**：基于本地资料用 DeepSeek 做多轮问答，回答标注引用来源；资料不足时自动用大模型通用知识兜底并提示
- **本地向量检索**：使用本地 embedding 模型（`BAAI/bge-small-zh-v1.5`）离线向量化，无需额外 embedding API
- **多用户隔离**：用户名 + 密码注册登录，股票 / 资料 / 索引 / 设置（含各自的 API Key）按用户完全隔离

## 技术栈

| 模块 | 技术 |
|---|---|
| 后端 | Python + FastAPI |
| 前端 | Jinja2 模板 + Bootstrap |
| 数据存储 | SQLite |
| RAG 框架 | LlamaIndex |
| 向量化 | HuggingFace sentence-transformers（`BAAI/bge-small-zh-v1.5`） |
| 大模型 | DeepSeek API（经 LlamaIndex OpenAILike 封装） |
| 文档解析 | PyMuPDF / pymupdf4llm |
| 认证 | 用户名 + 密码（pbkdf2 加盐哈希）+ 签名 session cookie |

## 目录结构

```
simple_agent/
├── app/
│   ├── main.py             # FastAPI 入口、路由、认证
│   ├── db.py               # SQLite 连接与建表
│   ├── auth_store.py       # 用户认证数据层（注册/登录/密码哈希）
│   ├── stocks_store.py     # 股票数据层（按 user_id 隔离）
│   ├── documents_store.py  # 资料数据层（按 user_id 隔离）
│   ├── settings_store.py   # 用户配置（API Key 等）
│   ├── storage.py          # 资料文件存储（data/users/{user_id}/...）
│   ├── index_service.py    # 向量索引构建 / 加载 / 检索
│   ├── llm_service.py      # DeepSeek 问答（两阶段 RAG + 兜底）
│   ├── pull_service.py     # 资料拉取编排
│   ├── fetchers.py         # 各来源资料抓取
│   ├── content_extractor.py# PDF / 网页正文解析
│   ├── stock_validator.py  # 股票代码校验与名称解析
│   ├── templates/          # 页面模板
│   └── static/             # 静态资源
├── docs/                   # PRD / 计划 / Backlog
├── data/                   # 运行时生成：SQLite、资料、索引（已 gitignore）
└── requirements.txt
```

## 本地运行

环境要求：Python 3.11+

```bash
# 1. 创建并激活虚拟环境
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动服务（开发模式，自动重载）
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

打开浏览器访问 http://127.0.0.1:8000 ，先注册账号并登录，然后在「设置」页填写自己的 DeepSeek API Key，即可使用 AI 问答。

> 首次进行问答 / 拉取资料时会自动下载本地 embedding 模型（约 100MB），需要联网，之后离线缓存复用。

> **关于 torch**：`requirements.txt` 已锁定 **CPU 版 torch**（Linux 用 `+cpu` wheel），不会拉取庞大的 CUDA / NVIDIA 依赖。本项目 embedding 推理在 CPU 上运行，无需 GPU。

## 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `APP_SECRET_KEY` | session cookie 签名密钥。**生产环境务必设置为强随机值**，否则进程重启会导致所有登录态失效 | `dev-secret-change-me-in-production`（仅供开发） |

生成强随机密钥：

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## 云主机部署（轻量方式）

本项目无需 Docker，直接在一台云主机用 uvicorn 常驻运行。下面以阿里云 ECS（Ubuntu）+ systemd 守护为例。

> **内存要求**：项目依赖 torch + transformers，加载本地 embedding 模型时内存峰值约 1.5G。**建议实例至少 2G 内存**；2核2G 可用，但需按下方第 0 步加 swap 兜底，避免加载模型时 OOM。

### 0.（阿里云专用）安全组与 swap

```bash
# (1) 在阿里云控制台「安全组」放行入方向 TCP 8000 端口（若用 Nginx 反代则放行 80/443）

# (2) 2核2G 建议加 2G swap，防止加载模型时内存打满被 OOM kill
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab   # 开机自动挂载
free -h                                                       # 确认 swap 已生效
```

### 1. 准备代码与依赖

> **Python 版本要求：必须使用 Python 3.11**。本项目依赖 `sentence-transformers==2.7.0`，它要求 `Python <3.12`；同时 3.13 / 3.14 等过新版本缺少多个依赖的预编译 wheel。若系统自带的是 3.12+，请按下方额外安装 3.11，不要动系统自带版本。

```bash
# 安装 git
sudo apt update && sudo apt install -y git

# 若系统没有 Python 3.11，用 deadsnakes PPA 单独安装（不影响系统自带版本）
sudo apt install -y software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev
python3.11 --version          # 确认输出 Python 3.11.x

# 拉取代码（或用 scp 上传）
git clone <你的仓库地址> /opt/simple_agent
cd /opt/simple_agent

# 创建虚拟环境并安装依赖（务必用 python3.11）
python3.11 -m venv .venv
source .venv/bin/activate
python --version          # 确认是 3.11.x

# 注意两点：
# (1) /tmp 常是较小的内存盘(tmpfs)，pip 解压 torch 会撑爆，故把临时目录指到根盘
# (2) requirements.txt 已锁定 CPU 版 torch，不会拉取数 GB 的 CUDA 依赖
mkdir -p ~/pip_tmp
TMPDIR=~/pip_tmp pip install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

> **依赖体积**：CPU 版 torch 约 200MB，加上 transformers / llama-index 等，总安装体积约 1.5GB。若 `pip install` 报 `No space left on device`，多半是 `/tmp` 内存盘太小——确认已加 `TMPDIR=~/pip_tmp` 指向根盘。

> **embedding 模型下载**：首次问答 / 拉取资料时会从 HuggingFace 下载 `bge-small-zh-v1.5`（约 100MB），但阿里云访问 HuggingFace 常超时。解决办法是使用国内镜像 —— 在下方 systemd 配置中已通过 `HF_ENDPOINT=https://hf-mirror.com` 指定。若手动运行，先 `export HF_ENDPOINT=https://hf-mirror.com` 再启动。

### 2. 用 systemd 守护进程（开机自启 + 崩溃重启）

创建服务文件 `/etc/systemd/system/simple-agent.service`：

```ini
[Unit]
Description=Simple Agent (A-share research assistant)
After=network.target

[Service]
# 注意：以下路径需替换为你的实际项目路径与运行用户。
# 例如阿里云 ECS 默认普通用户为 ecs-assist-user，则项目通常在 /home/ecs-assist-user/simple_agent
User=ecs-assist-user
WorkingDirectory=/home/ecs-assist-user/simple_agent
Environment="APP_SECRET_KEY=在此填入你生成的强随机密钥"
Environment="HF_ENDPOINT=https://hf-mirror.com"
Environment="DEEPSEEK_API_KEY=在此填入你的 DeepSeek key"
ExecStart=/home/ecs-assist-user/simple_agent/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启用并启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now simple-agent
sudo systemctl status simple-agent      # 查看状态
sudo journalctl -u simple-agent -f      # 查看日志
```

此时服务监听 `0.0.0.0:8000`。如云主机安全组 / 防火墙放行该端口，即可通过 `http://<服务器IP>:8000` 访问。

### 3.（可选）Nginx 反向代理 + HTTPS

如需用 80/443 端口和域名访问，可加一层 Nginx 反代：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

证书可用 [certbot](https://certbot.eff.org/) 一键签发并自动续期。

### 4. 数据持久化与备份

所有运行时数据都在项目根目录的 `data/` 下：

- `data/app.sqlite3`：用户、股票、资料元数据、配置
- `data/users/{user_id}/stocks/...`：各用户的资料文件与向量索引

进程 / 主机重启数据不丢。备份只需打包该目录：

```bash
tar czf backup-$(date +%F).tar.gz data/
```

### 5. 更新部署

```bash
cd /opt/simple_agent
git pull
source .venv/bin/activate
pip install -r requirements.txt        # 依赖有变化时
sudo systemctl restart simple-agent
```

## 安全提示

- 生产环境必须设置 `APP_SECRET_KEY` 环境变量
- DeepSeek API Key 按用户存储在本机 SQLite 中，请妥善保护服务器与 `data/` 目录访问权限
- 建议通过 Nginx + HTTPS 对外暴露，不要直接公网裸跑 8000 端口

## 文档

更多设计细节见 `docs/`：

- `docs/prd.md`：产品需求文档
- `docs/plan.md`：里程碑计划
- `docs/backlog.md`：任务清单

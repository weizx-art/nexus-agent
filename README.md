# 综合业务智能 Agent 后端

> 综合业务智能 Agent 后端 Lite 版本，仅保留 智能对话+知识库 模块！

基于 FastAPI 构建的智能体后端，提供 **账号认证、文件管理、知识库（解析 → 切片 → 向量化 → 召回）** 全链路能力。

<p align="center">
  <img src="./docs/demo.gif" alt="Demo" width="100%">
</p>


## ✨ 核心特性

- **全量异步架构** — FastAPI + SQLAlchemy Async + Redis asyncio，高并发场景下保持稳定
- **智能对话** — LangGraph ReAct Agent，支持多轮对话与工具调用
- **流式输出** — SSE 实时推送，逐 token 展示 AI 回复
- **知识库引擎** — 文档上传 → 自动解析 → 智能切片 → 向量化索引 → 多策略召回
- **混合检索** — 语义检索 + 全文检索 + 关键词匹配，灵活组合
- **分布式锁** — Redis 锁保护并发操作，确保数据一致性

## 🏗️ 技术栈

| 层 | 技术 |
|---|---|
| Web 框架 | FastAPI + Uvicorn（全量 async） |
| ORM | SQLAlchemy 2.0（AsyncSession + asyncpg） |
| 数据库 | PostgreSQL 16 |
| 缓存 / 锁 | Redis 7（redis.asyncio） |
| 认证 | JWT（PyJWT，HS256） |
| 对象存储 | MinIO / S3（aioboto3） |
| 向量数据库 | Weaviate 1.39 |
| Embedding | HuggingFace `gte-multilingual-base` |
| 文档处理 | LangChain + jieba 分词 |
| 智能体 | LangGraph ReAct Agent |
| LLM | OpenAI 兼容 API（DeepSeek 等） |

## 📁 项目结构

```
nexus-agent/
├── main.py                  # FastAPI 入口
├── scripts/
│   └── seed.py              # 数据库初始化（重置 + 填充测试数据）
├── core/
│   ├── config.py            # 配置管理
│   └── database.py          # 数据库连接
├── cache/
│   └── redis.py             # Redis 客户端
├── models/                  # ORM 模型
├── schemas/                 # Pydantic 模型
├── services/                # 业务逻辑
│   ├── chat_service.py      # 对话服务
│   ├── chat_agent.py        # LangGraph Agent
│   ├── llm_service.py       # LLM 调用
│   ├── dataset_service.py   # 知识库管理
│   ├── indexing_service.py  # 索引流水线
│   ├── embedding_service.py # 向量化服务
│   └── vector_service.py    # 向量数据库
├── routers/                 # API 路由
│   ├── chat.py              # 对话接口
│   ├── dataset.py           # 知识库接口
│   └── ...
├── utils/                   # 工具函数
│   └── lock.py              # 分布式锁
├── docker-compose.yml       # 基础设施
└── pyproject.toml           # 依赖管理
```

## 🚀 快速开始

### 1. 启动基础设施

```bash
docker compose up -d
```

| 服务 | 端口 | 凭据 |
|------|------|------|
| PostgreSQL | 5432 | `root` / `123456` |
| MinIO | 9000 / 9001 | `admin` / `Admin123456` |
| Weaviate | 8080 | API Key: `sk-1234567890` |
| Redis | 6379 | 密码: `123456` |

> 首次启动后，需在 MinIO 控制台创建 `nexus-agent` bucket 并设为公开。

### 2. 安装依赖

```bash
# 安装 uv（如未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 安装项目依赖
uv sync
```

### 3. 配置并启动

```bash
cp .env.example .env   # 按需修改配置
uv run uvicorn main:app --reload
```

启动后访问：
- Swagger 文档：http://localhost:8000/docs
- ReDoc 文档：http://localhost:8000/redoc

### 4. 初始化测试数据（可选）

```bash
uv run python scripts/seed.py
```

该脚本会重置数据库并生成完整链路测试数据：
- 管理员账号：`admin` / `admin123`
- 50 个知识库、150 个文档、750 个片段及对应的向量数据

### 5. 配置 LLM

在 `.env` 中配置 LLM API：

```bash
LLM_API_KEY=your-api-key
LLM_API_BASE=https://api.deepseek.com  # 或其他 OpenAI 兼容 API
LLM_MODEL_NAME=deepseek-chat
```

## 📡 API 接口

### 对话

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/chat/conversations` | 获取会话列表 |
| POST | `/api/chat/conversations` | 创建会话 |
| GET | `/api/chat/conversations/:id` | 获取消息历史 |
| POST | `/api/chat/completions/stream` | SSE 流式对话 |
| PATCH | `/api/chat/conversations/:id` | 更新会话标题 |
| DELETE | `/api/chat/conversations/:id` | 删除会话 |

### 知识库

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/datasets` | 知识库列表 |
| POST | `/api/datasets` | 创建知识库 |
| GET | `/api/datasets/:id` | 知识库详情 |
| PATCH | `/api/datasets/:id` | 更新知识库 |
| DELETE | `/api/datasets/:id` | 删除知识库 |
| POST | `/api/datasets/:id/retrieval` | 召回测试 |

### 文档

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/datasets/:id/documents` | 上传文档 |
| GET | `/api/datasets/:id/documents` | 文档列表 |
| PATCH | `/api/datasets/:id/documents/:doc_id` | 更新文档 |
| DELETE | `/api/datasets/:id/documents/:doc_id` | 删除文档 |

## 🧠 核心架构

### 对话流程

```
用户输入
  ↓
LangGraph ReAct Agent
  ↓
┌─────────────────────────────────┐
│  1. 解析意图                     │
│  2. 选择知识库检索工具            │
│  3. 向量化查询 + 召回相关片段      │
│  4. 构建上下文 Prompt             │
│  5. LLM 生成回复（流式）          │
└─────────────────────────────────┘
  ↓
SSE 推送 → 前端实时展示
```

### 索引流水线

```
上传文件 (MinIO)
  ↓
后台异步执行 (BackgroundTasks):
  1. FileExtractor 解析 (pdf/docx/md/txt)
  2. RecursiveCharacterTextSplitter 切片
  3. jieba 提取关键词
  4. HuggingFace 向量化（Redis 缓存）
  5. 并行写入 Weaviate + PostgreSQL
  6. 构建关键词倒排表
```

### 检索策略

| 策略 | 说明 |
|------|------|
| `semantic` | Weaviate 向量近邻搜索 |
| `full_text` | jieba 关键词 + 倒排表匹配 |
| `hybrid` | 两者融合，按分数排序 |

## ⚙️ 配置参考

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `DATABASE_URI` | PostgreSQL 连接串 | `postgresql+asyncpg://root:123456@localhost:5432/nexus_agent` |
| `JWT_SECRET_KEY` | JWT 签名密钥 | **生产环境必须修改** |
| `MINIO_ENDPOINT_URL` | MinIO 地址 | `http://localhost:9000` |
| `WEAVIATE_URL` | Weaviate 地址 | `http://localhost:8080` |
| `REDIS_HOST` | Redis 地址 | `localhost` |
| `LLM_API_BASE` | LLM API 地址 | `https://api.deepseek.com` |
| `LLM_MODEL_NAME` | LLM 模型名 | `deepseek-chat` |
| `EMBEDDING_MODEL_NAME` | Embedding 模型 | `Alibaba-NLP/gte-multilingual-base` |

## 📝 开发

```bash
# 运行测试
uv run pytest tests/ -v

# 代码检查
uv run ruff check .

# 格式化
uv run ruff format .
```

## 🔗 相关项目

- [nexus-web](https://github.com/weizx-art/nexus-web) — 前端项目（Vue 3 + TypeScript）

## 📄 许可证

MIT

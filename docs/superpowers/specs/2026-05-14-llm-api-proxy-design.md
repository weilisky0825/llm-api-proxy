# LLM API Proxy 架构设计

**日期**: 2026-05-14

## Context

需要构建一个大模型 API 访问代理（中转站），接收客户端的 OpenAI 或 Anthropic 格式请求，转发到上游 API 提供商，并记录请求/响应对到数据库。当前需求保持最小范围：只做转发+日志，不做 Key 管理、计费、路由等高级功能。

## 技术栈

- **语言**: Python 3.11+
- **框架**: FastAPI + httpx + uvicorn
- **数据库**: SQLite (默认) + 可配置切换 PostgreSQL/MySQL
- **配置**: YAML 配置文件 + 环境变量覆盖
- **部署**: 本地直跑 + Docker

## 系统架构

```
客户端 ──→ [FastAPI 路由层] ──→ [日志中间件] ──→ [协议转换层] ──→ [上游转发]
                                     │
                               SQLite 异步队列写入
```

## 模块设计

### 1. 路由层 (`app/routes/`)

根据 URL 路径识别 API 格式并分发：

| 路径 | 格式 | 说明 |
|---|---|---|
| `/v1/chat/completions` | OpenAI | 聊天补全 |
| `/v1/completions` | OpenAI | 文本补全（映射到 chat） |
| `/v1/messages` | Anthropic | 消息补全 |
| `/v1/messages/count_tokens` | Anthropic | Token 估算 |
| `/v1/models` | 两者 | 模型列表 |

### 2. 协议转换 (`app/proxy/converter.py`)

**OpenAI → Anthropic**:
- `messages[].role: "system"` → 提取为顶级 `system` 字段
- `messages[].content` (文本) → `messages[].content` (文本)
- `messages[].content` (图片) → `content_blocks` (image_block)
- `stop` → `stop_sequences`

**Anthropic → OpenAI**:
- `system` (字符串) → `messages[{role: "system"}]`
- `content_blocks` → `messages[].content`
- `stop_sequences` → `stop`

**流式 SSE 转换**:
- OpenAI `data: {"choices":[...]}` ↔ Anthropic `event: content_block_delta / message_delta`
- 逐块转换，不缓冲完整响应

### 3. 上游转发 (`app/proxy/forwarder.py`)

- 基于 httpx.AsyncClient
- 自动附加认证头（OpenAI: `Authorization: Bearer`; Anthropic: `x-api-key` + `anthropic-version`）
- 支持同步请求和 SSE 流式请求

### 4. 日志系统 (`app/logging/`)

**中间件** (`middleware.py`):
- 请求进入时提取元数据，生成 UUID request_id
- 响应返回时记录状态码、响应体、耗时、token 用量
- 日志失败不影响主请求流

**存储接口** (`store.py`):
```python
class LogStore(Protocol):
    async def log_request(self, entry: LogEntry) -> None: ...
    async def update_response(self, request_id: str, response: LogResponse) -> None: ...
```

**SQLite 实现** (`sqlite.py`):
- asyncio.Queue 异步队列，不阻塞主请求
- aiosqlite 异步写入
- 自动建表建索引

**数据库切换**: LogStore 接口抽象，SQLite 默认实现，PostgreSQL/MySQL 通过 SQLAlchemy 提供。

### 5. 配置系统 (`app/config.py`)

- `config.yaml` 定义默认值
- `.env` 环境变量覆盖
- pydantic BaseModel 校验

**环境变量映射**:

| YAML 路径 | 环境变量 |
|---|---|
| `server.host` | `PROXY_HOST` |
| `server.port` | `PROXY_PORT` |
| `upstream.provider` | `UPSTREAM_PROVIDER` |
| `upstream.api_key` | `UPSTREAM_API_KEY` |
| `upstream.base_url` | `UPSTREAM_BASE_URL` |
| `upstream.timeout` | `UPSTREAM_TIMEOUT` |
| `database.driver` | `DATABASE_DRIVER` |
| `database.sqlite.path` | `DATABASE_SQLITE_PATH` |
| `database.postgresql.url` | `DATABASE_POSTGRESQL_URL` |
| `database.mysql.url` | `DATABASE_MYSQL_URL` |
| `logging.level` | `LOGGING_LEVEL` |

## 错误处理

| 场景 | 行为 |
|---|---|
| 上游返回错误 | 透传状态码和错误体给客户端 |
| 上游超时 | 返回 504 Gateway Timeout |
| 代理内部异常 | 包装为对应 API 格式的错误响应 |
| 日志写入失败 | 记录 warning，不影响主请求 |

## 数据库 Schema

```sql
CREATE TABLE api_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id      TEXT NOT NULL UNIQUE,
    timestamp       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    client_ip       TEXT,
    request_path    TEXT NOT NULL,
    request_model   TEXT,
    request_api     TEXT NOT NULL,
    request_body    TEXT,
    request_headers TEXT,
    status_code     INTEGER,
    response_body   TEXT,
    response_time_ms INTEGER,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    total_tokens    INTEGER
);

CREATE INDEX idx_timestamp ON api_logs(timestamp);
CREATE INDEX idx_request_api ON api_logs(request_api);
CREATE INDEX idx_request_model ON api_logs(request_model);
```

## 项目结构

```
llm-api-proxy/
├── app/
│   ├── main.py                 # FastAPI 入口
│   ├── config.py               # 配置加载
│   ├── routes/
│   │   ├── openai.py           # OpenAI 路由
│   │   └── anthropic.py        # Anthropic 路由
│   ├── proxy/
│   │   ├── forwarder.py        # 上游转发
│   │   └── converter.py        # 协议转换
│   ├── logging/
│   │   ├── middleware.py       # 日志中间件
│   │   ├── store.py            # LogStore 接口
│   │   └── sqlite.py           # SQLite 实现
│   └── models/
│       ├── openai.py           # OpenAI 模型
│       └── anthropic.py        # Anthropic 模型
├── config.yaml
├── .env.example
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

## 未来扩展

当前为最小可用版本。后续可能的功能（按优先级）：
1. API Key 管理（多租户）
2. 计费/用量统计
3. 模型路由（多 upstream 自动切换）
4. 请求/响应缓存

# LLM API Proxy

大模型 API 访问代理（中转站）。接收客户端的 OpenAI 或 Anthropic 格式请求，按模型名自动路由到多个上游提供商，支持用户管理与配额审计。

**注意**： 本项目基于Claude Code + qwen3.6-plus构建，功能并未完全验证，仅供个人参考使用。

## 功能

- **多 Provider 路由** — 配置多个上游提供商（OpenAI/Anthropic 格式），按模型名自动路由
- **路由规则** — 精确匹配 → 前缀匹配 → 默认 Provider → 首个 Provider
- **协议转换** — 客户端 OpenAI 格式 + 上游 Anthropic 格式（或反之），自动转换
- **流式响应** — 完整支持 SSE 流式输出
- **用户管理** — 每个用户独立 API Key（Bearer token），支持配额与速率限制
- **管理员认证** — 后台管理需登录，密码 bcrypt 加密，session cookie 管理
- **请求日志** — 自动记录所有请求/响应对，关联用户，支持 Markdown 渲染查看
- **管理后台** — 仪表盘、配置管理（Provider 卡片 + YAML 编辑器）、实时日志、日志查询、API 测试、健康检查、统计

## 快速开始

**<span style="color:red">说明</span>**： <span style="color:red">可在[windows目录](./windows/)下直接下载可执行文件使用。</span>

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 Provider

编辑 `config.yaml`，配置上游提供商：

```yaml
upstream:
  providers:
    - name: "dashscope"
      provider: "openai"           # openai | anthropic
      api_key: "sk-xxxx"
      base_url: "https://coding.dashscope.aliyuncs.com/v1"
      timeout: 120
      models: ["glm-5", "qwen3.6-plus", "qwen-"]  # 精确匹配 + 前缀匹配
      default: true                 # 无匹配时的默认 provider
    - name: "volces"
      provider: "openai"
      api_key: "your-volces-key"
      base_url: "https://ark.cn-beijing.volces.com/api/v3"
      timeout: 120
      models: ["glm-5.1"]
      default: false
```

也可以在管理后台 `/admin/config` 页面通过可视化界面编辑 Provider 并保存。

### 3. 启动

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

启动后自动创建：
- SQLite 数据库（`data/proxy.db`）
- 管理员账号：`admin` / `admin123`（登录 `/admin/login` 修改密码）

### 4. 创建用户并调用

```bash
# 1. 管理员登录获取 cookie
curl -c cookies.txt -X POST http://localhost:8000/api/admin/admin/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'

# 2. 创建用户（获取 API Key）
curl -b cookies.txt -X POST http://localhost:8000/api/admin/users \
  -H "Content-Type: application/json" \
  -d '{"name":"myuser","rate_limit":60,"daily_quota":10000}'
# 响应: {"ok":true,"api_key":"sk-xxxx..."}

# 3. 用户使用 API（OpenAI 格式）
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-xxxx..." \
  -d '{"model":"glm-5","messages":[{"role":"user","content":"Hello"}],"max_tokens":1000}'

# 4. 用户使用 API（Anthropic 格式，适用于 Claude Code 等工具）
curl http://localhost:8000/v1/messages \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -H "Authorization: Bearer sk-xxxx..." \
  -d '{"model":"glm-5","messages":[{"role":"user","content":"Hello"}],"max_tokens":1000}'
```

### 5. AI 开发工具接入

代理兼容 OpenAI 和 Anthropic 两种协议，所有主流 AI 开发工具均可无缝接入。

#### Claude Code（Anthropic 官方 CLI）

Claude Code 使用 Anthropic 协议。将代理地址设为 `ANTHROPIC_BASE_URL`：

```bash
# 方式一：环境变量
export ANTHROPIC_BASE_URL=http://localhost:8000
export ANTHROPIC_API_KEY=sk-xxxx...  # 管理后台创建的用户 Key

# 方式二：.claude/settings.json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:8000",
    "ANTHROPIC_API_KEY": "sk-xxxx..."
  }
}
```

Claude Code 会自动使用代理转发所有请求。模型名（如 `claude-sonnet-4-6`）会根据 Provider 的 `models` 配置路由。

**注意**：如果你的 Provider 不支持 Claude 模型，需要在 Provider 的 `models` 列表中配置映射（如将 `claude-sonnet-4-6` 映射到上游支持的模型名）。

#### OpenCode（OpenAI 协议 CLI）

OpenCode 使用 OpenAI 协议：

```bash
# 环境变量
export OPENAI_API_KEY=sk-xxxx...  # 管理后台创建的用户 Key
export OPENAI_BASE_URL=http://localhost:8000/v1

# 或在配置文件中
{
  "api_key": "sk-xxxx...",
  "base_url": "http://localhost:8000/v1"
}
```

#### Trae（IDE 内置 AI）

Trae 支持 OpenAI 兼容协议。在 Trae 设置中配置：

1. 打开 Trae 设置 → AI 模型 → 自定义模型
2. 选择 "OpenAI Compatible" 模式
3. 填写：
   - **API Key**: `sk-xxxx...`（管理后台创建的用户 Key）
   - **Base URL**: `http://localhost:8000/v1`
   - **Model Name**: 你的 Provider 支持的模型名（如 `glm-5`）

#### Cursor

Cursor 支持 OpenAI 兼容协议：

1. Settings → Cursor Settings → Models
2. 添加自定义 OpenAI 兼容模型：
   - **API Endpoint**: `http://localhost:8000/v1`
   - **API Key**: `sk-xxxx...`
   - **Model**: 你的 Provider 支持的模型名

#### Continue（IDE 插件）

在 Continue 的 `config.json` 中添加自定义模型：

```json
{
  "models": [
    {
      "title": "Proxy",
      "provider": "openai",
      "model": "glm-5",
      "apiBase": "http://localhost:8000",
      "apiKey": "sk-xxxx..."
    }
  ]
}
```

#### 统一配置规则

| 工具 | 协议 | API Key 字段 | Base URL 字段 |
|------|------|-------------|--------------|
| Claude Code | Anthropic | `ANTHROPIC_API_KEY` | `ANTHROPIC_BASE_URL` |
| OpenCode | OpenAI | `OPENAI_API_KEY` | `OPENAI_BASE_URL` |
| Trae | OpenAI | API Key | Base URL + `/v1` |
| Cursor | OpenAI | API Key | API Endpoint |
| Continue | OpenAI | `apiKey` | `apiBase` |

**Key 统一**：所有工具使用同一个 Key — 通过管理后台 `/admin/users` 创建的用户 API Key（`sk-` 开头）。

**注意**：模型路由依赖于你配置的 Provider。如果上游不支持 Claude 模型（如 `claude-sonnet-4-6`），请在支持的 Provider 上配置对应模型的映射。

## 管理后台

访问 `http://localhost:8000/admin/login` 登录管理后台。

| 页面 | 说明 |
|------|------|
| `/admin` | 仪表盘 — 请求统计、Token 用量、最近日志 |
| `/admin/config` | 配置管理 — Provider 卡片编辑 + 其他 YAML 配置 |
| `/admin/live` | 实时日志 — SSE 推送，实时查看请求流 |
| `/admin/logs` | 日志查询 — 分页、按模型/用户/状态/时间过滤，详情弹窗含 Markdown 渲染 |
| `/admin/test` | API 测试 — 直接在后台发送测试请求 |
| `/admin/health` | 健康检查 — 上游连通性、数据库状态 |
| `/admin/stats` | 统计分析 — 按日/小时/模型/用户分组 |
| `/admin/users` | 用户管理 — CRUD、重置 Key、重置配额、启用/禁用 |

## 模型路由规则

请求到达后，`ProviderRouter` 通过以下步骤选择上游 Provider：

1. **精确匹配** — 模型名完全等于某个 Provider 的 `models` 列表中的值
2. **前缀匹配** — 模型名以某个 `models` 列表中的值为前缀（如 `qwen-` 匹配 `qwen3.6-plus`）
3. **默认 Provider** — 选择 `default: true` 的 Provider
4. **兜底** — 返回列表中的第一个 Provider

请求格式（OpenAI/Anthropic）根据目标 Provider 的 `provider` 类型自动转换。

## API 端点

### OpenAI 兼容

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/chat/completions` | 聊天补全（支持流式） |
| POST | `/v1/completions` | 文本补全（映射到 chat completions） |
| GET | `/v1/models` | 获取上游可用模型列表 |

### Anthropic 兼容

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/messages` | 消息补全（支持流式） |
| POST | `/v1/messages/count_tokens` | 估算 token 数量 |
| GET | `/v1/models` | 获取上游可用模型列表 |

### 认证

所有 `/v1/*` 请求需在 Header 中携带用户 API Key：

```
Authorization: Bearer sk-xxxx...
```

无效 Key 返回 401，账户禁用返回 403，配额耗尽返回 429。

### 管理 API（需登录）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/admin/admin/login` | 管理员登录 |
| POST | `/api/admin/admin/logout` | 登出 |
| GET | `/api/admin/admin/me` | 当前登录信息 |
| POST | `/api/admin/admin/password` | 修改密码 |
| GET | `/api/admin/config` | 获取配置 |
| POST | `/api/admin/config` | 保存配置 + 热重载 |
| GET | `/api/admin/users` | 用户列表 |
| POST | `/api/admin/users` | 创建用户 |
| PUT | `/api/admin/users/{id}` | 更新用户 |
| DELETE | `/api/admin/users/{id}` | 删除用户 |
| POST | `/api/admin/users/{id}/reset-key` | 重置 API Key |
| POST | `/api/admin/users/{id}/reset-quota` | 重置今日配额 |
| GET | `/api/admin/logs` | 分页查询日志 |
| GET | `/api/admin/logs/live` | SSE 实时日志流 |
| GET | `/api/admin/stats` | 统计分析 |
| GET | `/api/admin/health` | 健康检查 |
| POST | `/api/admin/test` | 发送测试请求 |

## 配置项说明

### upstream.providers[]

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | string | `"default"` | Provider 名称（唯一标识） |
| `provider` | string | `"openai"` | 协议类型：`openai` 或 `anthropic` |
| `api_key` | string | `""` | 上游 API Key |
| `base_url` | string | `"https://api.openai.com"` | 上游 API 地址 |
| `timeout` | int | `120` | 超时时间（秒） |
| `models` | list[string] | `[]` | 支持的模型列表（用于路由匹配） |
| `default` | bool | `false` | 是否为默认 Provider |

### server / database / logging

| 配置项 | 类型 | 默认值 | 环境变量 | 说明 |
|--------|------|--------|----------|------|
| `server.host` | string | `0.0.0.0` | `PROXY_HOST` | 监听地址 |
| `server.port` | int | `8000` | `PROXY_PORT` | 监听端口 |
| `database.driver` | string | `sqlite` | `DATABASE_DRIVER` | 数据库驱动 |
| `database.sqlite.path` | string | `./data/proxy.db` | `DATABASE_SQLITE_PATH` | SQLite 路径 |
| `logging.level` | string | `INFO` | `LOGGING_LEVEL` | 日志级别 |

## 数据库 Schema

```sql
-- 请求日志
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
    total_tokens    INTEGER,
    user_id         INTEGER DEFAULT NULL,
    user_name       TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_user_id ON api_logs(user_id);

-- API 用户
CREATE TABLE users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    api_key         TEXT NOT NULL UNIQUE,
    enabled         INTEGER NOT NULL DEFAULT 1,
    rate_limit      INTEGER NOT NULL DEFAULT 60,
    daily_quota     INTEGER NOT NULL DEFAULT 10000,
    used_tokens     INTEGER NOT NULL DEFAULT 0,
    quota_date      TEXT NOT NULL DEFAULT '',
    request_count   INTEGER NOT NULL DEFAULT 0,
    request_date    TEXT NOT NULL DEFAULT '',
    last_request_at DATETIME,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 管理员账号
CREATE TABLE admin_users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE DEFAULT 'admin',
    password_hash TEXT NOT NULL,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 管理员会话
CREATE TABLE admin_sessions (
    session_id  TEXT PRIMARY KEY,
    username    TEXT NOT NULL,
    expires_at  DATETIME NOT NULL,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

## 项目结构

```
llm-api-proxy/
├── app/
│   ├── main.py                     # FastAPI 入口 + middleware 注册
│   ├── config.py                   # 配置加载 (yaml + env + ProviderConfig)
│   ├── routes/
│   │   ├── openai.py               # OpenAI 兼容路由 + 协议转换
│   │   └── anthropic.py            # Anthropic 兼容路由 + 协议转换
│   ├── proxy/
│   │   ├── forwarder.py            # ProviderRouter + ProviderClient
│   │   └── converter.py            # OpenAI ↔ Anthropic 协议转换
│   ├── auth/
│   │   ├── admin_middleware.py     # 管理员认证中间件 (session cookie)
│   │   ├── user_middleware.py      # 用户认证中间件 (Bearer token + 配额)
│   │   ├── password.py             # bcrypt 密码哈希
│   │   ├── session.py              # session 管理 (CRUD + 过期清理)
│   │   └── rate_limiter.py         # 滑动窗口速率限制
│   ├── models/
│   │   ├── openai.py               # OpenAI Pydantic 模型
│   │   ├── anthropic.py            # Anthropic Pydantic 模型
│   │   └── user.py                 # User 数据模型 + API Key 生成
│   ├── logging/
│   │   ├── middleware.py           # 日志记录中间件
│   │   ├── store.py                # LogStore 接口
│   │   └── sqlite.py               # SQLite 实现 + 表初始化
│   └── web/
│       ├── api.py                  # 管理后台 REST API
│       ├── routes.py               # 页面路由
│       └── templates/              # Jinja2 模板
│           ├── layout.html         # 统一布局
│           ├── login.html          # 登录页
│           ├── dashboard.html      # 仪表盘
│           ├── config.html         # 配置管理
│           ├── users.html          # 用户管理
│           ├── logs.html           # 日志查询
│           ├── live.html           # 实时日志
│           ├── test.html           # API 测试
│           ├── health.html         # 健康检查
│           └── stats.html          # 统计分析
├── config.yaml                     # 配置文件
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

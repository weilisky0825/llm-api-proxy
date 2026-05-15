# 用户管理与管理员认证 — 设计文档

## 概述

为 LLM API Proxy 添加管理员登录认证和用户管理功能，实现：
- 管理员登录后才能访问后台页面
- 用户 CRUD、API Key 管理、配额与速率限制
- 请求关联到用户，日志可按用户过滤
- 管理员可修改密码

## 架构总览

```
客户端请求 (Bearer <user-key>)
  → app/auth/middleware.py  (验证用户 key, 注入 user_id)
    → app/routes/openai.py  (记录 user_id)
    → app/routes/anthropic.py (记录 user_id)
      → 转发到上游 provider

管理员访问 /admin/*
  → app/auth/admin_middleware.py (验证 session)
    → 后台页面/API
```

## 一、数据库设计

### 1.1 `admin_users` 表（管理员账号）

```sql
CREATE TABLE admin_users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT NOT NULL UNIQUE DEFAULT 'admin',
    password_hash TEXT NOT NULL,  -- bcrypt hash
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 首次启动时插入默认 admin（密码: admin123）
-- INSERT OR IGNORE INTO admin_users (username, password_hash) VALUES ('admin', '<bcrypt_hash>');
```

### 1.2 `users` 表（API 用户）

```sql
CREATE TABLE users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    api_key         TEXT NOT NULL UNIQUE,  -- sk-xxxx 格式
    enabled         INTEGER NOT NULL DEFAULT 1,
    rate_limit      INTEGER NOT NULL DEFAULT 60,     -- 每分钟最大请求数
    daily_quota     INTEGER NOT NULL DEFAULT 10000,  -- 每日 token 配额 (0=不限)
    used_tokens     INTEGER NOT NULL DEFAULT 0,      -- 今日已用 token
    quota_date      TEXT NOT NULL DEFAULT '',         -- 配额日期 YYYY-MM-DD
    request_count   INTEGER NOT NULL DEFAULT 0,       -- 今日请求数
    request_date    TEXT NOT NULL DEFAULT '',          -- 计数日期 YYYY-MM-DD
    last_request_at DATETIME,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### 1.3 `api_logs` 表变更

```sql
ALTER TABLE api_logs ADD COLUMN user_id INTEGER DEFAULT NULL;
ALTER TABLE api_logs ADD COLUMN user_name TEXT DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_user_id ON api_logs(user_id);
```

### 1.4 `admin_sessions` 表（管理员登录态）

```sql
CREATE TABLE admin_sessions (
    session_id  TEXT PRIMARY KEY,
    username    TEXT NOT NULL,
    expires_at  DATETIME NOT NULL,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

## 二、认证模块

### 2.1 `app/auth/__init__.py` — 空

### 2.2 `app/auth/password.py` — 密码哈希工具

```python
import bcrypt

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()).decode()

def verify_password(password: str, hash_str: str) -> bool:
    return bcrypt.checkpw(password.encode(), hash_str.encode())
```

### 2.3 `app/auth/session.py` — Session 管理

- `create_session(username: str) -> str` — 生成 session_id 并存入 DB，返回 cookie 值
- `get_session(session_id: str) -> str | None` — 验证 session，返回 username 或 None（过期/无效）
- `delete_session(session_id: str)` — 登出
- `clean_expired_sessions()` — 清理过期 session（>24h）

### 2.4 `app/auth/admin_middleware.py` — 管理员认证中间件

- `AdminAuthMiddleware` — Starlette 中间件，拦截 `/admin/*` 请求
- 检查 cookie `admin_session`，无效则重定向到 `/admin/login`
- 排除路径：`/admin/login`, `/admin/api/admin/login`

### 2.5 `app/auth/user_middleware.py` — 用户 API Key 中间件

- `UserAuthMiddleware` — 拦截 `/v1/*` 请求
- 从 `Authorization: Bearer <key>` 提取 key
- 查询 `users` 表验证 key，检查 enabled 状态
- 检查速率限制（内存计数器，每分钟窗口）
- 检查每日配额
- 验证通过后在 request.state 注入 `user_id` 和 `user_name`
- 无效/禁用 key 返回 401

### 2.6 `app/auth/rate_limiter.py` — 速率限制器

- `RateLimiter` 类，内存字典 `{user_id: [timestamp1, timestamp2, ...]}`
- `is_allowed(user_id: int, limit: int) -> bool` — 滑动窗口，移除 >60s 的记录

## 三、日志模块变更

### 3.1 `app/logging/store.py` — LogEntry 新增字段

```python
@dataclass
class LogEntry:
    ...
    user_id: int | None = None
    user_name: str = ""
```

### 3.2 `app/logging/sqlite.py` — SQL 变更

- `CREATE_TABLE` 增加 `user_id`, `user_name` 列
- `INSERT_REQUEST` 增加对应参数
- `query_logs` 支持 `user_id` 过滤
- `get_stats` 支持按用户分组
- `get_dashboard` 增加按用户统计

## 四、路由模块变更

### 4.1 `app/routes/openai.py` & `app/routes/anthropic.py`

- `mw.on_request()` 调用中增加 `user_id` 和 `user_name`
- 从 `request.state.user_id` / `request.state.user_name` 获取

### 4.2 `app/main.py`

- 注册 `UserAuthMiddleware`（拦截 `/v1/*`）
- 注册 `AdminAuthMiddleware`（拦截 `/admin/*`，排除登录页）
- startup 中初始化默认管理员

## 五、Web API

### 5.1 管理员登录 API (`app/web/api.py`)

- `POST /admin/api/admin/login` — `{username, password}` → `{ok, token?}`
- `POST /admin/api/admin/logout` — 删除 session
- `POST /admin/api/admin/password` — `{old_password, new_password}` → `{ok}`
- `GET /admin/api/admin/me` — 返回当前登录用户名

### 5.2 用户管理 API

- `GET /admin/api/users` — 用户列表（含配额使用状态）
- `POST /admin/api/users` — 创建用户 `{name, rate_limit, daily_quota}` → `{ok, user, api_key}`
- `PUT /admin/api/users/{id}` — 更新用户 `{name, enabled, rate_limit, daily_quota}`
- `POST /admin/api/users/{id}/reset-key` — 重置 API Key → `{ok, new_key}`
- `DELETE /admin/api/users/{id}` — 删除用户
- `POST /admin/api/users/{id}/reset-quota` — 重置今日配额使用量

### 5.3 日志 API 变更

- `GET /admin/api/logs` 新增 `user_id` 过滤参数

## 六、前端页面

### 6.1 管理员登录页 (`app/web/templates/login.html`)

- 用户名 + 密码表单
- 提交到 `/admin/api/admin/login`
- 成功后 redirect `/admin`

### 6.2 导航栏变更 (`app/web/templates/layout.html`)

- 侧边栏新增 "👥 用户管理" → `/admin/users`
- 右上角显示当前管理员 + 退出按钮
- 未登录时显示 "登录" 链接

### 6.3 用户管理页 (`app/web/templates/users.html`)

- 用户列表表格（名称、API Key、状态、速率限制、配额使用进度条、操作）
- "添加用户" 按钮 → 弹窗表单
- 操作：启用/禁用、重置 Key（弹窗显示新 Key）、重置配额、删除
- 配额进度条：已用 / 总配额，超限变红

### 6.4 日志查询页变更 (`app/web/templates/logs.html`)

- 过滤器新增"用户"下拉框（从 `/admin/api/users` 加载）

### 6.5 统计页变更 (`app/web/templates/stats.html`)

- 新增按用户分组的统计图表

## 七、配置变更

### 7.1 `app/config.py`

- 新增 `AdminConfig` 模型（可选，如 session 超时时间）
- 或保持简单，全部走数据库

## 八、实现顺序

1. 数据库表创建 + 迁移（ALTER TABLE）
2. 密码哈希 + Session 管理
3. 管理员登录 API + 登录页
4. 管理员认证中间件
5. 用户管理 API
6. 用户 API Key 中间件
7. 日志关联 user_id
8. 用户管理前端页面
9. 日志查询按用户过滤
10. 管理员密码修改功能

## 九、安全考虑

- 密码使用 bcrypt 哈希
- Session cookie 设置 `httponly=True, samesite='lax'`
- API Key 生成使用 `secrets.token_urlsafe(32)` → `sk-{key}` 格式
- 管理员登录页不记录到日志
- 用户 Key 在列表 API 中仅显示掩码（`sk-0y****HFBI`），完整 Key 仅在创建/重置时返回

## 十、依赖

新增 Python 包：`bcrypt`

## 十一、实现后修正记录

### 已修复问题

1. **list_users 崩溃** — `aiosqlite.Row` 未设置导致 `dict(r)` 无法转换。修复：在 `app/web/api.py` 的 `list_users()` 中增加 `db.row_factory = aiosqlite.Row`。
2. **config save 崩溃** — `ProviderRouter.initialize()` 中 `client.event_hooks = []` 与 httpx 内部 setter 不兼容（期望 dict）。修复：移除该行。
3. **yaml_other 保存失败** — `yaml.safe_load` 可能返回非 dict 类型，且 `other.get("upstream")` 可能不是 dict。修复：增加 `isinstance` 类型检查。
4. **yaml_other 包含空 upstream** — GET config 时 `yaml_other` 不应包含空的 `upstream: {}`，避免保存时覆盖 providers。修复：仅在 `other_upstream` 非空时写入。
5. **管理员 CRUD 无存在性检查** — `PUT/DELETE/reset-key/reset-quota` 对不存在的用户也返回成功。修复：通过 `cursor.rowcount == 0` 检测并返回 404。
6. **配额重置未持久化** — 日期变更时配额重置仅在内存中生效。修复：将 `quota_date` 和 `request_date` 更新写入数据库。
7. **volces provider 401** — volces ark 是 OpenAI 兼容接口，但配置为 `provider: anthropic` 导致 auth header 格式错误。修复：改为 `provider: openai`，`base_url` 改为 `/api/v3`。
8. **日志缺少 provider 信息** — 日志不记录请求最终走哪个 provider 和上游 URL。修复：
   - `api_logs` 表增加 `provider_name`（TEXT）和 `upstream_url`（TEXT）列
   - `LogEntry` 增加对应字段
   - `LogMiddleware.on_request()` 从 request_data 中提取
   - `app/routes/openai.py` 和 `app/routes/anthropic.py` 在 `on_request()` 调用中传入 provider 名称和完整上游 URL

### 已知限制

- **流式请求不统计用户用量** — `send_stream()` 返回生成器，在响应完成前无法获取 token 用量，因此不调用 `update_user_usage()`。请求计数仍正常递增。
- **用户 API Key 的用途** — 用于客户端调用 `/v1/*` 代理接口时的身份验证。工具如 Claude Code 配置时：
  - `ANTHROPIC_BASE_URL` 设为代理地址
  - `ANTHROPIC_API_KEY` 设为通过管理后台创建的用户 Key
  - 代理会将请求按模型名路由到对应 Provider，并记录该用户的请求日志
- **模型路由依赖 Provider 配置** — Claude Code 默认使用 `claude-sonnet-4-6` 等 Claude 模型。如果上游 Provider 不支持这些模型，需要在 Provider 的 `models` 列表中配置映射，或将请求转发到支持 Claude 的 Provider。
- **volces provider 模型激活** — 火山方舟账号需要先在控制台激活对应模型才能使用。当前 volces 的 API Key 有可用模型包括 `doubao-seed-1-6-250615`、`glm-4-7-251222`、`kimi-k2-250905` 等（status=`?` 的为活跃模型）。需要在 `config.yaml` 中 volces 的 `models` 列表配置为已激活的模型名。

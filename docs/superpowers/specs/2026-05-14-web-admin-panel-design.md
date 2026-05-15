# Web Admin Panel 架构设计

**日期**: 2026-05-14

## Context

在 LLM API Proxy 后端基础上增加 Web 管理面板，用于可视化查看代理状态、实时日志、历史日志查询、API 测试、健康检查和请求统计。

## 技术栈

- **模板引擎**: Jinja2
- **前端交互**: HTMX (页面局部刷新、SSE、表单提交)
- **状态管理**: Alpine.js (客户端状态)
- **图表**: Chart.js (统计图表)
- **CSS**: CDN Tailwind
- **新增依赖**: `jinja2`, `python-multipart`

## 菜单结构

| 菜单项 | 路径 | 功能 |
|---|---|---|
| 首页概览 | `/admin` | 服务状态、今日统计、最近请求 |
| 系统配置 | `/admin/config` | 表单编辑配置，保存生效 |
| 实时日志 | `/admin/live` | SSE 推送，实时显示新请求 |
| 日志查询 | `/admin/logs` | 按条件筛选、分页、查看请求详情 |
| API 测试 | `/admin/test` | 构建请求测试上游连接 |
| 健康检查 | `/admin/health` | 上游/数据库连接状态 |
| 请求统计 | `/admin/stats` | 按时间/模型/路径的聚合图表 |

## 后端 API 设计

### HTML 页面路由

| 方法 | 路径 | 返回 |
|---|---|---|
| GET | `/admin` | 首页 HTML |
| GET | `/admin/config` | 配置页 HTML |
| GET | `/admin/live` | 实时日志页 HTML |
| GET | `/admin/logs` | 日志查询页 HTML |
| GET | `/admin/test` | API 测试页 HTML |
| GET | `/admin/health` | 健康检查页 HTML |
| GET | `/admin/stats` | 请求统计页 HTML |

### JSON API

| 方法 | 路径 | 功能 | 参数 |
|---|---|---|---|
| GET | `/api/admin/dashboard` | 首页概览数据 | — |
| GET | `/api/admin/config` | 获取当前配置 | — |
| POST | `/api/admin/config` | 保存配置 | body: JSON |
| GET | `/api/admin/logs` | 日志查询 | page, page_size, api_type, model, status, start, end |
| GET | `/api/admin/stats` | 统计数据 | group_by (hour/day/model/path) |
| GET | `/api/admin/health` | 健康检查 | — |
| POST | `/api/admin/test` | API 测试 | body: JSON (格式、模型、内容) |

### SSE 端点

| 方法 | 路径 | 功能 |
|---|---|---|
| GET | `/api/admin/logs/live` | 实时日志 SSE 流 |

## SQLiteStore 新增方法

```python
class SQLiteStore(LogStore):
    async def get_latest_logs(self, limit: int = 50) -> list[dict]: ...
    async def query_logs(self, filters: dict, page: int, page_size: int) -> tuple[list[dict], int]: ...
    async def get_stats(self, group_by: str) -> list[dict]: ...
    async def get_dashboard(self) -> dict: ...
```

### get_dashboard 返回

```json
{
  "uptime_seconds": 3600,
  "total_requests_today": 150,
  "success_rate_today": 0.97,
  "total_tokens_today": 50000,
  "avg_response_time_ms": 800,
  "recent_requests": [...]
}
```

### query_logs 返回

```json
{
  "logs": [...],
  "total": 500,
  "page": 1,
  "page_size": 20
}
```

## 前端设计

所有页面共享一个布局模板：

```
┌─────────────┬─────────────────────────────┐
│  侧边栏      │  内容区                       │
│             │                              │
│  LLM Proxy   │  页面标题                     │
│             │  ─────────                     │
│  📊 首页     │  HTMX 局部刷新的内容           │
│  ⚙️ 配置    │                              │
│  📡 实时     │                              │
│  🔍 日志    │                              │
│  🧪 测试    │                              │
│  💚 健康    │                              │
│  📈 统计    │                              │
└─────────────┴─────────────────────────────┘
```

每个 HTML 模板是一个完整页面，HTMX 用于局部更新（实时日志 SSE、日志查询分页、表单提交等），不用于 SPA 路由。

## 项目结构

```
app/
├── web/
│   ├── __init__.py
│   ├── routes.py              # HTML 页面路由
│   ├── api.py                 # JSON API 路由
│   └── templates/
│       ├── layout.html        - 主布局
│       ├── dashboard.html     - 首页概览
│       ├── config.html        - 系统配置
│       ├── live.html          - 实时日志
│       ├── logs.html          - 日志查询
│       ├── test.html          - API 测试
│       ├── health.html        - 健康检查
│       └── stats.html         - 请求统计
```

## 安全考虑

- 管理面板无认证保护，仅在局域网或开发环境使用
- 配置保存时覆盖 YAML 文件，不执行命令
- API 测试仅代理到已配置的上游，不开放任意 URL 访问

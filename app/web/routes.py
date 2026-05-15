from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from app.main import render_template

router = APIRouter(prefix="/admin")


@router.get("")
async def admin_index():
    return RedirectResponse(url="/admin/dashboard")


@router.get("/login")
async def login_page():
    return render_template("login", title="管理员登录", active="login")


@router.get("/dashboard")
async def dashboard():
    return render_template("dashboard", title="首页概览", active="dashboard")


@router.get("/users")
async def users_page():
    return render_template("users", title="用户管理", active="users")


@router.get("/config")
async def config_page():
    return render_template("config", title="系统配置", active="config")


@router.get("/live")
async def live_page():
    return render_template("live", title="实时日志", active="live")


@router.get("/logs")
async def logs_page():
    return render_template("logs", title="日志查询", active="logs")


@router.get("/test")
async def test_page():
    return render_template("test", title="API 测试", active="test")


@router.get("/health")
async def health_page():
    return render_template("health", title="健康检查", active="health")


@router.get("/stats")
async def stats_page():
    return render_template("stats", title="请求统计", active="stats", charts=True)
#!/usr/bin/env python3
"""Build single-file executable using PyInstaller."""
import subprocess
import sys
import shutil
import os


def build():
    proj_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(proj_dir)

    # Clean previous build artifacts (keep dist/ for multi-platform)
    for d in ["build", "__pycache__"]:
        path = os.path.join(proj_dir, d)
        if os.path.exists(path):
            shutil.rmtree(path)

    sep = os.pathsep
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "llm-api-proxy",
        "--add-data", f"config.yaml{sep}.",
        "--add-data", f"app/web/templates{sep}app/web/templates",
        "--hidden-import", "app",
        "--hidden-import", "app.main",
        "--hidden-import", "app.config",
        "--hidden-import", "app.routes.openai",
        "--hidden-import", "app.routes.anthropic",
        "--hidden-import", "app.proxy.forwarder",
        "--hidden-import", "app.proxy.converter",
        "--hidden-import", "app.auth.admin_middleware",
        "--hidden-import", "app.auth.user_middleware",
        "--hidden-import", "app.auth.password",
        "--hidden-import", "app.auth.session",
        "--hidden-import", "app.auth.rate_limiter",
        "--hidden-import", "app.logging.middleware",
        "--hidden-import", "app.logging.sqlite",
        "--hidden-import", "app.logging.store",
        "--hidden-import", "app.web.routes",
        "--hidden-import", "app.web.api",
        "--hidden-import", "app.models.openai",
        "--hidden-import", "app.models.anthropic",
        "--hidden-import", "app.models.user",
        "--hidden-import", "uvicorn",
        "--hidden-import", "aiosqlite",
        "--hidden-import", "bcrypt",
        "--hidden-import", "jinja2",
        "--hidden-import", "yaml",
        "--collect-all", "jinja2",
        "run.py",
    ]
    subprocess.run(cmd, check=True)
    ext = ".exe" if sys.platform == "win32" else ""
    print(f"\nBuild complete: dist/llm-api-proxy{ext}")


if __name__ == "__main__":
    build()

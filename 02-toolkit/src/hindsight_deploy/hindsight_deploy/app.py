"""Hindsight Deploy Application Core.

Core application logic for the Hindsight External Deployment toolkit.
Handles configuration loading, environment validation, and deployment orchestration.
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

import typer
from pydantic import BaseModel, Field

# Resolve deployment assets relative to the source checkout.
# Compose files live under 01-deploy/compose/{basic,production}/.
DEPLOY_ROOT = Path(__file__).resolve().parents[4]
COMPOSE_ROOT = DEPLOY_ROOT / "01-deploy" / "compose"


class Settings(BaseModel):
    """应用配置设置。"""
    # 部署模式
    mode: str = Field(default="basic", description="部署模式: basic 或 production")

    # 路径配置
    home_dir: Path = Field(default_factory=lambda: Path.home() / ".hindsight")
    compose_dir: Path = Field(default_factory=lambda: Path.home() / ".hindsight" / "compose")
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".hindsight" / "data")
    backup_dir: Path = Field(default_factory=lambda: Path.home() / ".hindsight" / "backups")
    state_dir: Path = Field(default_factory=lambda: Path.home() / ".hindsight" / "state")

    # Docker 配置
    project_name: str = Field(default="hindsight")
    compose_command: str = Field(default="docker compose")

    # 服务端口
    api_port: int = Field(default=8888, description="Hindsight API 端口")
    control_port: int = Field(default=9999, description="Control Plane 端口")
    postgres_port: int = Field(default=5432, description="PostgreSQL 端口")

    # API 连接（local_external 模式）
    api_url: str = Field(default="http://localhost:8888", description="Hindsight API 地址")
    timeout: int = Field(default=120, description="API 请求超时（秒）")

    # LLM 配置
    llm_provider: str = Field(default="openai", description="LLM 提供商")
    llm_model: str = Field(default="gpt-4o-mini", description="LLM 模型")
    llm_base_url: Optional[str] = Field(default=None, description="LLM Base URL")

    # 安全
    env_file_mode: str = Field(default="0600", description=".env 文件权限")

    class Config:
        """Pydantic 配置。"""
        # 允许字段忽略（来自环境变量或 CLI）
        extra = "ignore"


# 全 settings 实例
settings = Settings()


def get_compose_file(mode: str) -> Path:
    """Resolve the Compose file relative to the installed source checkout."""
    if mode == "basic":
        return COMPOSE_ROOT / "basic" / "hindsight.yaml"
    elif mode == "production":
        return COMPOSE_ROOT / "production" / "hindsight.yaml"
    else:
        raise ValueError(f"未知部署模式: {mode}")


def get_project_name(mode: str) -> str:
    """返回该模式对应的 Compose project name。

    必须与 compose 文件里的 `name:` 一致，否则会拉起第二套栈（卷名不同、
    数据不互通）。basic 用 `hindsight`（与既有部署一致），production 用
    `hindsight-prod`（端口与容器名都错开，可与 basic 共存）。
    """
    return "hindsight" if mode == "basic" else "hindsight-prod"


def validate_compose_file(compose_path: Path) -> bool:
    """验证 Compose YAML 文件语法。"""
    import yaml
    try:
        with open(compose_path, "r") as f:
            yaml.safe_load(f)
        return True
    except Exception as e:
        typer.echo(f"❌ Compose 文件语法错误: {e}")
        return False


def init_directories() -> None:
    """确保必要的目录存在。"""
    for d in [
        settings.home_dir,
        settings.compose_dir,
        settings.data_dir,
        settings.backup_dir,
        settings.state_dir,
    ]:
        d.mkdir(parents=True, exist_ok=True)


def load_env_file(env_path: Path) -> dict:
    """加载 .env 文件并返回键值对。"""
    env = {}
    if not env_path.exists():
        return env
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


def save_env_file(env_path: Path, env: dict) -> None:
    """原子保存 .env 文件。"""
    env_path.write_text("")
    env_path.write_text("\n".join(f"{k}={v}" for k, v in sorted(env.items())) + "\n")
    # 设置权限
    try:
        os.chmod(str(env_path), int(settings.env_file_mode.replace("0", "")))
    except (ValueError, OSError):
        pass


app = typer.Typer(help="Hindsight External Deployment & Operations Toolkit")


@app.callback()
def callback(
    mode: str = typer.Option("basic", help="部署模式: basic 或 production"),
) -> None:
    """应用回调，在每个命令前运行。"""
    global settings
    settings.mode = mode
    if mode == "production":
        settings.api_url = "http://127.0.0.1:8889"
        settings.api_port = 8889
        settings.control_port = 9998
    else:
        settings.api_url = "http://127.0.0.1:8888"
        settings.api_port = 8888
        settings.control_port = 9999
    init_directories()


# 当作 CLI 运行时执行
if __name__ == "__main__":
    app()

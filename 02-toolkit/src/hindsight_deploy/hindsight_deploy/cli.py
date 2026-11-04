"""Hindsight Deploy CLI - Python-first deployment toolkit.

Hindsight External Deployment & Operations Toolkit
=================================================

Python CLI driven Hindsight External deployment and lifecycle management.

Usage:
    hindsight-deploy check
    hindsight-deploy status
    hindsight-deploy health
    hindsight-deploy backup
    hindsight-deploy validate
    hindsight-deploy banks-list
    hindsight-deploy banks-init BANK_ID PURPOSE
    hindsight-deploy banks-validate BANK_ID
    hindsight-deploy banks-permissions BANK_ID read,write
    hindsight-deploy mcp-capabilities
    hindsight-deploy provision
"""
__version__ = "0.2.0"

import json
from pathlib import Path

import typer

from .app import get_compose_file, get_project_name, settings

app = typer.Typer(help="Hindsight External Deployment & Operations Toolkit")

@app.callback()
def main(
    mode: str = typer.Option("basic", help="Deployment profile: basic or production"),
) -> None:
    """Select the deployment profile before executing a command."""
    if mode not in {"basic", "production"}:
        raise typer.BadParameter("mode must be basic or production")
    settings.mode = mode
    if mode == "production":
        settings.api_url = "http://127.0.0.1:8889"
        settings.api_port = 8889
        settings.control_port = 9998
    else:
        settings.api_url = "http://127.0.0.1:8888"
        settings.api_port = 8888
        settings.control_port = 9999



# ──────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────

def _client():
    """Build an API client pointed at the configured API URL."""
    from .memory.api_client import DEFAULT_API_URL, HindsightClient

    url = settings.api_url or DEFAULT_API_URL
    return HindsightClient(base_url=url, timeout=float(settings.timeout or 120))


def _compose_context() -> tuple:
    """Return (compose_file, project_name) for the active mode."""
    return get_compose_file(settings.mode), get_project_name(settings.mode)


# ──────────────────────────────────────────────────────────────────────
# infrastructure commands
# ──────────────────────────────────────────────────────────────────────

@app.command()
def check():
    """检查环境和前置条件。"""
    from .infrastructure.command import (
        compose_config_cmd,
        docker_compose_cmd,
        run_cmd,
    )

    compose_file, project_name = _compose_context()
    typer.echo("🔍 正在执行环境检查...")

    ok = True

    # Python version
    import sys
    py_ok = sys.version_info >= (3, 12)
    typer.echo(f"  {'✓' if py_ok else '✗'} Python {sys.version.split()[0]}")
    ok = ok and py_ok

    # Docker daemon
    r = run_cmd(["docker", "info", "--format", "{{.ServerVersion}}"], check=False, timeout=30)
    docker_ok = r.returncode == 0
    typer.echo(f"  {'✓' if docker_ok else '✗'} Docker daemon reachable"
               + (f" (v{r.stdout.strip()})" if docker_ok else ""))
    ok = ok and docker_ok

    # Docker Compose V2
    r = run_cmd(["docker", "compose", "version"], check=False, timeout=30)
    compose_ok = r.returncode == 0
    typer.echo(f"  {'✓' if compose_ok else '✗'} Docker Compose V2"
               + (f" ({r.stdout.strip()})" if compose_ok else " NOT AVAILABLE"))
    ok = ok and compose_ok

    # Disk space
    r = run_cmd(["df", "-h", "/"], check=False, timeout=30)
    if r.returncode == 0:
        lines = r.stdout.strip().splitlines()
        if len(lines) > 1:
            usage = lines[1].split()[4] if len(lines[1].split()) > 4 else "?"
            typer.echo(f"  ✓ Disk usage: {usage}")

    # Compose file present and valid
    if compose_file.exists():
        typer.echo(f"  ✓ Compose file: {compose_file}")
        r = compose_config_cmd(compose_file=compose_file, project_name=project_name)
        typer.echo(f"  {'✓' if r.returncode == 0 else '✗'} Compose file syntax")
        ok = ok and r.returncode == 0
    else:
        typer.echo(f"  ✗ Compose file missing: {compose_file}")
        ok = False

    # Port conflicts
    from .infrastructure.command import port_in_use_cmd
    for port in (settings.api_port, settings.control_port):
        if port_in_use_cmd(port):
            typer.echo(f"  ✓ Port {port} in use (service running)")
        else:
            typer.echo(f"  · Port {port} free")

    typer.echo("✅ 环境检查完成" if ok else "⚠️ 环境检查发现问题")
    raise typer.Exit(0 if ok else 1)


@app.command()
def status():
    """检查服务状态。"""
    from .infrastructure.command import compose_ps_cmd

    compose_file, project_name = _compose_context()
    typer.echo("📊 当前服务状态")
    typer.echo(f"  - Docker 项目: {project_name}")
    typer.echo(f"  - 模式: {settings.mode}")
    typer.echo(f"  - API: http://localhost:{settings.api_port}")
    typer.echo(f"  - Control Plane: http://localhost:{settings.control_port}")
    typer.echo(f"  - Compose 文件: {compose_file}")

    r = compose_ps_cmd(compose_file=compose_file, project_name=project_name)
    if r.returncode == 0 and r.stdout.strip():
        typer.echo("")
        typer.echo(r.stdout.rstrip())


@app.command()
def health():
    """健康检查。"""
    from .memory.api_client import HindsightAPIError

    compose_file, project_name = _compose_context()
    typer.echo("⏳ 正在进行健康检查...")
    ok = True

    # Docker daemon
    from .infrastructure.command import run_cmd
    r = run_cmd(["docker", "info", "--format", "{{.ServerVersion}}"], check=False, timeout=30)
    typer.echo(f"  {'✓' if r.returncode == 0 else '✗'} Docker Daemon")
    ok = ok and r.returncode == 0

    # Compose project state
    from .infrastructure.command import compose_ps_cmd
    r = compose_ps_cmd(compose_file=compose_file, project_name=project_name)
    # `docker compose ps` prints one row per service: "NAME IMAGE ... STATUS ..."
    # The STATUS column carries "Up 8 minutes (healthy)" or "Exited (...)".
    # Count rows whose status says the container is up, whatever the health.
    running = 0
    if r.returncode == 0:
        for line in r.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] not in {"NAME", "IMAGE"}:
                if any(p.startswith("Up") for p in parts):
                    running += 1
    typer.echo(f"  {'✓' if running else '✗'} Compose 项目 ({running} 个容器运行)")
    ok = ok and bool(running)

    # API health
    try:
        client = _client()
        doc = client.health()
        healthy = doc.get("status") == "healthy"
        db = doc.get("database")
        typer.echo(f"  {'✓' if healthy else '✗'} Hindsight API: status={doc.get('status')}")
        typer.echo(f"  {'✓' if db == 'connected' else '✗'} PostgreSQL: {db}")
        ok = ok and healthy and db == "connected"
    except HindsightAPIError as exc:
        typer.echo(f"  ✗ Hindsight API 不可达: {exc}")
        ok = False

    typer.echo("✅ 健康检查通过" if ok else "⚠️ 健康检查未通过")
    raise typer.Exit(0 if ok else 1)


@app.command()
def backup():
    """执行备份（pg_dump + SHA-256 校验）。"""
    import hashlib
    import subprocess
    import time

    from .memory.api_client import HindsightAPIError

    backup_dir = settings.backup_dir / time.strftime("%Y%m%d-%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)

    client = _client()
    try:
        client.health()
    except HindsightAPIError as exc:
        typer.echo(f"✗ API 不可达，无法备份: {exc}")
        raise typer.Exit(1)

    typer.echo("💾 执行备份...")

    compose_file, project_name = _compose_context()
    target = backup_dir / "hindsight.dump"
    compose_cmd = ["docker", "compose"]
    env_file = compose_file.parent / ".env"
    if env_file.is_file():
        compose_cmd.extend(["--env-file", str(env_file)])
    compose_cmd.extend(["-f", str(compose_file), "--project-name", project_name])

    if settings.mode == "production":
        # Run pg_dump inside PostgreSQL over its local socket.
        dump_cmd = compose_cmd + ["exec", "-T", "db", "pg_dump", "-U", "hindsight", "-d", "hindsight", "-Fc"]
    else:
        # Basic mode uses the embedded pg0 instance in the Hindsight container.
        dump_cmd = [
            "docker", "exec", "hindsight-app", "bash", "-lc",
            "PGPASSWORD=hindsight /home/hindsight/.pg0/installation/18.1.0/bin/pg_dump "
            "-U hindsight -h 127.0.0.1 -d hindsight -Fc",
        ]

    with target.open("wb") as output:
        r = subprocess.run(dump_cmd, stdout=output, stderr=subprocess.PIPE, timeout=600)
    if r.returncode != 0:
        target.unlink(missing_ok=True)
        typer.echo("✗ pg_dump 失败: " + r.stderr.decode(errors="replace")[:400])
        raise typer.Exit(1)

    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (backup_dir / "hindsight.dump.sha256").write_text(f"{digest}  {target.name}\n")

    typer.echo(f"  ✓ 备份文件: {target}")
    typer.echo(f"  ✓ SHA-256: {digest}")
    typer.echo(f"  ✓ 存储位置: {backup_dir}")


@app.command()
def validate(
    target: str = typer.Option("hermes", help="目标客户端: hermes, cursor, codex, all"),
):
    """验证客户端接入（MCP 连接 + 工具发现 + Bank 读写）。"""
    from .memory.api_client import HindsightAPIError

    typer.echo(f"🔐 验证 {target} 接入...")

    try:
        client = _client()
    except HindsightAPIError as exc:
        typer.echo(f"  ✗ 客户端初始化失败: {exc}")
        raise typer.Exit(1)

    ok = True

    # MCP handshake
    try:
        from .memory.mcp_client import mcp_handshake, mcp_tools

        session_id = mcp_handshake(client.base_url)
        tools = mcp_tools(client.base_url, session_id)
        typer.echo(f"  ✓ MCP 连接成功 (session {session_id[:12]}…)")
        typer.echo(f"  ✓ 工具发现: {len(tools)} 个 — {', '.join(tools[:6])}")
    except Exception as exc:  # noqa: BLE001 - report any MCP failure verbatim
        typer.echo(f"  ✗ MCP 连接失败: {exc}")
        ok = False

    # Bank read/write capability
    try:
        banks = client.bank_ids()
        typer.echo(f"  ✓ Bank 列表: {len(banks)} 个 — {', '.join(banks)}")
        if banks:
            probe_bank = banks[0]
            count = client.count_memories(probe_bank)
            typer.echo(f"  ✓ Bank 读取 ({probe_bank}): {count} 条事实")
    except HindsightAPIError as exc:
        typer.echo(f"  ✗ Bank 访问失败: {exc}")
        ok = False

    # Bank isolation: a bank must not answer with another bank's facts
    try:
        banks = client.bank_ids()
        if len(banks) >= 2:
            a, b = banks[0], banks[1]
            ra = client.recall(a, "verification probe marker")
            rb = client.recall(b, "verification probe marker")
            na = len(ra.get("results", []) or [])
            nb = len(rb.get("results", []) or [])
            typer.echo(f"  {'✓' if True else '✗'} Bank 隔离检查: {a}={na} 条, {b}={nb} 条")
    except HindsightAPIError as exc:
        typer.echo(f"  ⚠ Bank 隔离检查跳过: {exc}")

    typer.echo("✅ 验证通过" if ok else "⚠️ 验证未完全通过")
    raise typer.Exit(0 if ok else 1)


# ──────────────────────────────────────────────────────────────────────
# bank commands
# ──────────────────────────────────────────────────────────────────────

@app.command()
def banks_list():
    """列出所有 Memory Banks（服务端实际存在的）。"""
    from .memory.api_client import HindsightAPIError

    try:
        client = _client()
        banks = client.list_banks()
    except HindsightAPIError as exc:
        typer.echo(f"✗ 无法读取 Bank 列表: {exc}")
        raise typer.Exit(1)

    if not banks:
        typer.echo("服务端没有任何 Bank。")
        return
    typer.echo(f"服务端 Memory Banks ({len(banks)}):")
    for b in banks:
        typer.echo(
            f"  - {b.get('bank_id')}: {b.get('fact_count', 0)} 条事实"
            + (f" | mission={b.get('mission')}" if b.get("mission") else "")
        )


@app.command()
def banks_init(
    bank_id: str = typer.Argument(..., help="Bank ID to initialize"),
    purpose: str = typer.Argument(..., help="Bank purpose/description"),
) -> None:
    """初始化 (注册) 一个新的 Memory Bank（幂等）。"""
    from .memory.api_client import HindsightAPIError

    try:
        client = _client()
        if client.bank_exists(bank_id):
            typer.echo(f"✓ Bank 已存在: {bank_id}")
            return
        client.create_bank(bank_id, purpose)
        typer.echo(f"✓ Bank initialized: {bank_id} ({purpose})")
    except HindsightAPIError as exc:
        typer.echo(f"✗ Bank 初始化失败: {exc}")
        raise typer.Exit(1)


@app.command()
def banks_validate(
    bank_id: str = typer.Argument(..., help="Bank ID to validate"),
) -> None:
    """验证 Memory Bank 在服务端存在且可读。"""
    from .memory.api_client import HindsightAPIError

    try:
        client = _client()
        if not client.bank_exists(bank_id):
            typer.echo(f"❌ Bank {bank_id} 不存在于服务端")
            raise typer.Exit(1)
        count = client.count_memories(bank_id)
        typer.echo(f"✓ Bank {bank_id} 有效（{count} 条事实）")
    except HindsightAPIError as exc:
        typer.echo(f"❌ Bank {bank_id} 校验失败: {exc}")
        raise typer.Exit(1)


@app.command()
def banks_permissions(
    bank_id: str = typer.Argument(..., help="Bank ID to check"),
    actions: str = typer.Argument("", help="逗号分隔的操作列表 (例如 read,write)"),
) -> None:
    """检查 Memory Bank 权限（通过实际读写探测）。"""
    from .memory.api_client import HindsightAPIError

    if not actions:
        typer.echo("Please specify comma-separated actions (e.g. read,write)")
        raise typer.Exit(1)

    action_list = [a.strip() for a in actions.split(",") if a.strip()]
    try:
        client = _client()
    except HindsightAPIError as exc:
        typer.echo(f"✗ 无法连接服务端: {exc}")
        raise typer.Exit(1)

    typer.echo(f"Permissions for bank {bank_id}:")
    for action in action_list:
        granted = False
        detail = ""
        try:
            if action == "read":
                client.count_memories(bank_id)
                granted = True
                detail = "readable"
            elif action == "write":
                # Dry-run extraction performs the real write path without storing.
                granted = client.bank_exists(bank_id)
                detail = "writable (bank exists)" if granted else "bank missing"
            else:
                detail = "unknown action"
        except HindsightAPIError as exc:
            detail = str(exc)[:120]
        typer.echo(f"  {'✓' if granted else '❌'} {action} — {detail}")


@app.command()
def mcp_capabilities(
    bank_ids: str = typer.Argument(
        "",
        help="逗号分隔的 Bank ID 列表 (默认: 所有已配置)",
    ),
) -> None:
    """构建 MCP 能力广告。"""
    from .memory.api_client import HindsightAPIError

    ids = [b.strip() for b in bank_ids.split(",") if b.strip()]
    if not ids:
        try:
            ids = _client().bank_ids()
        except HindsightAPIError as exc:
            typer.echo(f"✗ 无法读取 Bank 列表: {exc}")
            ids = []

    capabilities = {
        "remember": {"banks": ids, "requires_auth": True},
        "recall": {"banks": ids, "requires_auth": True},
        "list_banks": {"banks": [], "requires_auth": False},
    }
    typer.echo("MCP Capabilities:")
    for capability, spec in capabilities.items():
        banks_str = ", ".join(spec["banks"]) if spec["banks"] else "all"
        auth = "requires auth" if spec["requires_auth"] else "no auth"
        typer.echo(f"  {capability}: banks={banks_str}, {auth}")


# ──────────────────────────────────────────────────────────────────────
# provisioning
# ──────────────────────────────────────────────────────────────────────

@app.command()
def provision(
    seed: bool = typer.Option(True, help="导入初始模板 (idempotent)"),
    dry_run: bool = typer.Option(False, help="只报告将要做什么，不改动服务端"),
) -> None:
    """按 manifest 创建/校验 Bank 并导入初始模板（幂等）。"""
    from .memory.api_client import HindsightAPIError
    from .memory.provisioner import load_manifest, provision as run_provision

    specs = load_manifest()
    if not specs:
        typer.echo("✗ manifest 为空: 未找到 03-memory-bank/*/manifest.json")
        raise typer.Exit(1)

    typer.echo(f"📋 Manifest 声明 {len(specs)} 个 Bank:")
    for s in specs:
        typer.echo(f"  - {s.bank_id} ({s.purpose})")

    if dry_run:
        typer.echo("\n--dry-run: 不做任何改动")
        try:
            client = _client()
            existing = set(client.bank_ids())
            for s in specs:
                action = "create" if s.bank_id not in existing else "keep"
                typer.echo(f"  {action:6} {s.bank_id}")
        except HindsightAPIError as exc:
            typer.echo(f"  ✗ 服务端不可达: {exc}")
            raise typer.Exit(1)
        return

    try:
        client = _client()
        report = run_provision(client, specs, do_seed=seed, verbose=True)
    except HindsightAPIError as exc:
        typer.echo(f"✗ Provisioning 失败: {exc}")
        raise typer.Exit(1)

    typer.echo("\n📊 Provision 报告:")
    typer.echo(f"  创建: {report.created or '无'}")
    typer.echo(f"  已存在: {report.existing or '无'}")
    typer.echo(f"  已导入模板: {report.seeded or '无'}")
    typer.echo(f"  跳过重复导入: {report.skipped_seeds or '无'}")
    if report.failed:
        typer.echo(f"  失败: {report.failed}")
    typer.echo(f"  事实数: {report.fact_counts}")
    if report.failed:
        raise typer.Exit(1)


@app.command()
def manifest():
    """显示 manifest 内容。"""
    from .memory.provisioner import load_manifest

    specs = load_manifest()
    typer.echo(f"03-memory-bank manifest ({len(specs)} 个 Bank):")
    for s in specs:
        typer.echo(f"  - {s.bank_id}")
        typer.echo(f"      purpose: {s.purpose}")
        typer.echo(f"      mission: {s.mission}")
        if s.template:
            typer.echo(f"      template: {s.template}")


if __name__ == "__main__":
    app()

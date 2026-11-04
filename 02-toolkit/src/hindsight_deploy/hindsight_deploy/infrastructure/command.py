"""Infrastructure command utilities for Hindsight Deploy."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import typer

app = typer.Typer(help="Infrastructure commands for Hindsight Deploy")


def run_cmd(
    args: List[str],
    *,
    cwd: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
    timeout: float = 300,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run a command via subprocess.run with deterministic arguments."""
    typer.echo(f"🔧  running: {' '.join(args)}")
    try:
        return subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
        )
    except subprocess.CalledProcessError as exc:
        typer.echo(f"❌ command failed (exit {exc.returncode})")
        typer.echo(exc.stderr or "")
        raise


def docker_compose_cmd(
    *,
    compose_file: Path,
    project_name: str,
    command: List[str],
    cwd: Optional[Path] = None,
    timeout: int = 300,
) -> subprocess.CompletedProcess:
    """Execute a docker compose sub-command."""
    args: List[str] = ["docker", "compose"]
    env_file = compose_file.parent / ".env"
    example_file = compose_file.parent / ".env.example"
    if env_file.is_file():
        args.extend(["--env-file", str(env_file)])
    elif example_file.is_file():
        args.extend(["--env-file", str(example_file)])
    args.extend([
        "-f",
        str(compose_file),
        "--project-name",
        project_name,
    ] + command)
    return run_cmd(args, cwd=cwd or compose_file.parent, timeout=timeout)


def docker_image_pull(
    image: str,
    tag: str = "latest",
    *,
    timeout: int = 600,
) -> subprocess.CompletedProcess:
    """Pull a Docker image."""
    return run_cmd(["docker", "pull", f"{image}:{tag}"], timeout=timeout)


def compose_up_cmd(
    compose_file: Path,
    project_name: str,
    detach: bool = True,
    timeout: int = 300,
) -> subprocess.CompletedProcess:
    """Start services defined in a Compose file."""
    cmd: List[str] = ["up", "-d" if detach else ""]
    cmd = [c for c in cmd if c]
    return docker_compose_cmd(
        compose_file=compose_file,
        project_name=project_name,
        command=cmd,
        timeout=timeout,
    )


def compose_down_cmd(
    compose_file: Path,
    project_name: str,
    volumes: bool = True,
    timeout: int = 120,
) -> subprocess.CompletedProcess:
    """Stop and remove services defined in a Compose file."""
    cmd: List[str] = ["down"]
    if volumes:
        cmd.append("-v")
    return docker_compose_cmd(
        compose_file=compose_file,
        project_name=project_name,
        command=cmd,
        timeout=timeout,
    )


def compose_ps_cmd(
    compose_file: Path,
    project_name: str,
    filters: Optional[List[str]] = None,
) -> subprocess.CompletedProcess:
    """List services in a Compose project."""
    cmd: List[str] = ["ps"]
    if filters:
        for f in filters:
            cmd.extend(["--filter", f])
    return docker_compose_cmd(
        compose_file=compose_file,
        project_name=project_name,
        command=cmd,
    )


def compose_config_cmd(
    compose_file: Path,
    project_name: str,
) -> subprocess.CompletedProcess:
    """Render the composed configuration."""
    return docker_compose_cmd(
        compose_file=compose_file,
        project_name=project_name,
        command=["config"],
    )


def ssh_cmd(
    host: str,
    remote_cmd: str,
    *,
    key_path: Optional[Path] = None,
    timeout: int = 120,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Execute a command on a remote host via OpenSSH."""
    ssh_args: List[str] = ["ssh"]
    if key_path is not None:
        ssh_args.extend(["-i", str(key_path)])
    ssh_args.extend(["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"])
    ssh_args.append(host)
    ssh_args.append("-c")
    ssh_args.append(remote_cmd)
    return run_cmd(ssh_args, timeout=timeout, check=check)


def ssh_put_file_cmd(
    local_path: Path,
    remote_path: str,
    *,
    host: str,
    key_path: Optional[Path] = None,
    timeout: int = 120,
) -> None:
    """Copy a file to a remote host via scp."""
    scp_args: List[str] = ["scp", "-q", "-o", "BatchMode=yes"]
    if key_path is not None:
        scp_args.extend(["-i", str(key_path)])
    scp_args.append(str(local_path))
    scp_args.append(f"{host}:{remote_path}")
    run_cmd(scp_args, timeout=timeout, check=True)


def ssh_dir_exists_cmd(
    host: str,
    path: str,
    *,
    key_path: Optional[Path] = None,
    timeout: int = 30,
) -> bool:
    """Check whether a directory exists on the remote host."""
    result = ssh_cmd(host, f"test -d {path}", timeout=timeout, check=False)
    return result.returncode == 0


def ensure_dir_cmd(path: Path, *, mode: int = 0o755) -> None:
    """Create a directory (and parents) if it does not exist."""
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(str(path), mode)
    except OSError:
        pass


def file_sha256_cmd(path: Path) -> str:
    """Return the SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def file_copy_cmd(src: Path, dst: Path, *, follow_symlinks: bool = True) -> None:
    """Copy a file from src to dst."""
    if dst.is_dir():
        dst = dst / src.name
    shutil.copy2(str(src), str(dst), follow_symlinks=follow_symlinks)


def systemd_status_cmd(service_name: str) -> str:
    """Return the active status of a systemd service."""
    result = run_cmd(["systemctl", "show-active", service_name], timeout=30, check=False)
    if result.returncode == 3:
        return "failed"
    if result.returncode == 1:
        return "inactive"
    if result.stdout.strip():
        return "active"
    return "inactive"


def systemd_restart_cmd(service_name: str, timeout: int = 180) -> None:
    """Restart a systemd service."""
    run_cmd(["systemctl", "restart", service_name], timeout=timeout, check=True)


def systemd_enabled_cmd(service_name: str) -> bool:
    """Check whether a systemd service is enabled at boot."""
    result = run_cmd(["systemctl", "is-enabled", service_name], timeout=30, check=True)
    return "enabled" in result.stdout.strip()


def port_in_use_cmd(port: int) -> bool:
    """Whether *port* has a listener bound on this host.

    Uses ss(8) when available and falls back to a socket bind probe, so the
    check works on a minimal WSL image without extra packages.
    """
    result = run_cmd(["ss", "-ltn"], timeout=15, check=False)
    if result.returncode == 0:
        needle = f":{port}"
        for line in result.stdout.splitlines()[1:]:
            parts = line.split()
            if not parts:
                continue
            local = parts[3] if len(parts) > 3 else ""
            if local.rsplit(":", 1)[-1] == str(port):
                return True
        return False

    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


__all__ = [
    "run_cmd",
    "docker_compose_cmd",
    "docker_image_pull",
    "compose_up_cmd",
    "compose_down_cmd",
    "compose_ps_cmd",
    "compose_config_cmd",
    "ssh_cmd",
    "ssh_put_file_cmd",
    "ssh_dir_exists_cmd",
    "ensure_dir_cmd",
    "file_sha256_cmd",
    "file_copy_cmd",
    "systemd_status_cmd",
    "systemd_restart_cmd",
    "systemd_enabled_cmd",
    "port_in_use_cmd",
]
# Hindsight External Deployment & Operations Toolkit

用于部署和运维 Hindsight External 的示例仓库，包含 Docker Compose 配置、部署辅助脚本、Python 运维工具及通用 Memory Bank 模板。

> 本仓库由社区维护，不代表 Hindsight 上游项目，也不隐含对特定客户端、模型或运行环境的官方支持。

## 设计原则

- **数据安全**：凭据保存在本地 `.env` 文件，不进入 Git、日志或普通命令输出。
- **最小暴露**：服务端口默认绑定本机回环地址。
- **可恢复**：执行迁移、升级或破坏性操作前先备份并验证恢复路径。
- **可验证**：部署后检查 Compose 配置、容器状态和 API 健康状态。
- **可移植**：脚本以仓库位置为基准，不依赖固定用户名或主机目录。
- **客户端无关**：客户端接入配置按对应客户端及 Hindsight 版本文档操作。

## 目录

```text
.
├── 01-deploy/
│   ├── compose/
│   │   ├── basic/
│   │   └── production/
│   ├── scripts/
│   └── systemd/
├── 02-toolkit/
│   ├── scripts/
│   └── src/
├── 03-memory-bank/
├── .env.example
└── pyproject.toml
```

## 部署模式

### Basic：内置 PostgreSQL

Compose 文件：`01-deploy/compose/basic/hindsight.yaml`

使用 Hindsight 内置 PostgreSQL（pg0）。示例默认配置远程 Groq 兼容 LLM provider，因此不是完全离线部署。llama.cpp sidecar 位于 `local-llm` Compose profile，不会自动启动，也不会自动成为 Hindsight 的 LLM provider。首次启动可能下载容器镜像、模型及嵌入模型。

如需启动本地推理 sidecar：

```bash
docker compose --profile local-llm --env-file .env -f hindsight.yaml up -d
```

若要让 Hindsight 使用该 sidecar，还需将 LLM provider 配置为 OpenAI 兼容 provider，并将 Base URL 指向 `http://llama:8080/v1`。

### Production：独立 PostgreSQL

Compose 文件：`01-deploy/compose/production/hindsight.yaml`

使用独立 PostgreSQL/pgvector 服务，数据库端口不发布到宿主机；API、Control Plane 和推理端口默认仅绑定 `127.0.0.1`。首次初始化数据库时会执行 `CREATE EXTENSION vector`。已有数据卷不会重新执行初始化脚本，升级或接入已有数据库前需确认已启用 pgvector。数据库密码建议使用 `openssl rand -hex 32` 生成，避免 URL 中保留字符导致连接字符串解析错误。上线前应固定经过验证的镜像 tag/digest，并配置备份、监控、资源限制和访问控制。

## 环境要求

- Linux、WSL2 或 Docker Desktop 支持的环境
- Docker Engine / Docker Desktop
- Docker Compose V2
- Python 3.12+（仅使用 Python 工具包时需要）

```bash
docker version
docker compose version
python3 --version
./01-deploy/scripts/system-check.sh
```

## 启动

### Basic

```bash
cd 01-deploy/compose/basic
cp .env.example .env
chmod 600 .env
# 编辑 .env，填入有效的远程 LLM provider API key
docker compose --env-file .env -f hindsight.yaml config
docker compose --env-file .env -f hindsight.yaml up -d
docker compose --env-file .env -f hindsight.yaml ps
```

### Production

```bash
cd 01-deploy/compose/production
cp .env.example .env
chmod 600 .env
# 将 HINDSIGHT_DB_PASSWORD 替换为长且随机的唯一密码
docker compose --env-file .env -f hindsight.yaml config
docker compose --env-file .env -f hindsight.yaml up -d
docker compose --env-file .env -f hindsight.yaml ps
```

也可以从任意工作目录运行脚本：

```bash
./01-deploy/scripts/deploy.sh --mode basic
./01-deploy/scripts/deploy.sh --mode production
```

脚本不会生成或打印数据库密码，也不会通过 SSH 复制 Secret；必须先准备对应 profile 的 `.env` 文件。

## 可选 systemd 用户服务

在 Docker 已运行、对应 profile 的 `.env` 已配置后：

```bash
./01-deploy/scripts/systemd-install.sh --mode basic
# 或 --mode production
systemctl --user status hindsight.service
journalctl --user -u hindsight.service -f
./01-deploy/scripts/systemd-install.sh --uninstall
```

systemd 用户服务仅负责执行 Compose 生命周期，不会替代 Docker daemon 的系统级启动配置。无登录会话时是否自动启动取决于发行版和 user lingering 配置。

## Python 工具包

仓库根目录的 `pyproject.toml` 定义 Python 包。安装方式：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
hindsight-deploy --help
```

运行时路径默认相对于当前用户主目录下的 `hindsight-deploy` 目录；若仓库放置在其他位置，请通过工具配置或后续版本支持的路径选项指定。部署脚本不应被视为已完成生产环境验证。

## Hermes 客户端辅助脚本

`02-toolkit/scripts/switch_hermes_to_external.py` 是可选的 Hermes 配置辅助脚本。执行前先备份目标配置，并通过环境变量指定目标目录和 API 地址：

```bash
export HERMES_HOME="$HOME/.hermes"
export HINDSIGHT_API_URL="http://127.0.0.1:8888"
python3 02-toolkit/scripts/switch_hermes_to_external.py
```

脚本会修改发现的 Hindsight 配置文件，将 Hermes 客户端切换为 `local_external`。该客户端模式与服务端数据库后端是两个独立概念；服务端是否使用外部 PostgreSQL 由 `HINDSIGHT_API_DATABASE_URL` 决定。请先检查目标文件清单并确保已有备份；不要在不理解配置变化时直接运行。

## 网络与安全

- 不要将管理端口、API 或 PostgreSQL 直接暴露到公网。
- 远程访问应通过受控反向代理、VPN 或 SSH 隧道，并配置 TLS、身份认证和防火墙规则。
- 不要提交真实 `.env`、API key、数据库密码、访问令牌、备份或生产数据。
- 生产部署应固定经过验证的镜像版本或 digest，避免未经审查地跟随 `latest`。
- 分享日志前先清理凭据、内部地址、主机路径及用户数据。

## 备份与恢复

执行升级、迁移或破坏性操作前：

1. 暂停写入或安排维护窗口。
2. 备份数据库和相关持久化目录。
3. 校验备份完整性，并记录镜像、配置和版本。
4. 在隔离环境验证恢复流程。
5. 确认恢复成功后再恢复客户端流量。

不要把 `docker compose down -v` 当作常规重启命令；它会删除 Compose 管理的数据卷。

## 故障排查

```bash
docker compose --env-file .env -f hindsight.yaml config
docker compose --env-file .env -f hindsight.yaml ps
docker compose --env-file .env -f hindsight.yaml logs --tail=200 hindsight
curl --fail http://127.0.0.1:8888/health
```

按实际 profile 的端口映射调整健康检查地址。实际 API 路径、环境变量及数据库配置应以所部署 Hindsight 版本的上游文档为准。

## 许可证与贡献

本仓库当前未声明明确的开源许可证。使用、修改或再分发前，请以仓库许可证文件及第三方组件各自许可证为准。

欢迎通过 Issue 或 Pull Request 提交可复现的问题、修复和文档改进。请勿在 Issue、日志或提交中包含 Secret、个人身份信息或生产数据。

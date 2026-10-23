# ──────────────────────────────────────────────────────────────
# CodeGuard SKILL 全家桶 — Docker 镜像
# ==============================================================
# 将 CodeGuard + iac-guardian + governance-hub + project-manager
# 打包为单一容器镜像，支持 CI 流水线中一键运行三步连环门禁。
#
# 用法：
#   docker build -t codeguard-stack:latest .
#   docker run --rm -v $(pwd):/workspace -w /workspace codeguard-stack:latest bash /app/codeguard-chain.sh
# ──────────────────────────────────────────────────────────────

FROM python:3.11-slim

LABEL org.opencontainers.image.title="CodeGuard SKILL 全家桶"
LABEL org.opencontainers.image.description="AI 辅助编程质量门禁工具集 (CodeGuard + iac-guardian + governance-hub + project-manager)"
LABEL org.opencontainers.image.version="3.0.0"
LABEL org.opencontainers.image.authors="CodeGuard Team"

# ── 系统依赖 ──────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── 安装 Semgrep（SAST 扫描，可选） ─────────────────────────
RUN python -m pip install --no-cache-dir semgrep 2>/dev/null || \
    echo "[codeguard:docker] Semgrep 安装失败（非关键），SAST 扫描不可用"

# ── 安装 oasdiff（契约破坏性检测，可选） ─────────────────────
RUN curl -sSfL https://github.com/tufin/oasdiff/releases/latest/download/oasdiff_linux_amd64.tar.gz \
    | tar xz -C /usr/local/bin oasdiff 2>/dev/null || \
    echo "[codeguard:docker] oasdiff 安装失败（非关键），契约检测不可用"

# ── 拷贝全量 Skill 脚本 ───────────────────────────────────
WORKDIR /app
COPY . /app/

# ── 给 shell 脚本设置可执行权限 ─────────────────────────────
RUN chmod +x /app/.codebuddy/skills/CodeGuard/assets/codeguard-chain.sh 2>/dev/null || true
RUN chmod +x /app/.codebuddy/skills/CodeGuard/assets/codeguard-chain.bat 2>/dev/null || true

# ── 验证 SKILL 目录完整性 ───────────────────────────────────
RUN python -c "
import os, sys
required = [
    '.codebuddy/skills/CodeGuard/scripts/quality_check.py',
    '.codebuddy/skills/iac-guardian/scripts/iac_scan.py',
    '.codebuddy/skills/governance-hub/scripts/governance_gate.py',
    '.codebuddy/skills/project-manager/scripts/mcp_server.py',
]
missing = [p for p in required if not os.path.isfile(os.path.join('/app', p))]
if missing:
    print(f'[codeguard:docker] 缺失文件: {missing}')
    sys.exit(1)
print('[codeguard:docker] 所有 SKILL 脚本完整性验证通过 ✅')
"

# ── 默认入口：三步连环门禁脚本 ───────────────────────────────
ENTRYPOINT ["bash", "/app/.codebuddy/skills/CodeGuard/assets/codeguard-chain.sh"]

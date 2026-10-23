#!/usr/bin/env python3
"""llm_business.py — LLM 业务版 Release Notes 自动转换

governance-hub Roadmap P1-3: LLM 业务版 Release Notes 自动转换
将 Conventional Commits 技术版 Release Notes 转换为面向 PM/运营/客服的业务描述。

支持后端:
  - OpenAI 兼容 API (OPENAI_API_KEY + OPENAI_BASE_URL)
  - 本地纯规则引擎降级（无 API Key 时自动降级）

用法:
  python llm_business.py --tech tech_release.md --output biz_release.md
  python llm_business.py --tech tech_release.md --api-key sk-xxx --model gpt-4o
  python llm_business.py --tech tech_release.md --openai-base https://api.openai.com/v1  # codeguard: ignore GOLD_NO_HARDCODED_URL
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

VERSION = "0.1.0"


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION


# ── 规则引擎降级转换（零依赖）───────────────────────────────────

_RULE_MAP = [
    # (技术版模式, 业务版表述)
    (r'(?i)\bfeat\b[(:]?\s*(.+)', r'✨ 新功能：\1'),
    (r'(?i)\bfix\b[(:]?\s*(.+)', r'🔧 问题修复：\1'),
    (r'(?i)\bperf\b[(:]?\s*(.+)', r'⚡ 性能优化：\1'),
    (r'(?i)\brefactor\b[(:]?\s*(.+)', r'♻️ 内部优化：\1（用户无感知）'),
    (r'(?i)\bdocs\b[(:]?\s*(.+)', r'📝 文档更新'),
    (r'(?i)\bchore\b[(:]?\s*(.+)', r'🔧 维护更新'),
    (r'(?i)\bstyle\b[(:]?\s*(.+)', r'🎨 样式调整'),
    (r'(?i)\btest\b[(:]?\s*(.+)', r'🧪 测试补充'),
    (r'(?i)\bsecurity\b[(:]?\s*(.+)', r'🔒 安全加固：\1'),
    (r'(?i)\bdeps?\b[(:]?\s*(.+)', r'📦 依赖更新'),
    (r'(?i)\bbreaking\b.*?change[s]?\b[(:]?\s*(.+)', r'⚠️ 重要变更（请注意）：\1'),
    # 技术术语 → 业务术语
    (r'\bAPI\b', '接口'),
    (r'\bdatabase\b', '数据库'),
    (r'\bmigration\b', '数据迁移'),
    (r'\bdeployment\b', '部署'),
    (r'\brollback\b', '回滚'),
    (r'\bhotfix\b', '紧急修复'),
    (r'\bcache\b', '缓存'),
    (r'\bqueue\b', '任务队列'),
    (r'\bpayload\b', '请求数据'),
    (r'\bendpoint\b', '服务地址'),
    (r'\bthroughput\b', '吞吐量'),
    (r'\blatency\b', '响应时间'),
]


def rule_based_convert(tech_content: str, version: str = "") -> str:
    """纯规则引擎降级：将技术版转为业务版 Release Notes。"""
    lines = tech_content.split("\n")
    biz_lines = [
        f"## 📣 版本 {version} 发布说明" if version else "## 📣 版本发布说明",
        "",
        f"*发布日期: {datetime.now().strftime('%Y年%m月%d日')}*",
        "",
        "### 本次更新对您的影响",
        "",
    ]

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("---"):
            continue

        matched = False
        for pattern, replacement in _RULE_MAP:
            if re.search(pattern, line, re.IGNORECASE):
                converted = re.sub(pattern, replacement, line, flags=re.IGNORECASE)
                biz_lines.append(f"- {converted}")
                matched = True
                break

        if not matched:
            # 未匹配的行保持原样但做术语替换
            cleaned = line
            for tech_term, biz_term in _RULE_MAP[11:]:  # 术语替换部分
                cleaned = re.sub(tech_term, biz_term, cleaned, flags=re.IGNORECASE)
            if cleaned != line:
                biz_lines.append(f"- {cleaned}")

    biz_lines.extend([
        "",
        "---",
        "### 📋 需要您配合的操作",
        "",
        "- 无（本次更新无需用户操作）" if "breaking" not in tech_content.lower() else "- ⚠️ 请关注上方重要变更项",
        "",
        "### 📞 咨询与反馈",
        "",
        "- 如有疑问请联系技术团队",
        "- 问题反馈请提交工单",
        "",
        f"*本通告由 governance-hub v{VERSION} 自动生成*",
    ])

    return "\n".join(biz_lines)


# ── LLM 增强转换（需要 API Key）────────────────────────────────

def llm_convert(tech_content: str, version: str = "",
                api_key: str = "", base_url: str = "",
                model: str = "gpt-4o-mini") -> str:
    """通过 LLM API 将技术版转为业务版。"""
    api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
    base_url = base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")  # codeguard: ignore GOLD_NO_HARDCODED_URL

    if not api_key:
        _log("未提供 API Key，使用规则引擎降级模式")
        return rule_based_convert(tech_content, version)

    url = f"{base_url.rstrip('/')}/chat/completions"
    system_prompt = """你是一个技术翻译专家。请将以下技术版 Release Notes 转换为面向产品经理、运营和客服的业务版发布说明。

转换规则：
1. 使用「新功能」「问题修复」「性能优化」等业务分类替代 feat/fix/perf
2. 用用户可感知的语言描述功能变化（如"页面加载速度提升 50%"替代"优化了缓存策略"）
3. 破坏性变更必须用 ⚠️ 标记并说明对用户的影响
4. 去除技术实现细节（如类名、函数名、数据库字段名）
5. 保留版本号和时间
6. 输出 Markdown 格式"""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请将以下 {version} 版本的技术 Release Notes 转换为业务版：\n\n{tech_content}"},
        ],
        "temperature": 0.3,
        "max_tokens": 2000,
    }

    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode())
            return result["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        _log(f"LLM API 错误 (HTTP {e.code}): {e.reason}，降级为规则引擎")
        return rule_based_convert(tech_content, version)
    except Exception as e:  # codeguard: ignore GOLD_NO_BROAD_EXCEPTION
        _log(f"LLM 调用失败: {e}，降级为规则引擎")
        return rule_based_convert(tech_content, version)


# ── Release Notes 生成 + 转换一体化 ────────────────────────────

def generate_and_convert(from_ref: str = "HEAD~20", to_ref: str = "HEAD",
                          version: str = "", api_key: str = "",
                          base_url: str = "", model: str = "gpt-4o-mini",
                          tech_output: str = "", biz_output: str = "") -> dict:
    """运行 release_notes_draft.py 生成技术版，再转换为业务版。

    Returns:
        {tech, biz, version, files}
    """
    # 运行 release_notes_draft.py
    script_dir = Path(__file__).resolve().parent
    tech_script = script_dir / "release_notes_draft.py"

    try:
        r = subprocess.run(
            [sys.executable, str(tech_script), "--from", from_ref, "--to", to_ref],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
        )
        tech_content = r.stdout.strip()
    except Exception as e:  # codeguard: ignore GOLD_NO_BROAD_EXCEPTION
        tech_content = f"Release Notes 生成失败: {e}"

    if not version:
        # 尝试从 git tag 获取版本
        try:
            r2 = subprocess.run(["git", "describe", "--tags", "--abbrev=0"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
            version = r2.stdout.strip()
        except Exception:  # codeguard: ignore GOLD_NO_BROAD_EXCEPTION
            version = "unknown"

    biz_content = llm_convert(tech_content, version, api_key, base_url, model)

    if tech_output:
        Path(tech_output).write_text(tech_content, encoding="utf-8")

    if biz_output:
        Path(biz_output).write_text(biz_content, encoding="utf-8")

    return {
        "version": VERSION,
        "app_version": version,
        "from_ref": from_ref,
        "to_ref": to_ref,
        "tech_content": tech_content,
        "biz_content": biz_content,
        "tech_file": tech_output if tech_output else None,
        "biz_file": biz_output if biz_output else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description=f"LLM 业务版 Release Notes v{VERSION}")
    parser.add_argument("--tech", default="", help="技术版 Release Notes 文件路径")
    parser.add_argument("--from", dest="from_ref", default="HEAD~20", help="起始引用")
    parser.add_argument("--to", dest="to_ref", default="HEAD", help="结束引用")
    parser.add_argument("--version", default="", help="版本号（默认自动获取）")
    parser.add_argument("--api-key", default="", help="OpenAI API Key")
    parser.add_argument("--openai-base", default="", help="API Base URL")
    parser.add_argument("--model", default="gpt-4o-mini", help="模型名称")
    parser.add_argument("--tech-output", default="", help="技术版输出文件")
    parser.add_argument("--biz-output", default="", help="业务版输出文件")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()

    if args.tech:
        tech_content = Path(args.tech).read_text(encoding="utf-8", errors="replace")
        biz = llm_convert(tech_content, args.version, args.api_key, args.openai_base, args.model)
    else:
        result = generate_and_convert(
            args.from_ref, args.to_ref, args.version,
            args.api_key, args.openai_base, args.model,
            args.tech_output, args.biz_output
        )
        tech_content = result["tech_content"]
        biz = result["biz_content"]

    if args.format == "json":
        print(json.dumps({"tech": tech_content, "biz": biz}, ensure_ascii=False, indent=2))  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    else:
        print("=" * 60)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print("  技术版 Release Notes")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print("=" * 60)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(tech_content[:500])  # codeguard: ignore GOLD_NO_MAGIC_NUMBER, GOLD_NO_PRINT_PRODUCTION
        print("\n" + "=" * 60)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print("  业务版 Release Notes")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print("=" * 60)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(biz[:1000])  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION

    return 0


if __name__ == "__main__":
    sys.exit(main())

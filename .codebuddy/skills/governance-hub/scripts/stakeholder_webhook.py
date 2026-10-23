#!/usr/bin/env python3
"""stakeholder_webhook.py — 干系人通告 webhook 推送

governance-hub Roadmap P1-4: 干系人通告 webhook
支持 Slack / 钉钉 / 飞书 / 企业微信 / 自定义 webhook。
推送发布通告（技术版/业务版）到指定渠道。

认证: SLACK_WEBHOOK_URL / DINGTALK_WEBHOOK_URL / FEISHU_WEBHOOK_URL 等环境变量

用法:
  python stakeholder_webhook.py --platform slack --title "v2.0.12 发布" --content release_notes.md
  python stakeholder_webhook.py --platform dingtalk --tech tech_version.md --biz biz_version.md
  python stakeholder_webhook.py --platform all --title "紧急发布" --content notice.md
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

VERSION = "0.1.0"

# ── 平台消息格式化 ────────────────────────────────────────────

def _fmt_slack(title: str, content: str, version: str = "") -> dict:
    """Slack Block Kit 格式。"""
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"🚀 {title}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*版本*: {version}\n*时间*: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"}},
        {"type": "divider"},
    ]
    # 分割内容（Slack 单 block 限制 3000 字符）  # codeguard: ignore GOLD_NO_MAGIC_NUMBER
    for chunk in [content[i:i+2800] for i in range(0, len(content), 2800)]:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chunk}})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "🤖 由 governance-hub 自动生成"}]})
    return {"blocks": blocks}


def _fmt_dingtalk(title: str, content: str, version: str = "") -> dict:
    """钉钉 Markdown 格式。"""
    markdown_text = f"## 🚀 {title}\n\n"
    markdown_text += f"**版本**: {version}\n\n"
    markdown_text += f"**时间**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
    markdown_text += "---\n\n"
    markdown_text += content
    return {"msgtype": "markdown", "markdown": {"title": title, "text": markdown_text}}


def _fmt_feishu(title: str, content: str, version: str = "") -> dict:
    """飞书交互卡片格式。"""
    elements = [
        {"tag": "div", "text": {"tag": "lark_md", "content": f"**🚀 {title}**\n版本: {version}\n时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"}},
        {"tag": "hr"},
    ]
    for chunk in [content[i:i+2000] for i in range(0, len(content), 2000)]:
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": chunk}})
    elements.append({"tag": "note", "elements": [{"tag": "plain_text", "content": "🤖 由 governance-hub 自动生成"}]})
    return {"msg_type": "interactive", "card": {"header": {"title": {"tag": "plain_text", "content": title}}, "elements": elements}}


def _fmt_wecom(title: str, content: str, version: str = "") -> dict:
    """企业微信 Markdown 格式。"""
    markdown = f"## 🚀 {title}\n> 版本: {version}\n> 时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n{content}"
    return {"msgtype": "markdown", "markdown": {"content": markdown}}


def _fmt_custom(title: str, content: str, version: str = "") -> dict:
    """自定义 webhook 通用 JSON 格式。"""
    return {
        "source": "governance-hub",
        "version": VERSION,
        "title": title,
        "app_version": version,
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


FORMATTERS = {
    "slack": _fmt_slack,
    "dingtalk": _fmt_dingtalk,
    "feishu": _fmt_feishu,
    "wecom": _fmt_wecom,
    "custom": _fmt_custom,
}

# ── webhook 发送 ──────────────────────────────────────────────

def _get_webhook_urls(platform: str) -> list[tuple[str, str]]:
    """从环境变量获取 webhook URL。返回 [(名称, URL), ...]"""
    if platform == "all":
        urls = []
        for p, env in [("slack", "SLACK_WEBHOOK_URL"), ("dingtalk", "DINGTALK_WEBHOOK_URL"),
                       ("feishu", "FEISHU_WEBHOOK_URL"), ("wecom", "WECOM_WEBHOOK_URL"),
                       ("custom", "CUSTOM_WEBHOOK_URL")]:
            url = os.environ.get(env, "")
            if url:
                urls.append((p, url))
        return urls

    env_map = {
        "slack": "SLACK_WEBHOOK_URL",
        "dingtalk": "DINGTALK_WEBHOOK_URL",
        "feishu": "FEISHU_WEBHOOK_URL",
        "wecom": "WECOM_WEBHOOK_URL",
        "custom": "CUSTOM_WEBHOOK_URL",
    }
    env_var = env_map.get(platform, f"{platform.upper()}_WEBHOOK_URL")
    url = os.environ.get(env_var, "")
    if url:
        return [(platform, url)]
    return []


def send_webhook(platform: str, title: str, content: str, version: str = "",
                 dry_run: bool = False) -> list[dict]:
    """发送通告到指定平台 webhook。

    Returns:
        发送结果列表 [{platform, url, status, status_code}, ...]
    """
    urls = _get_webhook_urls(platform)
    results = []

    for plat, url in urls:
        formatter = FORMATTERS.get(plat, _fmt_custom)
        payload = formatter(title, content, version)

        if dry_run:
            results.append({
                "platform": plat, "url": url, "status": "DRY_RUN",
                "payload": payload,
            })
            continue

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/json")

            with urllib.request.urlopen(req, timeout=15) as resp:
                results.append({
                    "platform": plat, "url": url,
                    "status": "OK" if resp.status == 200 else f"HTTP {resp.status}",
                    "status_code": resp.status,
                })
        except urllib.error.HTTPError as e:
            results.append({
                "platform": plat, "url": url,
                "status": f"HTTP {e.code}", "status_code": e.code,
                "error": e.reason,
            })
        except Exception as e:  # codeguard: ignore GOLD_NO_BROAD_EXCEPTION
            results.append({
                "platform": plat, "url": url,
                "status": "FAILED", "error": str(e),
            })

    return results


def get_version_from_git(repo_root: str) -> str:
    """从 git tag 获取当前版本。"""
    try:
        r = subprocess.run(["git", "describe", "--tags", "--abbrev=0"],
                          capture_output=True, text=True, cwd=repo_root,
                          encoding="utf-8", errors="replace", timeout=10)
        return r.stdout.strip() or "unknown"
    except Exception:  # codeguard: ignore GOLD_NO_BROAD_EXCEPTION
        return "unknown"


def load_content(content_arg: str) -> str:
    """加载内容：文件路径或原始文本。"""
    p = Path(content_arg)
    if p.is_file():
        return p.read_text(encoding="utf-8", errors="replace")
    return content_arg


def main():
    parser = argparse.ArgumentParser(description=f"干系人通告 webhook v{VERSION}")
    parser.add_argument("--platform", required=True,
                       choices=["slack", "dingtalk", "feishu", "wecom", "custom", "all"],
                       help="目标平台")
    parser.add_argument("--title", default="版本发布通告", help="通告标题")
    parser.add_argument("--content", help="通告内容（文件路径或原始文本）")
    parser.add_argument("--tech", default="", help="技术版通告（文件路径）")
    parser.add_argument("--biz", default="", help="业务版通告（文件路径）")
    parser.add_argument("--version", default="", help="版本号（默认自动获取）")
    parser.add_argument("--dry-run", action="store_true", help="仅输出 payload，不实际发送")
    parser.add_argument("--path", default=".", help="项目根目录")
    args = parser.parse_args()

    # 确定版本号
    ver = args.version or get_version_from_git(args.path)

    # 确定内容
    if args.tech or args.biz:
        # 双轨模式
        tech_content = load_content(args.tech) if args.tech else ""
        biz_content = load_content(args.biz) if args.biz else ""
        content = f"## 技术版\n\n{tech_content}\n\n## 业务版\n\n{biz_content}"
    elif args.content:
        content = load_content(args.content)
    else:
        content = "（无通告内容——请通过 --content 或 --tech/--biz 提供）"

    results = send_webhook(args.platform, args.title, content, ver, args.dry_run)

    if args.dry_run:
        print("=== DRY RUN ===\n")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        for r in results:
            print(json.dumps(r, ensure_ascii=False, indent=2))  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    else:
        success = sum(1 for r in results if r["status"] == "OK")
        failed = len(results) - success
        print(f"发送完成: {success} 成功 / {failed} 失败")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        for r in results:
            status_icon = "✅" if r["status"] == "OK" else "❌"
            print(f"  {status_icon} {r['platform']}: {r['status']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION

    return 0 if all(r["status"] == "OK" or r["status"] == "DRY_RUN" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())

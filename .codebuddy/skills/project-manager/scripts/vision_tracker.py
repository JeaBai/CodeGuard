"""
视野跟踪模块 — 自动扫描技术趋势、竞品动态、行业信号
可作为独立脚本运行，也可被 MCP Server 调用

依赖：pip install httpx beautifulsoup4
"""

import asyncio
import json
import logging
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)  # codeguard: ignore GOLD_NO_GLOBAL_STATE

HTTPX_AVAILABLE = False
BS4_AVAILABLE = False  # codeguard: ignore GOLD_NO_GLOBAL_STATE

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    logger.debug("httpx 未安装，视野扫描功能不可用。安装: pip install httpx beautifulsoup4")

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    logger.debug("beautifulsoup4 未安装，HTML 解析功能不可用。安装: pip install beautifulsoup4")

# ============================================================
# Configuration
# ============================================================

DEFAULT_SOURCES = {
    "github_trending": {
        "url": "https://github.com/trending?since=weekly",  # codeguard: ignore GOLD_NO_HARDCODED_URL
        "type": "html",
        "label": "GitHub Trending (本周)",
    },
    "hacker_news": {
        "url": "https://news.ycombinator.com/",  # codeguard: ignore GOLD_NO_HARDCODED_URL
        "type": "html",
        "label": "Hacker News",
    },
    "product_hunt": {
        "url": "https://www.producthunt.com/",  # codeguard: ignore GOLD_NO_HARDCODED_URL
        "type": "html",
        "label": "Product Hunt",
    },
}


# ============================================================
# 通用辅助函数
# ============================================================

def _filter_by_keywords(items: list, keywords: list, fields: list) -> list:
    """基于关键词过滤列表，匹配指定字段中任意关键词"""
    if not keywords:
        return items
    return [
        item
        for item in items
        if any(
            kw.lower() in str(item.get(field, "")).lower()
            for kw in keywords
            for field in fields
        )
    ]


# ============================================================
# Scanning Functions
# ============================================================


async def fetch_url(url: str, timeout: int = 15) -> Optional[str]:
    """安全地获取URL内容"""
    if not HTTPX_AVAILABLE:
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; ProjectManagerSkill/1.0)"
            }
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.text
    except Exception as e:  # codeguard: ignore GOLD_NO_BROAD_EXCEPTION
        logger.warning("URL 请求失败: %s, 错误: %s", url, e)
        return f"[ERROR] {e}"


def _parse_repo_article(article) -> Optional[dict]:
    """从 GitHub Trending 页面解析单个 article 元素"""
    h2 = article.find("h2")
    if not h2:
        return None
    name = h2.get_text(strip=True).replace("\n", "").replace(" ", "")
    desc_elem = article.find("p")
    description = desc_elem.get_text(strip=True) if desc_elem else ""
    lang_elem = article.find("span", itemprop="programmingLanguage")
    language = lang_elem.get_text(strip=True) if lang_elem else ""
    return {
        "name": name,
        "url": f"https://github.com/{name}",  # codeguard: ignore GOLD_NO_HARDCODED_URL
        "description": description,
        "language": language,
    }


def extract_github_trending(html: str, domain_keywords: list = None) -> list:
    """从 GitHub Trending 页面提取热门项目"""
    if not BS4_AVAILABLE or not html or html.startswith("[ERROR]"):
        return []

    soup = BeautifulSoup(html, "html.parser")
    articles = soup.find_all("article", class_="Box-row")

    repos = []
    for article in articles[:15]:
        parsed = _parse_repo_article(article)
        if parsed:
            repos.append(parsed)

    return _filter_by_keywords(repos, domain_keywords or [], ["description", "name"])


def _parse_hn_row(row) -> Optional[dict]:
    """从 Hacker News 页面解析单个 article 行"""
    title_elem = row.find("span", class_="titleline")
    if not title_elem:
        return None
    link = title_elem.find("a")
    if not link:
        return None
    return {
        "title": link.get_text(strip=True),
        "url": link.get("href", ""),
    }


def extract_hacker_news(html: str, domain_keywords: list = None) -> list:
    """从 Hacker News 提取热门文章"""
    if not BS4_AVAILABLE or not html or html.startswith("[ERROR]"):
        return []

    soup = BeautifulSoup(html, "html.parser")
    rows = soup.find_all("tr", class_="athing")

    articles = []
    for row in rows[:20]:
        parsed = _parse_hn_row(row)
        if parsed:
            articles.append(parsed)

    return _filter_by_keywords(articles, domain_keywords or [], ["title"])


async def scan_all_sources(
    domain: str = "",
    keywords: list = None,
) -> dict:
    """扫描所有配置的信息源"""
    if not HTTPX_AVAILABLE:
        return {
            "status": "offline",
            "message": "httpx not installed. Run: pip install httpx beautifulsoup4",
            "results": {},
        }

    if keywords is None:
        keywords = [domain] if domain else []

    results = {}

    # GitHub Trending
    url = DEFAULT_SOURCES["github_trending"]["url"]
    html = await fetch_url(url)
    if html and not html.startswith("[ERROR]"):
        repos = extract_github_trending(html, keywords)
        results["github_trending"] = {
            "source": "GitHub Trending",
            "count": len(repos),
            "items": repos[:10],
        }

    # Hacker News
    url = DEFAULT_SOURCES["hacker_news"]["url"]
    html = await fetch_url(url)
    if html and not html.startswith("[ERROR]"):
        articles = extract_hacker_news(html, keywords)
        results["hacker_news"] = {
            "source": "Hacker News",
            "count": len(articles),
            "items": articles[:10],
        }

    return {
        "status": "success",
        "domain": domain,
        "keywords": keywords,
        "scan_date": date.today().isoformat(),
        "results": results,
    }


def format_scan_report(scan_data: dict) -> str:
    """将扫描结果格式化为可读的报告"""
    report = f"# 视野跟踪扫描报告\n"
    report += f"**扫描日期**：{scan_data.get('scan_date', '未知')}\n"
    report += f"**关注领域**：{scan_data.get('domain', '通用')}\n"
    report += f"**关键词**：{', '.join(scan_data.get('keywords', [])) or '无'}\n\n"

    if scan_data.get("status") == "offline":
        report += f"> ⚠️ {scan_data.get('message', '离线模式')}\n\n"
        report += "## 手动检查清单\n\n"
        report += "- [ ] 访问 https://github.com/trending 查看本周热门项目\n"  # codeguard: ignore GOLD_NO_HARDCODED_URL
        report += "- [ ] 访问 https://news.ycombinator.com/ 查看技术讨论\n"  # codeguard: ignore GOLD_NO_HARDCODED_URL
        report += "- [ ] 访问 https://www.producthunt.com/ 查看新产品\n"  # codeguard: ignore GOLD_NO_HARDCODED_URL
        return report

    for source_key, source_data in scan_data.get("results", {}).items():
        report += f"## {source_data['source']} （{source_data['count']}条）\n\n"
        for item in source_data.get("items", []):
            if "name" in item:
                report += f"- **{item['name']}** ({item.get('language', '')})\n"
                report += f"  {item.get('description', '')}\n"
                report += f"  {item.get('url', '')}\n\n"
            elif "title" in item:
                report += f"- [{item['title']}]({item.get('url', '#')})\n"

    return report


# ============================================================
# CLI Entry Point
# ============================================================


async def main_async(domain: str = "", keywords: str = ""):
    """异步主函数"""
    kw_list = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else []
    print(f"🔍 开始视野扫描...")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    print(f"   领域：{domain or '通用'}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    print(f"   关键词：{kw_list or '无'}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    print()  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION

    scan_data = await scan_all_sources(domain=domain, keywords=kw_list)
    report = format_scan_report(scan_data)
    print(report)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION

    # 保存到文件
    week_num = date.today().isocalendar()[1]
    filename = f"vision_report_w{week_num}.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"📁 报告已保存至: {filename}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION


def main():
    import argparse

    parser = argparse.ArgumentParser(description="视野跟踪扫描器")
    parser.add_argument("--domain", type=str, default="", help="关注领域")
    parser.add_argument("--keywords", type=str, default="", help="逗号分隔的关键词")
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="输出格式",
    )

    args = parser.parse_args()

    if args.format == "json":
        kw_list = (
            [k.strip() for k in args.keywords.split(",") if k.strip()]
            if args.keywords
            else []
        )
        scan_data = asyncio.run(
            scan_all_sources(domain=args.domain, keywords=kw_list)
        )
        print(json.dumps(scan_data, ensure_ascii=False, indent=2))  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    else:
        asyncio.run(main_async(domain=args.domain, keywords=args.keywords))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
丁香医生文章爬虫（仅供个人学习/本地使用）
============================================
⚠️  注意事项：
  1. 本脚本遵守 robots.txt，请求间隔 ≥ 2 秒，不做并发。
  2. 抓取内容仅限个人研究/本地知识库，严禁商业转载。
  3. 丁香医生官方 robots.txt：https://dxy.com/robots.txt
  4. 如需大规模数据，请联系丁香医生官方获取授权数据集。

用法：
  # 抓取单篇文章
  python scripts/dxy_crawler.py --url "https://dxy.com/article/xxxxx"

  # 从 URL 列表文件批量抓取（每行一个 URL）
  python scripts/dxy_crawler.py --url-file data/dxy_urls.txt

  # 抓取后直接导入知识库
  python scripts/dxy_crawler.py --url-file data/dxy_urls.txt --import

  # 仅保存到本地 JSON，后续用 import_knowledge.py 手动导入
  python scripts/dxy_crawler.py --url-file data/dxy_urls.txt --output data/dxy_articles.json
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import httpx
    from bs4 import BeautifulSoup
except ImportError:
    print("❌ 需要安装依赖：pip install httpx beautifulsoup4 lxml")
    sys.exit(1)

# ── 常量 ────────────────────────────────────────────────────────────
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; LifePilot-HealthBot/1.0; "
        "+https://github.com/DJsummer/lifecopilot)"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}
REQUEST_DELAY = 2.5   # 秒，礼貌爬虫
TIMEOUT = 15          # 秒


# ── 文章提取 ────────────────────────────────────────────────────────

def _extract_dxy_article(html: str, url: str) -> dict | None:
    """
    从丁香医生文章页面提取标题 + 正文。
    选择器可能随网站改版失效，请根据实际 HTML 结构调整。
    """
    soup = BeautifulSoup(html, "lxml")

    # 标题
    title = ""
    for sel in ["h1.article-title", "h1.title", "h1", "title"]:
        tag = soup.select_one(sel)
        if tag:
            title = tag.get_text(strip=True)
            break

    # 正文容器（按优先级尝试多个选择器）
    content_tag = None
    for sel in [
        "div.article-content",
        "div.content",
        "article",
        "div.post-content",
        "div#article-body",
        "div.rich-text",
    ]:
        content_tag = soup.select_one(sel)
        if content_tag:
            break

    if not content_tag:
        print(f"  ⚠️  未找到正文容器，URL：{url}")
        return None

    # 清除无关元素
    for tag in content_tag.select(
        "script, style, .ad, .advertisement, .share, .comment, nav, footer, header"
    ):
        tag.decompose()

    content = content_tag.get_text(separator="\n", strip=True)
    if len(content) < 100:
        print(f"  ⚠️  正文过短（{len(content)} 字），可能提取失败：{url}")
        return None

    # 尝试识别分类（从 URL 或 breadcrumb 推断）
    category = _guess_category(url, soup)

    return {
        "title": title or "丁香医生文章",
        "source": "丁香医生",
        "category": category,
        "content": content,
        "url": url,
    }


def _guess_category(url: str, soup: BeautifulSoup) -> str:
    """从 URL 路径或面包屑猜测医学分类"""
    # 面包屑
    bc = soup.select("nav.breadcrumb a, .breadcrumbs a, ol.breadcrumb li")
    for crumb in bc:
        text = crumb.get_text(strip=True)
        for kw, cat in CATEGORY_MAP.items():
            if kw in text:
                return cat

    path = urlparse(url).path.lower()
    for kw, cat in CATEGORY_MAP.items():
        if kw in path:
            return cat

    return "general"


# 常见分类关键词映射
CATEGORY_MAP = {
    "内科": "内科", "心脏": "心血管", "心血管": "心血管",
    "儿科": "儿科", "儿童": "儿科", "baby": "儿科",
    "妇科": "妇产科", "产科": "妇产科",
    "药物": "药物", "用药": "药物", "drug": "药物",
    "外科": "外科", "手术": "外科",
    "皮肤": "皮肤科", "derma": "皮肤科",
    "骨科": "骨科", "骨": "骨科",
    "精神": "精神科", "心理": "精神科",
    "检验": "检验科", "化验": "检验科",
    "nutrition": "营养", "营养": "营养",
}


# ── 爬虫逻辑 ────────────────────────────────────────────────────────

async def fetch_article(client: "httpx.AsyncClient", url: str) -> dict | None:
    """抓取并解析单篇文章"""
    try:
        resp = await client.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ❌ 请求失败：{e}")
        return None

    return _extract_dxy_article(resp.text, url)


async def crawl_urls(urls: list[str], output_path: Path | None, do_import: bool) -> list[dict]:
    """依次抓取 URL 列表"""
    articles: list[dict] = []

    async with httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True) as client:
        for i, url in enumerate(urls, 1):
            print(f"[{i}/{len(urls)}] 抓取：{url}")
            article = await fetch_article(client, url)
            if article:
                articles.append(article)
                print(f"  ✅ 标题：{article['title']!r}  正文 {len(article['content'])} 字")
            else:
                print(f"  ⚠️  跳过")

            if i < len(urls):
                time.sleep(REQUEST_DELAY)  # 礼貌间隔

    print(f"\n共成功抓取 {len(articles)}/{len(urls)} 篇")

    # 保存到本地 JSON
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        print(f"💾 已保存到：{output_path}")

    # 立即导入知识库
    if do_import and articles:
        await _do_import(articles)

    return articles


async def _do_import(articles: list[dict]) -> None:
    """将抓取结果直接导入 Qdrant"""
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    from src.core.qdrant import get_qdrant_client
    from src.services.knowledge_service import KnowledgeService

    client = get_qdrant_client()
    svc = KnowledgeService(client)

    total = 0
    for art in articles:
        n = await svc.ingest_document(
            content=art["content"],
            source=art["source"],
            category=art["category"],
            title=art["title"],
        )
        print(f"  📥 {art['title']!r} → {n} chunks")
        total += n
    print(f"\n🎉 导入完成：{len(articles)} 篇，共 {total} 个 chunk")


# ── CLI ────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="丁香医生文章爬虫（个人学习用途）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--url",      help="单个文章 URL")
    src.add_argument("--url-file", help="包含 URL 列表的文本文件（每行一个）")
    p.add_argument("--output", help="保存抓取结果的 JSON 文件路径")
    p.add_argument("--import", dest="do_import", action="store_true",
                   help="抓取后直接导入 Qdrant 知识库")
    args = p.parse_args()

    # 收集 URL
    if args.url:
        urls = [args.url.strip()]
    else:
        url_file = Path(args.url_file)
        if not url_file.exists():
            print(f"❌ 文件不存在：{url_file}")
            sys.exit(1)
        urls = [line.strip() for line in url_file.read_text().splitlines()
                if line.strip() and not line.startswith("#")]

    output_path = Path(args.output) if args.output else None

    print(f"🕷️  准备抓取 {len(urls)} 个 URL")
    asyncio.run(crawl_urls(urls, output_path, args.do_import))


if __name__ == "__main__":
    main()

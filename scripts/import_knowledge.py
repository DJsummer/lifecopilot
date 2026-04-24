#!/usr/bin/env python3
"""
健康知识库批量导入工具
=====================
支持将本地文件（TXT / Markdown / JSON / PDF）批量导入到 Qdrant 向量数据库。

用法：
  # 导入单个文本/Markdown 文件
  python scripts/import_knowledge.py --file docs/高血压指南.md \
      --source "丁香医生" --category "内科" --title "高血压预防与治疗"

  # 导入整个目录（自动遍历 .txt / .md 文件）
  python scripts/import_knowledge.py --dir data/medical_docs/ \
      --source "丁香医生" --category "内科"

  # 通过 JSON 批量文件导入（推荐用于大批量）
  python scripts/import_knowledge.py --json data/dxy_articles.json

  # 导入 PDF 文件（需安装 pdfplumber：pip install pdfplumber）
  python scripts/import_knowledge.py --file 检验单说明.pdf \
      --source "检验手册" --category "检验科"

JSON 批量格式（data/dxy_articles.json）：
  [
    {
      "title": "高血压的预防与治疗",
      "source": "丁香医生",
      "category": "内科",
      "content": "文章正文..."
    },
    ...
  ]
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# ── 项目根目录加入 sys.path ──────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 环境变量：优先读取 .env，其次 .env.local
from dotenv import load_dotenv
for env_file in [ROOT / ".env", ROOT / ".env.local"]:
    if env_file.exists():
        load_dotenv(env_file)
        break

from src.core.config import settings
from src.core.qdrant import get_qdrant_client
from src.services.knowledge_service import KnowledgeService


# ────────────────────────────────────────────────────────────────────
# 文件读取工具
# ────────────────────────────────────────────────────────────────────

def read_text_file(path: Path) -> str:
    """读取 TXT / Markdown 文件"""
    return path.read_text(encoding="utf-8")


def read_pdf_file(path: Path) -> str:
    """读取 PDF 文件（需要 pdfplumber）"""
    try:
        import pdfplumber
    except ImportError:
        print("❌ 读取 PDF 需要安装 pdfplumber：pip install pdfplumber")
        sys.exit(1)
    text_parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
    return "\n".join(text_parts)


def read_file(path: Path) -> str:
    """根据文件扩展名自动选择读取方式"""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return read_pdf_file(path)
    else:
        return read_text_file(path)


# ────────────────────────────────────────────────────────────────────
# 导入逻辑
# ────────────────────────────────────────────────────────────────────

async def ingest_one(
    svc: KnowledgeService,
    content: str,
    source: str,
    category: str,
    title: str,
) -> int:
    """导入单篇文章，返回 chunk 数量"""
    if not content.strip():
        print(f"  ⚠️  内容为空，跳过：{title!r}")
        return 0
    chunks = await svc.ingest_document(
        content=content,
        source=source,
        category=category,
        title=title,
    )
    return chunks


async def import_single_file(args: argparse.Namespace) -> None:
    """--file 模式：导入单个文件"""
    path = Path(args.file)
    if not path.exists():
        print(f"❌ 文件不存在：{path}")
        sys.exit(1)

    title = args.title or path.stem
    print(f"\n📄 正在导入：{path.name}")
    print(f"   来源：{args.source}  分类：{args.category}  标题：{title}")

    content = read_file(path)
    client = get_qdrant_client()
    svc = KnowledgeService(client)
    n = await ingest_one(svc, content, args.source, args.category, title)
    print(f"   ✅ 成功入库 {n} 个 chunk")


async def import_directory(args: argparse.Namespace) -> None:
    """--dir 模式：遍历目录导入所有 TXT/MD/PDF 文件"""
    directory = Path(args.dir)
    if not directory.is_dir():
        print(f"❌ 目录不存在：{directory}")
        sys.exit(1)

    suffixes = {".txt", ".md", ".markdown", ".pdf"}
    files = sorted(f for f in directory.rglob("*") if f.suffix.lower() in suffixes)
    if not files:
        print(f"⚠️  目录下没有找到可导入的文件（支持 .txt/.md/.pdf）：{directory}")
        sys.exit(0)

    print(f"\n📂 目录：{directory}")
    print(f"   找到 {len(files)} 个文件，来源：{args.source}  分类：{args.category}\n")

    client = get_qdrant_client()
    svc = KnowledgeService(client)

    total_chunks = 0
    for i, fp in enumerate(files, 1):
        title = args.title or fp.stem
        print(f"[{i}/{len(files)}] {fp.name} → title={title!r}", end="  ")
        content = read_file(fp)
        n = await ingest_one(svc, content, args.source, args.category, title)
        print(f"✅ {n} chunks")
        total_chunks += n

    print(f"\n🎉 完成！共导入 {len(files)} 篇文章，{total_chunks} 个 chunk")


async def import_json(args: argparse.Namespace) -> None:
    """--json 模式：从 JSON 批量文件导入"""
    path = Path(args.json)
    if not path.exists():
        print(f"❌ JSON 文件不存在：{path}")
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        articles = json.load(f)

    if not isinstance(articles, list):
        print("❌ JSON 格式错误：根节点应为数组 []")
        sys.exit(1)

    print(f"\n📋 JSON 文件：{path.name}")
    print(f"   共 {len(articles)} 篇文章\n")

    client = get_qdrant_client()
    svc = KnowledgeService(client)

    total_chunks = 0
    errors = 0
    for i, article in enumerate(articles, 1):
        title    = article.get("title", f"文章{i}")
        source   = article.get("source", args.source or "未知来源")
        category = article.get("category", args.category or "general")
        content  = article.get("content", "")

        if not source and not args.source:
            print(f"[{i}] ⚠️  缺少 source 字段，使用 '未知来源'")

        print(f"[{i}/{len(articles)}] {title!r} [{source}/{category}]", end="  ")
        try:
            n = await ingest_one(svc, content, source, category, title)
            print(f"✅ {n} chunks")
            total_chunks += n
        except Exception as e:
            print(f"❌ 失败：{e}")
            errors += 1

    print(f"\n🎉 完成！成功 {len(articles)-errors} 篇，失败 {errors} 篇，共 {total_chunks} 个 chunk")


# ────────────────────────────────────────────────────────────────────
# CLI 入口
# ────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="LifePilot 健康知识库批量导入工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--file", help="单个文件路径（.txt .md .pdf）")
    mode.add_argument("--dir",  help="目录路径，递归导入所有 .txt/.md/.pdf")
    mode.add_argument("--json", help="JSON 批量文件路径")

    p.add_argument("--source",   default="",        help="来源标识，如 '丁香医生'（JSON 模式下可被条目覆盖）")
    p.add_argument("--category", default="general", help="分类，如 '内科' '儿科' '药物'")
    p.add_argument("--title",    default="",        help="标题（--file/--dir 模式，默认取文件名）")

    # Qdrant 连接覆盖（可选，优先级高于 .env）
    p.add_argument("--qdrant-host", default=None, help="Qdrant 主机（默认使用 .env 配置）")
    p.add_argument("--qdrant-port", type=int, default=None, help="Qdrant 端口")
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # 覆盖 Qdrant 连接配置
    if args.qdrant_host:
        os.environ["QDRANT_HOST"] = args.qdrant_host
    if args.qdrant_port:
        os.environ["QDRANT_PORT"] = str(args.qdrant_port)

    print("🔗 Qdrant:", settings.QDRANT_HOST, ":", settings.QDRANT_PORT)
    print("🤖 Embedding model:", settings.EMBEDDING_MODEL)

    if args.file:
        asyncio.run(import_single_file(args))
    elif args.dir:
        asyncio.run(import_directory(args))
    else:
        asyncio.run(import_json(args))


if __name__ == "__main__":
    main()

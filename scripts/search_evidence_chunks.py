from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.session import AsyncSessionLocal
from app.rag.retriever import EvidenceRetriever


async def main() -> None:
    parser = argparse.ArgumentParser(description="Search embedded RAG evidence chunks.")
    parser.add_argument("query")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--regulatory", action="store_true")
    parser.add_argument("--privacy", action="store_true")
    parser.add_argument("--advertising", action="store_true")
    args = parser.parse_args()

    retriever = EvidenceRetriever()
    async with AsyncSessionLocal() as session:
        results = await retriever.search(
            session,
            args.query,
            top_k=args.top_k,
            tag_regulatory=True if args.regulatory else None,
            tag_privacy=True if args.privacy else None,
            tag_advertising=True if args.advertising else None,
        )

    for index, result in enumerate(results, start=1):
        print(f"[{index}] {result.similarity:.4f} {result.document_id} {result.section_id or ''}")
        print(f"    {result.title}")
        print(f"    {result.chunk_text[:240].replace(chr(10), ' ')}")


if __name__ == "__main__":
    asyncio.run(main())

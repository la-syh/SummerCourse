"""评测每个目标页面的多条查询，并按最佳排名计算 MRR@20。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from urllib.parse import parse_qsl, urlencode, urlsplit

if __package__:
    from .search_engine import evaluate, search_service
else:
    from search_engine import evaluate, search_service


def canonical_url(url: str) -> str:
    """忽略协议和片段，保留规范化主机、路径及查询参数。"""
    parts = urlsplit(str(url or "").strip())
    host = (parts.hostname or "").casefold()
    port = parts.port
    if port and port not in {80, 443}:
        host = f"{host}:{port}"
    path = parts.path.rstrip("/") or "/"
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return host + path + (f"?{query}" if query else "")


def target_rank(target_url: str, returned_urls: list[str]) -> int | None:
    target = canonical_url(target_url)
    for rank, url in enumerate(returned_urls[:20], start=1):
        if canonical_url(url) == target:
            return rank
    return None


def load_pages(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as reader:
        data = json.load(reader)
    pages = data.get("pages") if isinstance(data, dict) else None
    if not isinstance(pages, list) or not pages:
        raise ValueError("JSON 必须包含非空 pages 数组")
    for index, page in enumerate(pages, start=1):
        if not isinstance(page, dict):
            raise ValueError(f"pages[{index - 1}] 不是对象")
        queries = page.get("queries")
        if (
            not isinstance(page.get("url"), str)
            or not isinstance(queries, list)
            or len(queries) != 4
            or not all(isinstance(query, str) and query.strip() for query in queries)
        ):
            raise ValueError(f"第 {index} 页必须包含 URL 和恰好四条非空查询")
    return pages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--mode", default="bm25_hybrid")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    pages = load_pages(args.dataset)
    corpus_urls = {
        canonical_url(url)
        for url in search_service.document_registry.urls()
    }

    # 排除模型和矩阵运算的首次执行开销。
    evaluate(pages[0]["queries"][0], mode=args.mode)

    best_reciprocal_ranks = []
    per_query_reciprocal_ranks = [[] for _ in range(4)]
    latencies_ms = []
    best_ranks: list[int | None] = []

    for page_index, page in enumerate(pages, start=1):
        ranks = []
        for query_index, query in enumerate(page["queries"]):
            started = time.monotonic()
            urls = evaluate(query, mode=args.mode)[:20]
            latencies_ms.append((time.monotonic() - started) * 1000)
            rank = target_rank(page["url"], urls)
            ranks.append(rank)
            per_query_reciprocal_ranks[query_index].append(
                1.0 / rank if rank is not None else 0.0
            )

        hits = [rank for rank in ranks if rank is not None]
        best_rank = min(hits) if hits else None
        best_ranks.append(best_rank)
        best_reciprocal_ranks.append(
            1.0 / best_rank if best_rank is not None else 0.0
        )
        if args.verbose:
            print(
                f"[{page_index:03d}/{len(pages)}] "
                f"best={best_rank or '-':>2} ranks={ranks} "
                f"{page['title']}"
            )
        elif page_index % 10 == 0 or page_index == len(pages):
            print(f"Evaluated {page_index}/{len(pages)} pages")

    page_count = len(pages)
    covered_targets = sum(
        canonical_url(page["url"]) in corpus_urls
        for page in pages
    )
    best_mrr = sum(best_reciprocal_ranks) / page_count
    average_latency = sum(latencies_ms) / len(latencies_ms)

    print("\n=== BEST-OF-4 RETRIEVAL EVALUATION ===")
    print(f"Mode: {args.mode}")
    print(f"Pages: {page_count}; queries: {len(latencies_ms)}")
    print(f"Targets present in corpus: {covered_targets}/{page_count}")
    print(f"Best-of-4 MRR@20: {best_mrr:.6f}")
    for cutoff in (1, 5, 10, 20):
        hits = sum(
            rank is not None and rank <= cutoff
            for rank in best_ranks
        )
        print(f"Best-of-4 Hit@{cutoff}: {hits / page_count:.3%} ({hits}/{page_count})")
    for index, reciprocal_ranks in enumerate(
        per_query_reciprocal_ranks,
        start=1,
    ):
        print(
            f"Query {index} MRR@20: "
            f"{sum(reciprocal_ranks) / page_count:.6f}"
        )
    print(f"Average latency: {average_latency:.3f} ms/query")


if __name__ == "__main__":
    main()

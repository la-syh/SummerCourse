"""在同一组 debug 查询上比较五种检索方法。"""

import getpass
import time

if __package__:
    from .client import login, send_ans
    from .search_engine import evaluate
else:
    from client import login, send_ans
    from search_engine import evaluate


METHODS = (
    ("tfidf", "TF-IDF"),
    ("bm25", "BM25"),
    ("embedding", "Embedding"),
    ("tfidf_hybrid", "TF-IDF + Embedding"),
    ("bm25_hybrid", "BM25 + Embedding"),
)


def main() -> None:
    idx = input("idx: ").strip()
    passwd = getpass.getpass("passwd (None for debug mode): ")
    queries = login(idx, passwd)

    print("method\tMRR@20\tlatency(ms)")
    for mode, label in METHODS:
        # 排除 PyTorch / tokenizer 首次执行的一次性预热开销。
        evaluate(queries[0], mode=mode)

        all_urls = []
        elapsed_milliseconds = []
        for query in queries:
            started = time.monotonic()
            all_urls.append(evaluate(query, mode=mode)[:20])
            elapsed_milliseconds.append(
                round((time.monotonic() - started) * 1000, 3)
            )

        server_mode, mrr, latency = send_ans(
            idx,
            passwd,
            all_urls,
            elapsed_milliseconds,
        )
        print(f"{label}\t{mrr:.6f}\t{latency:.3f}\t[{server_mode}]")


if __name__ == "__main__":
    main()

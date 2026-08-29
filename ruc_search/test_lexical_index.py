"""TF-IDF / BM25 词法评分测试。"""

from math import log
import unittest

from .lexical_index import LexicalIndex


def make_index() -> LexicalIndex:
    index = LexicalIndex.__new__(LexicalIndex)
    index.stopwords = set()
    index.document_count = 2
    index.doc_lengths = [1.0, 1.0]
    index.bm25_doc_lengths = [100.0, 1000.0]
    index.average_bm25_doc_length = 550.0
    index.terms = {
        "目标": {
            "df": 2,
            "idf": 1.0,
            "bm25_idf": log(1.0 + 0.5 / 2.5),
            "postings": [[0, 3], [1, 3]],
        }
    }
    return index


class LexicalIndexTest(unittest.TestCase):
    def test_bm25_penalizes_long_documents(self):
        rows = make_index().search_bm25_with_scores("目标", topk=2)
        self.assertEqual([doc_id for doc_id, _ in rows], [0, 1])
        self.assertGreater(rows[0][1], rows[1][1])

    def test_method_dispatch(self):
        index = make_index()
        self.assertEqual(
            index.search_with_scores("目标", method="bm25"),
            index.search_bm25_with_scores("目标"),
        )
        self.assertEqual(
            index.search_with_scores("目标", method="tfidf"),
            index.search_tfidf_with_scores("目标"),
        )

    def test_invalid_method_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "method"):
            make_index().search_with_scores("目标", method="unknown")


if __name__ == "__main__":
    unittest.main()

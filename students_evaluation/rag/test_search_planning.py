"""RAG 子查询规划与结果合并测试。"""

import unittest
from unittest.mock import patch

from . import search_engine


class SearchPlanningTest(unittest.TestCase):
    def test_company_entities_are_searched_separately(self):
        terms = ["快手", "参访", "华为", "腾讯", "排序", "公司", "企业"]
        with patch.object(
            search_engine,
            "extract_query_terms",
            return_value=terms,
        ):
            queries = search_engine.build_search_queries(
                "按照企业参访站次，将华为、快手和腾讯公司排序"
            )

        self.assertIn("华为 公司 企业参访", queries)
        self.assertIn("快手 公司 企业参访", queries)
        self.assertIn("腾讯 公司 企业参访", queries)
        self.assertFalse(
            any(
                query.startswith("高瓴人工智能学院 手和腾讯公司")
                for query in queries
            )
        )

    def test_years_are_searched_separately(self):
        terms = ["教室", "规模", "2019", "2021", "2020", "活动"]
        with patch.object(
            search_engine,
            "extract_query_terms",
            return_value=terms,
        ):
            queries = search_engine.build_search_queries(
                "比较2019年、2020年和2021年活动使用的教室规模"
            )

        self.assertIn("2019 教室 规模 活动", queries)
        self.assertIn("2020 教室 规模 活动", queries)
        self.assertIn("2021 教室 规模 活动", queries)

    def test_results_from_subqueries_are_interleaved(self):
        def fake_search(query, top_k):
            return [
                {
                    "url": f"https://example.com/{query}/{rank}",
                    "title": f"{query}-{rank}",
                }
                for rank in range(top_k)
            ]

        with (
            patch.object(
                search_engine,
                "build_search_queries",
                return_value=["query-a", "query-b", "query-c"],
            ),
            patch.object(search_engine, "search", side_effect=fake_search),
        ):
            results = search_engine.multi_search("普通问题", top_k=2)

        self.assertEqual(
            [result["title"] for result in results[:6]],
            [
                "query-a-0", "query-b-0", "query-c-0",
                "query-a-1", "query-b-1", "query-c-1",
            ],
        )
        self.assertEqual(results[1]["matched_query"], "query-b")


if __name__ == "__main__":
    unittest.main()

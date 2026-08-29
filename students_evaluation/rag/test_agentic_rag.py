"""迭代检索控制器的无网络测试。"""

import unittest

if __package__:
    from .agentic_rag import run_agentic_rag
else:
    from agentic_rag import run_agentic_rag


def integrate(results, **_kwargs):
    return "\n".join(item["title"] for item in results)


class AgenticRagTest(unittest.TestCase):
    def test_three_rounds_and_source_interleaving(self):
        searched = []
        responses = iter([
            '```json\n{"action":"search","query":"教师个人主页"}\n```',
            '{"action":"search","query":"教师 教授课程"}',
            "最终课程答案",
        ])

        def search(query, top_k):
            searched.append((query, top_k))
            number = len(searched)
            return [
                {
                    "url": f"https://example.com/{number}/{index}",
                    "title": f"第{number}轮-{index}",
                }
                for index in range(5)
            ]

        def model(**kwargs):
            self.assertIn("max_tokens", kwargs)
            return next(responses)

        answer, sources = run_agentic_rag(
            "原始问题",
            search,
            integrate,
            model,
        )

        self.assertEqual(answer, "最终课程答案")
        self.assertEqual(
            [item[0] for item in searched],
            ["原始问题", "教师个人主页", "教师 教授课程"],
        )
        self.assertEqual(len(sources), 10)
        self.assertEqual(
            [item["title"] for item in sources[:3]],
            ["第3轮-0", "第2轮-0", "第1轮-0"],
        )

    def test_early_answer_stops_searching(self):
        searched = []

        def search(query, top_k):
            searched.append(query)
            return [{"url": "https://example.com", "title": "已有证据"}]

        def model(**_kwargs):
            return '{"action":"answer","answer":"提前得到答案"}'

        answer, _ = run_agentic_rag(
            "问题",
            search,
            integrate,
            model,
        )

        self.assertEqual(answer, "提前得到答案")
        self.assertEqual(searched, ["问题"])

    def test_repeated_query_forces_answer_without_research(self):
        searched = []
        responses = iter([
            '{"action":"search","query":"问题"}',
            "基于现有材料的答案",
        ])

        def search(query, top_k):
            searched.append(query)
            return [{"url": "https://example.com", "title": "材料"}]

        def model(**_kwargs):
            return next(responses)

        answer, _ = run_agentic_rag(
            "问题",
            search,
            integrate,
            model,
        )

        self.assertEqual(answer, "基于现有材料的答案")
        self.assertEqual(searched, ["问题"])

    def test_empty_planner_response_falls_back_to_answer(self):
        searched = []
        calls = 0

        def search(query, top_k):
            searched.append(query)
            return [{"url": "https://example.com", "title": "有效材料"}]

        def model(**_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("大模型连续返回空答案")
            return "降级后的最终答案"

        answer, _ = run_agentic_rag(
            "问题",
            search,
            integrate,
            model,
        )

        self.assertEqual(answer, "降级后的最终答案")
        self.assertEqual(searched, ["问题"])
        self.assertEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()

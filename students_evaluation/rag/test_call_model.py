"""大模型调用封装的无网络测试。"""

import importlib
import os
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch


call_model_module = importlib.import_module(
    "students_evaluation.rag.call_model"
)


def response(content, finish_reason="stop"):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason=finish_reason,
            )
        ]
    )


class CallModelTest(unittest.TestCase):
    def test_single_attempt_receives_almost_full_timeout_budget(self):
        client = MagicMock()
        client.chat.completions.create.return_value = response("答案")

        with (
            patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}),
            patch.object(
                call_model_module,
                "OpenAI",
                return_value=client,
            ) as openai,
        ):
            call_model_module.call_model(
                "测试问题",
                timeout=60.0,
                attempts=1,
            )

        self.assertEqual(openai.call_args.kwargs["timeout"], 55.0)

    def test_thinking_mode_is_enabled(self):
        client = MagicMock()
        client.chat.completions.create.return_value = response("简短答案")

        with (
            patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}),
            patch.object(call_model_module, "OpenAI", return_value=client),
        ):
            call_model_module.call_model("测试问题")

        self.assertEqual(
            client.chat.completions.create.call_args.kwargs["extra_body"],
            {"thinking": {"type": "enabled"}},
        )
        self.assertEqual(
            client.chat.completions.create.call_args.kwargs[
                "reasoning_effort"
            ],
            "low",
        )

    def test_empty_content_is_retried(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            response(None, "length"),
            response("第二次返回答案"),
        ]

        with (
            patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}),
            patch.object(call_model_module, "OpenAI", return_value=client),
            patch.object(call_model_module.time, "sleep"),
        ):
            answer = call_model_module.call_model(
                "测试问题",
                max_tokens=1024,
            )

        self.assertEqual(answer, "第二次返回答案")
        self.assertEqual(client.chat.completions.create.call_count, 2)

    def test_repeated_empty_content_has_diagnostic_message(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            response(None, "length"),
            response("", "length"),
        ]

        with (
            patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}),
            patch.object(call_model_module, "OpenAI", return_value=client),
            patch.object(call_model_module.time, "sleep"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                r"finish_reason=length, max_tokens=1024",
            ):
                call_model_module.call_model(
                    "测试问题",
                    max_tokens=1024,
                )


if __name__ == "__main__":
    unittest.main()

"""离线模型加载器测试。"""

import os
import unittest
from unittest.mock import patch

from . import offline_model


class OfflineModelTest(unittest.TestCase):
    def test_offline_environment_is_forced(self):
        for name in (
            "HF_HUB_OFFLINE",
            "TRANSFORMERS_OFFLINE",
            "HF_DATASETS_OFFLINE",
            "HF_HUB_DISABLE_TELEMETRY",
        ):
            self.assertEqual(os.environ.get(name), "1")

    def test_loader_only_uses_local_files(self):
        sentinel = object()
        with patch.object(
            offline_model,
            "SentenceTransformer",
            return_value=sentinel,
        ) as constructor:
            loaded = offline_model.load_embedding_model("local-model")

        self.assertIs(loaded, sentinel)
        constructor.assert_called_once_with(
            "local-model",
            local_files_only=True,
        )

    def test_missing_cache_has_clear_error(self):
        with patch.object(
            offline_model,
            "SentenceTransformer",
            side_effect=OSError("cache miss"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "离线模式下无法从本地缓存加载模型",
            ):
                offline_model.load_embedding_model("missing-model")


if __name__ == "__main__":
    unittest.main()

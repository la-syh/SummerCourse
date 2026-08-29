"""只从本地 Hugging Face 缓存加载检索模型。"""

from __future__ import annotations

import os


# 必须在导入 sentence_transformers / transformers / huggingface_hub 前设置。
# 这里使用强制赋值，避免外部环境中的 "0" 意外开启网络访问。
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

from sentence_transformers import SentenceTransformer


MODEL_NAME = "BAAI/bge-base-zh-v1.5"


def load_embedding_model(
    model_name: str = MODEL_NAME,
) -> SentenceTransformer:
    """加载本地模型；缓存缺失时立即失败，绝不尝试联网。"""
    try:
        return SentenceTransformer(
            model_name,
            local_files_only=True,
        )
    except Exception as exc:
        raise RuntimeError(
            f"离线模式下无法从本地缓存加载模型 {model_name!r}。"
            "请在测试前联网下载并缓存该模型。"
        ) from exc

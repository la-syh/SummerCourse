import json
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

from .page_content import extract_page_content

'''
chunk 0: tokens   0 ~ 383
chunk 1: tokens 320 ~ 703
chunk 2: tokens 640 ~ 1023

{
'chunk_id': 全局唯一编号
'doc_id': 对应网页编号
'url': 所属页面
'title': 页面标题
'chunk_index': 是对应页面中的第几个 chunk
'token_start': 在正文中的 token 起始位置
'token_end': 在正文中的 token 末尾位置
'char_start': 在原始字符串的字符起点
'char_end': 在原始字符串的字符终点
'text': chunk 原文
}
'''

def split_text_to_chunks( 
    text: str,
    tokenizer,
    chunk_tokens: int = 384,
    overlap_tokens: int = 64,
):
    encoded = tokenizer(
        text,
        add_special_tokens=False,
        return_offsets_mapping=True,
        truncation=False,
    )

    token_ids = encoded["input_ids"]
    offsets = encoded["offset_mapping"]
    step = chunk_tokens - overlap_tokens
    chunks = []
    for chunk_index, start in enumerate(range(0, len(token_ids), step)):
        end = min(start + chunk_tokens, len(token_ids))
        char_start, char_end = offsets[start][0], offsets[end - 1][1]
        chunk_text = text[char_start:char_end].strip()

        if chunk_text:
            chunks.append({
                'chunk_index': chunk_index,
                'token_start':start,
                'token_end':end,
                'char_start': char_start,
                'char_end': char_end,
                'text':chunk_text
            })
        if end == len(token_ids):
            break
    
    return chunks


def build_embedding(
        project_root: Path,
        doc_id_path: Path,
        chunk_path: Path,
        embedding_path: Path,
        model: SentenceTransformer,
        chunk_tokens: int = 384,
        overlap_tokens: int = 64,):
    all_chunks = []
    chunk_id = 0

    with doc_id_path.open(encoding="utf-8") as reader:
        for line in reader:
            document = json.loads(line)
            title, content = extract_page_content(
                project_root / document["file"]
            )
            chunks = split_text_to_chunks(
                content,
                model.tokenizer,
                chunk_tokens,
                overlap_tokens,
            )
            for chunk in chunks:
                all_chunks.append({
                    "chunk_id": chunk_id,
                    "doc_id": document["docID"],
                    "url": document["url"],
                    "title": title,
                    **chunk,
                })
                chunk_id += 1

    with chunk_path.open("w", encoding="utf-8") as chunk_writer:
        for chunk in all_chunks:
            json.dump(chunk, chunk_writer, ensure_ascii=False)
            chunk_writer.write("\n")

    embeddings = model.encode(
        [chunk["text"] for chunk in all_chunks],
        batch_size=32,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    np.save(embedding_path, embeddings.astype(np.float32))

    print(f"chunks: {len(all_chunks)}")
    print(f"embedding shape: {embeddings.shape}")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    doc_id_path = project_root / 'data' / 'docID.jsonl'
    chunk_path = project_root / 'data' / 'chunks.jsonl'
    embedding_path = project_root / 'data' / 'chunk_embeddings.npy'
    MODEL_NAME = "BAAI/bge-small-zh-v1.5"
    model = SentenceTransformer(MODEL_NAME)

    chunk_tokens = 384
    overlap_tokens = 64
    build_embedding(project_root=project_root,
                    doc_id_path=doc_id_path,
                    chunk_path=chunk_path, 
                    embedding_path=embedding_path,
                    model=model,
                    chunk_tokens=chunk_tokens, 
                    overlap_tokens=overlap_tokens)

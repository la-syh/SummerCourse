import json
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

from info import DocumentRegistry, PageInfoStore

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

class Embeddings:
    def __init__(self, 
                document_registry: DocumentRegistry,
                page_info_store: PageInfoStore,
                chunk_path: Path,
                embedding_path: Path,
                model: SentenceTransformer,
                chunk_tokens: int = 384,
                overlap_tokens: int = 64,
                remake: bool = False):
        self.document_registry = document_registry
        self.page_info_store = page_info_store
        self.chunk_path = Path(chunk_path)
        self.embedding_path = Path(embedding_path)
        self.model, self.chunk_tokens, self.overlap_tokens = model, chunk_tokens, overlap_tokens

        if remake or not self.chunk_path.exists():
            self.build_chunks()
        else:
            self.load_chunks()
        if remake or not self.embedding_path.exists():
            self.build_embedding()
        else:
            self.load_embeddings()
    def build_chunks(self, ):
        self.all_chunks = []
        chunk_id = 0

        for document in self.document_registry:
            page_info = self.page_info_store.get(document.url, cache=False)
            title = page_info.title if page_info else ""
            content = page_info.content if page_info else ""
            chunks = split_text_to_chunks(
                content,
                self.model.tokenizer,
                self.chunk_tokens,
                self.overlap_tokens,
            )
            for chunk in chunks:
                self.all_chunks.append({
                    "chunk_id": chunk_id,
                    "doc_id": document.doc_id,
                    "url": document.url,
                    "title": title,
                    **chunk,
                })
                chunk_id += 1

        with self.chunk_path.open("w", encoding="utf-8") as chunk_writer:
            for chunk in self.all_chunks:
                json.dump(chunk, chunk_writer, ensure_ascii=False)
                chunk_writer.write("\n")
    def load_chunks(self):
        if not self.chunk_path.exists():
            raise FileExistsError(self.chunk_path)

        with self.chunk_path.open('r', encoding='utf-8') as chunk_reader:
            self.all_chunks = [json.loads(line) for line in chunk_reader]

    def build_embedding(self):
        self.embeddings = self.model.encode(
            [chunk["text"] for chunk in self.all_chunks],
            batch_size=32,
            show_progress_bar=True,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        np.save(self.embedding_path, self.embeddings.astype(np.float32))

        print(f"chunks: {len(self.all_chunks)}")
        print(f"embedding shape: {self.embeddings.shape}")
    def load_embeddings(self):
        if not self.embedding_path.exists():
            raise FileExistsError(f'{self.embedding_path} 不存在')
        self.embeddings = np.load(self.embedding_path)

if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    doc_id_path = project_root / 'data' / 'docID.jsonl'
    chunk_path = project_root / 'data' / 'chunks.jsonl'
    embedding_path = project_root / 'data' / 'chunk_embeddings.npy'
    MODEL_NAME = "BAAI/bge-small-zh-v1.5"
    model = SentenceTransformer(MODEL_NAME)
    document_registry = DocumentRegistry(project_root, doc_id_path)
    page_info_store = PageInfoStore(document_registry)

    chunk_tokens = 384
    overlap_tokens = 64
    builder = Embeddings(document_registry=document_registry,
                    page_info_store=page_info_store,
                    chunk_path=chunk_path, 
                    embedding_path=embedding_path,
                    model=model,
                    chunk_tokens=chunk_tokens, 
                    overlap_tokens=overlap_tokens,
                    remake = False)

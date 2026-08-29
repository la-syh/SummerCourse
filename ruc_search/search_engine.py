from .embedding_builder import Embeddings
from pathlib import Path
from sentence_transformers import SentenceTransformer
import numpy as np
class search_engine:
    def __init__(self, 
                project_root: Path,
                doc_id_path: Path,
                chunk_path: Path,
                embedding_path: Path,
                model: SentenceTransformer,
                chunk_tokens: int = 384,
                overlap_tokens: int = 64,
                ):
        self.QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
        self.project_root = project_root
        self.doc_id_path, self.chunk_path = doc_id_path, chunk_path
        self.embedding_path = embedding_path
        self.model, self.chunk_tokens, self.overlap_tokens = model, chunk_tokens, overlap_tokens
        self.data = Embeddings(self.project_root, self.doc_id_path, self.chunk_path,
                               self.embedding_path, self.model, self.chunk_tokens, self.overlap_tokens,
                               remake=False)
        
        
    def search(self, text: str, topk = 20):
        text = text.strip().casefold()
        if topk <= 0 or not text:   # 返回前 topk 个
            doc_ids, seen_doc_ids = [], set()
            for chunk in self.data.all_chunks:
                doc_id = chunk["doc_id"]
                if doc_id in seen_doc_ids:
                    continue
                seen_doc_ids.add(doc_id)
                doc_ids.append(doc_id)
                if len(doc_ids) == topk:
                    break
            return doc_ids

        query_embedding = self.model.encode(
                    self.QUERY_PREFIX + text, 
                    show_progress_bar=False,
                    convert_to_numpy=True,
                    normalize_embeddings=True,)
        scores = self.data.embeddings @ query_embedding
        ranked_chunk_ids = np.argsort(-scores)

        doc_ids = []
        seen_doc_ids = set()

        for chunk_id in ranked_chunk_ids:
            chunk = self.data.all_chunks[int(chunk_id)]
            doc_id = chunk["doc_id"]

            if doc_id in seen_doc_ids:
                continue

            seen_doc_ids.add(doc_id)
            doc_ids.append(doc_id)

            if len(doc_ids) == topk:
                break

        return doc_ids
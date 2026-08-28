from .page_content import extract_page_content
from sentence_transformers import SentenceTransformer
from pathlib import Path
import json

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
'text': chunk 原文
}
'''

def split_text_to_chunks( 
    text: str,
    tokenizer,
    chunk_tokens: int = 384,
    overlap_tokens: int = 64,
):
    token_ids = tokenizer.encode(text, add_special_tokens=False)
    step = chunk_tokens - overlap_tokens
    chunks = []
    for chunk_index, start in enumerate(range(0, len(token_ids), step)):
        end = min(start + chunk_tokens, len(token_ids))
        current_ids = token_ids[start:end]
        chunk_text = tokenizer.decode(current_ids, skip_special_tokens=True).strip()

        if chunk_text:
            chunks.append({
                'chunk_index': chunk_index,
                'token_start':start,
                'token_end':end,
                'text':chunk_text
            })
        if end == len(token_ids):
            break
    
    return chunks

def build_embedding(docID_path, chunk_path,
                    tokenizer, 
                    chunk_tokens: int = 384,
                    overlap_tokens: int = 64,):
    all_chunks = []
    chunk_id = 0
    with open(docID_path, 'r', encoding='utf-8') as docID_reader:
        for line in docID_reader:
            state = json.loads(line)
            file_path = project_root / state['file']
            title, content = extract_page_content(file_path)
            chunks = split_text_to_chunks(content, tokenizer=tokenizer, 
                                          chunk_tokens=chunk_tokens, overlap_tokens=overlap_tokens)
            for chunk in chunks:
                all_chunks.append({
                    'chunk_id': chunk_id,
                    'doc_id': state['docID'],
                    'url': state['url'],
                    'title': title,
                    **chunk
                })
                chunk_id += 1
    with open(chunk_path, 'w', encoding='utf-8') as chunk_writer:
        for chunk in all_chunks:
            json.dump(chunk, chunk_writer)
            chunk_writer.write('\n')


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    docID_path = project_root / 'downloaded_html' / 'docID.jsonl'
    chunk_path = project_root / 'inverted_index' / 'chunks.jsonl'
    MODEL_NAME = "BAAI/bge-small-zh-v1.5"
    model = SentenceTransformer(MODEL_NAME)
    tokenizer = model.tokenizer

    chunk_tokens = 384
    overlap_tokens = 64
    step = chunk_tokens - overlap_tokens    
    build_embedding(docID_path=docID_path, chunk_path=chunk_path, tokenizer=tokenizer,
                    chunk_tokens=chunk_tokens, overlap_tokens=overlap_tokens)
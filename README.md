# RUC Embedding Search

一个面向中国人民大学相关网页的本地混合检索项目，包含网页抓取、Resiliparse HTML 解析、token 分块、Embedding 构建，以及字段加权 TF-IDF/BM25 词法检索。

项目将“网页是什么”与“网页如何排序”分开：`info/` 是本地网页数据访问层，`ruc_search/` 只负责索引、召回和排序。

## 项目结构

```text
.
├── crawler/
│   ├── crawler.py            # 网页抓取、断点续传和 docID 分配
│   ├── extractor.py          # 链接与跳转目标提取
│   └── content_dedup.py      # 正文精确与近重复检测
├── info/
│   ├── document_registry.py  # docID、URL 与本地 HTML 路径映射
│   └── page_info.py          # 按 URL 读取标题、正文和摘要
├── ruc_search/
│   ├── embedding_builder.py  # token 分块与 chunk Embedding 构建
│   ├── lexical_index.py      # 字段加权 TF-IDF/BM25 倒排索引
│   ├── offline_model.py      # 强制只从本地缓存加载 Embedding 模型
│   └── search_engine.py      # 可切换的词法、语义与混合排序
├── students_evaluation/rag/
│   ├── call_model.py         # OpenAI 兼容的大模型调用封装
│   └── search_engine.py      # RAG 检索、上下文构建与评测接口
├── data/                     # 本地数据和可重建产物，不提交
│   ├── downloaded_html/      # 按域名保存的 HTML
│   ├── docID.jsonl           # docID、URL 和 HTML 路径映射
│   ├── chunks.jsonl          # chunk 文本与元数据
│   ├── chunk_embeddings.npy  # 与 chunk_id 按行对应的向量
│   ├── lexical_index.json    # 可重建的字段加权词法索引
│   ├── content_fingerprints.jsonl # 已保存网页的内容指纹
│   └── duplicate_urls.jsonl  # 被跳过 URL 到原页面的映射
└── requirements.txt          # Python 依赖
```

## 环境

```bash
pip install -r requirements.txt
```

### 离线运行

所有检索入口都通过 `ruc_search/offline_model.py` 加载 Embedding 模型。代码会强制启用 Hugging Face、Transformers 和 Datasets 的离线模式，并使用 `local_files_only=True`，因此测试时不会尝试从 Hugging Face Hub 下载文件。缓存缺失时程序会立即给出明确错误。

断网前可以执行以下命令验证本地缓存：

```bash
python -c "from ruc_search.offline_model import load_embedding_model; load_embedding_model(); print('local model ready')"
```

`data/docID.jsonl`、`data/chunks.jsonl`、`data/chunk_embeddings.npy` 和 `data/lexical_index.json` 也必须保留在本地。需要注意，Embedding 检索可以完全离线运行，但 `students_evaluation/rag/call_model.py` 当前调用远程 DeepSeek API；如果 RAG 生成环节也完全断网，则还需要课程提供的本地接口或本地大模型。

## 常用命令

所有命令均从项目根目录执行。

继续运行爬虫：

```bash
python -m crawler.crawler
```

爬虫默认写入：

- `data/downloaded_html/`：本地 HTML；
- `data/docID.jsonl`：`docID`、`url`、`file` 映射；
- `data/crawler_checkpoint.json`：爬取断点。
- `data/content_fingerprints.jsonl`：已保存正文的持久化指纹；
- `data/duplicate_urls.jsonl`：未重复保存的 URL 及其对应原页面。

`docID.jsonl` 每行是一个 JSON 对象，格式固定为：

```json
{"docID": 0, "url": "https://example.ruc.edu.cn/", "file": "data/downloaded_html/example.ruc.edu.cn/example.html"}
```

`docID` 是非负且全局唯一的整数；`file` 是相对于项目根目录的路径，必须指向 `data/downloaded_html/` 中的文件。

### 网页信息 API

`DocumentRegistry` 是 `docID.jsonl` 的唯一读写入口；检索引擎、索引构建器和爬虫不自行保存 `docID -> URL` 映射。

```python
from pathlib import Path

from info import DocumentRegistry, PageInfoStore

project_root = Path.cwd()
registry = DocumentRegistry(
    project_root,
    project_root / "data" / "docID.jsonl",
)
pages = PageInfoStore(registry)

url = registry.get_url(2475)
html_path = registry.get_html_path_by_doc_id(2475)
page_info = pages.get_page_info(url)

print(page_info["title"])
print(page_info["abstract"])
print(page_info["content"])
```

`PageInfoStore` 只读本地 HTML，不在查询时请求外网。解析结果会按 URL 缓存；混合排序使用已有 chunk 预充的轻量字段，避免为每个候选页重复解析 HTML。

### 爬取时按正文去重

爬虫保存新页面前会先提取主内容，并执行两层去重：

1. 规范化正文的 SHA-256 相同，判为完全重复；
2. 64 位 SimHash 的汉明距离不超过 7 时，再检查页面标题和三词 shingle 的 bottom-k 草图。长正文的估计 Jaccard 相似度至少为 0.85、少于 1000 个有效字符的正文至少为 0.95，才判为近重复。

近重复页面不会写入 HTML，也不会获得新 `docID`，但爬虫仍会提取其中的链接，因而不会中断链接发现。重复关系会追加到 `duplicate_urls.jsonl`，重启后不会再次保存。第一次升级运行时会自动为已有 HTML 补建指纹；这不会删除已经保存的旧页面。

阈值可以在构造 `Crawler` 时调整：

```python
Crawler(
    start_urls,
    duplicate_hamming_threshold=7,
    duplicate_minimum_similarity=0.85,
    minimum_content_chars=200,
)
```

重建 chunk 和 Embedding：

```bash
python -m ruc_search.embedding_builder
```

### 检索模式与消融评测

`SearchEngine.search()` 支持 `tfidf`、`bm25`、`embedding`、`tfidf_hybrid` 和 `bm25_hybrid` 五种模式，默认使用 `bm25_hybrid`。BM25 沿用标题、小标题、正文的 $3:2:1$ 字段权重，并使用 $k_1=1.5$、$b=0.75$ 进行词频饱和与文档长度归一化。

连接课程 debug 服务器、在同一批查询上比较五种模式：

```bash
python -m students_evaluation.main.compare_methods
```

启动 Web 界面：

```bash
python -m web.app
```

普通检索可以直接使用；RAG 问答还需要在启动前设置 DeepSeek API Key：

```bash
export DEEPSEEK_API_KEY="你的 API Key"
python -m web.app
```

在首页输入内容后，可以选择“搜索”查看 20 条检索结果，也可以选择“RAG 问答”生成答案并查看用于核对的来源页面。两种模式共用同一个检索服务，不会重复加载 Embedding 模型和索引。

RAG 会先在本地执行多组短查询，合并和清洗检索结果，然后只调用一次大模型生成最终答案。多年份问题会逐年检索，包含多个高信息实体的企业参访问题会逐实体检索；不同子查询的结果按 URL 去重并交错合并，防止某一个查询占满上下文。评测接口保持为 `rag_evaluate(query) -> str`。

## 数据与提交

`data/` 属于本地运行数据和可重建产物，不纳入 Git。`chunk_embeddings.npy` 第 $i$ 行必须对应 `chunks.jsonl` 中 `chunk_id = i` 的记录，更新爬取语料后需要重建 chunk 和向量。

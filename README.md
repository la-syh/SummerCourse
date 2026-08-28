# RUC Embedding Search

一个面向中国人民大学相关网页的本地语义检索项目，包含网页抓取、Resiliparse HTML 解析、token 分块和 Embedding 构建。

## 项目结构

```text
.
├── crawler/
│   ├── crawler.py            # 网页抓取、断点续传和 docID 分配
│   └── extractor.py          # Resiliparse 链接与跳转目标提取
├── ruc_search/
│   ├── page_content.py       # Resiliparse 标题与正文提取
│   └── embedding_builder.py  # token 分块与 chunk Embedding 构建
├── data/                     # 本地数据和可重建产物，不提交
│   ├── downloaded_html/      # 按域名保存的 HTML
│   ├── docID.jsonl           # docID、URL 和 HTML 路径映射
│   ├── chunks.jsonl          # chunk 文本与元数据
│   └── chunk_embeddings.npy  # 与 chunk_id 按行对应的向量
└── requirements.txt          # Python 依赖
```

## 环境

```bash
conda activate ML
pip install -r requirements.txt
```

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

`docID.jsonl` 每行是一个 JSON 对象，格式固定为：

```json
{"docID": 0, "url": "https://example.ruc.edu.cn/", "file": "data/downloaded_html/example.ruc.edu.cn/example.html"}
```

`docID` 是非负且全局唯一的整数；`file` 是相对于项目根目录的路径，必须指向 `data/downloaded_html/` 中的文件。

重建 chunk 和 Embedding：

```bash
python -m ruc_search.embedding_builder
```

## 数据与提交

`data/` 属于本地运行数据和可重建产物，不纳入 Git。`chunk_embeddings.npy` 第 \(i\) 行必须对应 `chunks.jsonl` 中 `chunk_id = i` 的记录，更新爬取语料后需要重建 chunk 和向量。

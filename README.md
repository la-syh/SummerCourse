# RUC Search

一个面向中国人民大学相关网页的本地搜索引擎课程项目，包含网页抓取、HTML 解析、tf-idf 排序检索、结果去重、Web UI 和自动评测接口。

## 项目结构

```text
.
├── ruc_search/               # 核心搜索引擎包
│   ├── crawler.py            # 网页抓取与断点续传
│   ├── extractor.py          # HTML、正文和链接提取
│   ├── index.py              # 倒排索引与 tf-idf 排序
│   ├── metadata.py           # 离线标题、摘要和内容指纹生成
│   └── service.py            # Web 与评测共用的搜索服务
├── web/                      # Flask Web UI
│   ├── app.py
│   ├── static/
│   └── templates/
├── archive/                  # 课程早期历史实现
├── AI_disclosure.md          # Day 1 至 Day 5 合并后的 AI 使用记录
├── downloaded_html/          # 本地网页与 URL/docID 映射，不提交
├── inverted_index/           # 索引与页面元数据，不提交
├── students_evaluation/      # 助教评测客户端，不提交
└── stopwords.txt             # 本地停用词表，不提交
```

## 环境

```bash
pip install -r requirements.txt
```

## 常用命令

所有命令均从项目根目录执行。

生成或更新页面标题、摘要和内容指纹：

```bash
python -m ruc_search.metadata
```

启动 Web UI：

```bash
python -m web.app
```

浏览器访问 <http://127.0.0.1:12345/>。

使用命令行测试索引：

```bash
python -m ruc_search.index
```

继续运行爬虫：

```bash
python -m ruc_search.crawler
```

运行基础检索评测：

```bash
cd students_evaluation/main
python client.py
```

## 数据与提交

已下载网页、倒排索引、页面元数据、断点和停用词表属于本地运行数据，不纳入 Git。课程要求的每日 bundle 文件也不纳入当前仓库提交。

历史阶段代码没有删除，统一保存在 `archive/`；各阶段 AI 协作记录已按时间顺序合并到根目录的 `AI_disclosure.md`。

from day4.Inverted_index import Inverted_index
from flask import Flask, render_template, request
import json
from bs4 import BeautifulSoup
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
METADATA_PATH = PROJECT_ROOT / "inverted_index" / "page_metadata.jsonl"

def load_page_metadata(path: Path) -> dict[str, dict]:
    metadata = {}

    with path.open("r", encoding="utf-8") as reader:
        for line in reader:
            record = json.loads(line)
            metadata[record["url"]] = record

    return metadata


page_metadata = load_page_metadata(METADATA_PATH)

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/query', methods = ['GET'])
def query():
    key = request.args.get('key')

    # Implement your search engine here.
    # Generate a list of search results.
    urls = search(key) if key else []
    
    results = []
    for url in urls:
        page_info = page_metadata.get(url, {})

        results.append(
            {
                "title": page_info.get("title") or url,
                "url": url,
                "abstract": page_info.get("abstract") or "暂无摘要",
            }
        )

    return render_template('res.html', key=key, results=results)

def search(query_text: str) -> list[str]:
    return search_engine.query(query_text, k=20)

if __name__ == "__main__":
    docID_path = PROJECT_ROOT / "downloaded_html" / "docID.jsonl"
    index_path = PROJECT_ROOT / "inverted_index" / "inverted_index.json"
    stopwords_path = PROJECT_ROOT / "stopwords.txt"

    search_engine = Inverted_index(
        str(docID_path),
        str(index_path),
        str(stopwords_path),
    )
    app.run(host='0.0.0.0', port=12345, debug=True)

    
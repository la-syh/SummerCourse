from day4.Inverted_index import Inverted_index
from flask import Flask, render_template, request
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

def get_page_info(url: str):
    r = requests.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0"
        },
        timeout=10,
    )
    r.raise_for_status()

    # 关键：使用 content，不使用 text
    soup = BeautifulSoup(r.content, "html.parser")

    # title
    node = (
        soup.find("meta", {"name": "citation_title"})
        or soup.find("meta", {"property": "og:title"})
    )

    title = None

    if node is not None:
        content = node.get("content")
        if isinstance(content, str):
            title = content.strip()

    if title is None and soup.title is not None:
        title = soup.title.get_text(strip=True)

    # abstract
    node = (
        soup.find("meta", {"name": "citation_abstract"})
        or soup.find("meta", {"name": "description"})
        or soup.find("meta", {"property": "og:description"})
        or soup.find("meta", {"name": "twitter:description"})
    )

    abstract = None

    if node is not None:
        content = node.get("content")
        if isinstance(content, str):
            abstract = content.strip()

    return title, abstract

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/query', methods = ['GET'])
def query():
    key = request.args.get('key')

    # Implement your search engine here.
    # Generate a list of search results.
    headers = {'user-agent': 'my-app/0.0.1'}
    if key:
        urls = search_engine.query(key, k=20)
    else:
        urls = []
    
    results = []
    for url in urls:
        title, abstract = get_page_info(url)
        results.append({'title': title, 'url': url, 'abstract': abstract})

    return render_template('res.html', key=key, results=results)

docID_path = 'downloaded_html/docID.jsonl'
index_path = 'inverted_index/inverted_index.json'
stopwords_path = 'stopwords.txt'
search_engine = Inverted_index(docID_path, index_path, stopwords_path)
app.run(host='0.0.0.0', port=12345, debug=True)

    
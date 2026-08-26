from day1.ExtractHTML import ExtractHTML
from collections import defaultdict
import json
import os

class Inverted_index:
    def __init__(self, url_index, docID_path, inverted_index_path, stopwords_path = None, remake = False):
        self.stopwords = self.load_stopwords(stopwords_path)
        if remake or not os.path.exists(docID_path):  # 新建 docID
            self.make_docID(url_index, docID_path)
        if not remake and os.path.exists(inverted_index_path): # 倒排索引已经被构建过
            self.load_inverted_index(inverted_index_path)
            return
        
        # 构建倒排索引
        self.make_inverted_index(docID_path)
        self.save_inverted_index(inverted_index_path)

    def make_docID(self, url_index, file_path):
        temp_path = file_path + '.tmp'
        if os.path.exists(temp_path):
            os.remove(temp_path)
        docid, done_url = 0, set()
        try:
            with open(url_index, 'r', encoding='utf-8') as r:
                for line in r:
                    state = json.loads(line)
                    url, file = state['url'], 'downloaded_html/' + state['file']
                    if url in done_url:
                        continue
                    done_url.add(url)
                    with open(temp_path, 'a', encoding='utf-8') as w:
                        w.write(json.dumps({'docID': docid, 'url': url, 'file': file}, ensure_ascii=False) + '\n')
                    docid += 1
            os.replace(temp_path, file_path)
        except Exception as error:
            print(f'docID 构建失败: {error}')

    def make_inverted_index(self, docID_path):
        self.inverted_index = defaultdict(lambda: [-1])
        with open(docID_path, 'r', encoding='utf-8') as r:
            for line in r:
                state = json.loads(line)
                url, file, docID = state['url'], state['file'], state['docID']
                with open(file, 'r', encoding='utf-8') as file_reader:
                    content = file_reader.read()
                html = ExtractHTML(content)
                _, _, _, title_words, doctitle_words, body_words = html.extract_title_and_body_words()
                for raw_word in title_words + doctitle_words + body_words:
                    word = raw_word.strip().casefold()
                    if not word or word in self.stopwords:
                        continue
                    if docID != self.inverted_index[word][-1]:
                        self.inverted_index[word].append(docID)
    def save_inverted_index(self, inverted_index_path):
        output_dir = os.path.dirname(inverted_index_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        with open(inverted_index_path, 'w', encoding='utf-8') as w:
            json.dump(self.inverted_index, w, ensure_ascii=False)
    def load_inverted_index(self, inverted_index_path):
        with open(inverted_index_path, 'r', encoding='utf-8') as r:
            data = json.load(r)
        self.inverted_index = defaultdict(lambda: [-1], data)

    def load_stopwords(self, stopwords_path):
        if stopwords_path is None:
            return set()
        with open(stopwords_path, 'r', encoding='utf-8') as r:
            return {line.strip().casefold() for line in r if line.strip()}

    def query(self, word:str)-> list[int]:
        if not isinstance(word, str):
            raise TypeError('query 参数必须是字符串')
        
        word = word.strip().casefold()
        return (self.inverted_index.get(word, [-1]))[1:]
    def intersection(self, l1, l2)-> list[int]:
        result = []
        p1, p2 = iter(l1), iter(l2)
        try:
            doc1, doc2 = next(p1), next(p2)
            while True:
                if doc1 == doc2:
                    result.append(doc1)
                    doc1, doc2 = next(p1), next(p2)
                elif doc1 < doc2:
                    doc1 = next(p1)
                else:
                    doc2 = next(p2)
        except StopIteration:
            pass
        return result

    def union(self, l1, l2)-> list[int]:
        result = []
        i, j = 0, 0
        while i < len(l1) and j < len(l2):
            if l1[i] == l2[j]:
                result.append(l1[i])
                i, j = i + 1, j + 1
            elif l1[i] < l2[j]:
                result.append(l1[i])
                i = i + 1
            else:
                result.append(l2[j])
                j = j + 1
        result.extend(l1[i:])
        result.extend(l2[j:])
        return result

if __name__ == "__main__":
    url_index = 'downloaded_html/url_index.jsonl'
    docID_path = 'downloaded_html/docID.jsonl'
    inverted_index_path = 'inverted_index/inverted_index.jsonl'
    stopwords_path = 'stopwords.txt'
    index_maker = Inverted_index(url_index, docID_path, inverted_index_path, 
                                 stopwords_path=stopwords_path, remake=False)
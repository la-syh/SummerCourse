from day1.ExtractHTML import ExtractHTML
from collections import defaultdict
import json
import os

class Inverted_index:
    '''
    {
        "document_count": 15947,
        "terms": {
            "人工智能": {
                "df": 120,
                "postings": [
                    {"docID": 3, "tf": 2},
                    {"docID": 15, "tf": 4},
                    ...
                ]
            }
        },
        "doc_lengths":[
            12.34,
            8.91
        ]
    }
    '''
    def __init__(self, docID_path, stopwords_path = None):
        self.document_count = 0
        self.terms = defaultdict(lambda: dict())
        self.doc_lengths:list[float] = []
        self.stopwords = self.load_stopwords(stopwords_path)

        # init self.terms
        with open(docID_path, 'r', encoding='utf-8') as docID_reader:
            for line in docID_reader:
                state = json.loads(line)
                docID, url, file = state['docIC'], state['url'], state['file']
                self.document_count += 1
                with open(file, 'r', encoding='utf-8') as file_reader:
                    content = file_reader.read()
                html = ExtractHTML(content)
                _, _, _, title_words, doctitle_words, body_words = html.extract_title_and_body_words()
                for raw_word in title_words + doctitle_words + body_words:
                    word = raw_word.strip().casefold()
                    if not word or word in self.stopwords:
                        continue
                    self.add_term(word, docID)
        for word in self.terms.keys():
            self.terms[word]['df'] = len(self.terms[word]['postings'])

        # init doc vectors
        pass
        
    def load_stopwords(self, stopwords_path):
        if stopwords_path is None:
            return set()
        with open(stopwords_path, 'r', encoding='utf-8') as r:
            return {line.strip().casefold() for line in r if line.strip()}

    def add_term(self, word, docID):
        term_data = self.terms[word]
        postings = term_data.setdefault('postings', [])
        if self.terms[word]['postings'][-1]['docID'] != docID:
            self.terms[word]['postings'].append({'docID': docID, 'tf': 1})
        else:
            self.terms[word]['postings'][-1]['tf'] += 1

if __name__ == "__main__":
    docID_path = 'downloaded_html/docID.jsonl'
    stopwords_path = 'stopwords.txt'
    tester = Inverted_index(docID_path, stopwords_path)
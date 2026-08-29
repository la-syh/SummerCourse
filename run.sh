#!/bin/bash
python -m crawler.crawler
python -m ruc_search.embedding_builder
python -m web.app
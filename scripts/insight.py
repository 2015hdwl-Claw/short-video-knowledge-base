#!/usr/bin/env python3
"""Save an insight/lesson to wiki/insights/ or auto-detect from video summaries."""

import sys
import os
import json
import time
import datetime
import argparse
import re

import requests

REPO = os.path.dirname(os.path.abspath(__file__))
INSIGHTS_DIR = os.path.join(REPO, '..', 'wiki', 'insights')
JSON_PATH = os.path.join(REPO, '..', 'short-videos', 'short-videos.json')
os.makedirs(INSIGHTS_DIR, exist_ok=True)

API_KEY = os.getenv('CLASSIFIER_API_KEY', '7571f91152a74a669179d3a2c67c513a.E6KUmy0NNEwTYdKK')
BASE_URL = os.getenv('CLASSIFIER_BASE_URL', 'https://open.bigmodel.cn/api/paas/v4/')
MODEL = os.getenv('CLASSIFIER_MODEL', 'glm-4.7-flash')
MAX_BATCHES = 3
BATCH_SIZE = 5

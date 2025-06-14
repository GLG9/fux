import os
import sys
import json
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler

import pytest
import requests

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT_DIR)

from main import parse_grades, generate_messages, send_discord_messages

@pytest.fixture(scope="module")
def grade_server():
    handler = SimpleHTTPRequestHandler
    os.chdir(ROOT_DIR)
    server = HTTPServer(("localhost", 8000), handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    try:
        yield "http://localhost:8000/index.html"
    finally:
        server.shutdown()
        thread.join()


def fetch_example_data(url):
    resp = requests.get(url)
    resp.raise_for_status()
    return parse_grades(resp.text)


def test_parse_grades_via_server(grade_server):
    data = fetch_example_data(grade_server)
    assert "Deutsch" in data["subjects"]
    assert isinstance(data["N1"], float)


def test_generate_messages_new_grade(grade_server):
    base = fetch_example_data(grade_server)
    old = json.loads(json.dumps(base))
    new = json.loads(json.dumps(base))
    new["subjects"]["Deutsch"]["H2Grades"].append("4")
    msgs = generate_messages(new, old)
    assert any("Neue Note in Deutsch (H2)" in m for m in msgs)


def test_generate_messages_final_grade(grade_server):
    base = fetch_example_data(grade_server)
    old = json.loads(json.dumps(base))
    new = json.loads(json.dumps(base))
    old["subjects"]["Biologie"]["FinalGrade"] = None
    msgs = generate_messages(new, old)
    assert any("Zeugnisnote in Biologie" in m for m in msgs)


def test_no_messages_when_no_change(grade_server):
    data = fetch_example_data(grade_server)
    msgs = generate_messages(data, data)
    assert msgs == []


def test_send_discord_messages(monkeypatch):
    sent = []
    def fake_post(url, headers=None, json=None):
        sent.append(json["content"])
        class R:
            status_code = 204
            text = ""
        return R()

    monkeypatch.setattr(requests, "post", fake_post)
    send_discord_messages(["msg1", "msg2"])
    assert sent == ["msg1", "msg2"]

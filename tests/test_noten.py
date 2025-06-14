import importlib
import json
import os
import threading
import http.server
from functools import partial

import requests
import pytest


def start_server(directory):
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    server = http.server.ThreadingHTTPServer(("localhost", 8000), handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    return server, thread


def setup_env(monkeypatch):
    monkeypatch.setenv("USER1", "Test")
    monkeypatch.setenv("USERNAME1", "u")
    monkeypatch.setenv("PASSWORD1", "p")
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
    import sys
    import pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    import main
    importlib.reload(main)
    return main


def compute_messages(old_data, new_data, user_name):
    messages = []
    old_info_all = old_data.get(user_name, {})
    for subject, info in new_data.get("subjects", {}).items():
        old_info = old_info_all.get("subjects", {}).get(subject, {})
        for sem in ["H1Grades", "H2Grades"]:
            new_list = info.get(sem, [])
            old_list = old_info.get(sem, [])
            for grade in new_list[len(old_list):]:
                messages.append(f"[{user_name}] Neue Note in {subject} ({sem[:2]}): {grade}")
        new_final = info.get("FinalGrade")
        if new_final is not None and new_final != old_info.get("FinalGrade"):
            messages.append(f"[{user_name}] Zeugnisnote in {subject} steht fest: {new_final}")
    return messages


def test_fetch_and_parse(monkeypatch):
    main = setup_env(monkeypatch)
    server, thread = start_server(os.getcwd())
    try:
        res = requests.get("http://localhost:8000/index.html")
        data = main.parse_grades(res.text)
    finally:
        server.shutdown()
        thread.join()
    assert "Deutsch" in data["subjects"]
    assert isinstance(data["subjects"]["Deutsch"], dict)


def test_no_new_grades(monkeypatch):
    main = setup_env(monkeypatch)
    html = open("index.html", encoding="utf-8").read()
    old_data = {"Test": main.parse_grades(html)}
    new_data = json.loads(json.dumps(old_data["Test"]))
    messages = compute_messages(old_data, {"subjects": new_data["subjects"]}, "Test")
    assert messages == []


def test_new_grade_and_final(monkeypatch):
    main = setup_env(monkeypatch)
    html = open("index.html", encoding="utf-8").read()
    base = main.parse_grades(html)
    old = {"Test": json.loads(json.dumps(base))}

    # add a grade and change final grade
    modified = json.loads(json.dumps(base))
    modified["subjects"]["Deutsch"]["H1Grades"].append("3")
    modified["subjects"]["Deutsch"]["FinalGrade"] = 2

    messages = compute_messages(old, {"subjects": modified["subjects"]}, "Test")

    sent = []

    class DummyResponse:
        status_code = 204
        text = ""

    def fake_post(url, headers=None, json=None):
        sent.append(json["content"])
        return DummyResponse()

    monkeypatch.setattr(requests, "post", fake_post)

    for msg in messages:
        requests.post("https://discord.com/api/channels/123/messages", json={"content": msg})

    assert "Neue Note" in sent[0]
    assert any("Zeugnisnote" in s for s in sent)
    assert len(sent) == len(messages)


def test_sparse_user_indexes(monkeypatch):
    monkeypatch.delenv("USER1", raising=False)
    monkeypatch.delenv("USERNAME1", raising=False)
    monkeypatch.delenv("PASSWORD1", raising=False)
    monkeypatch.setenv("USER2", "Sparse")
    monkeypatch.setenv("USERNAME2", "user2")
    monkeypatch.setenv("PASSWORD2", "pass2")
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
    import importlib
    import main
    importlib.reload(main)
    assert len(main.USERS) == 1
    assert main.USERS[0]["username"] == "user2"


def test_fetch_html_returns_none_on_error(monkeypatch):
    main = setup_env(monkeypatch)

    def fail_get(self, *args, **kwargs):
        raise requests.RequestException("fail")

    monkeypatch.setattr(requests.Session, "get", fail_get)

    session = requests.Session()
    html = main.fetch_html("u", "p", session=session)
    assert html is None

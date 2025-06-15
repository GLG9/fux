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
    show_avg = os.getenv("SHOW_YEAR_AVERAGE", "true").lower() == "true"
    old_info_all = old_data.get(user_name, {})
    for subject, info in new_data.get("subjects", {}).items():
        old_info = old_info_all.get("subjects", {}).get(subject, {})
        for sem in ["H1Grades", "H2Grades", "H1Exams", "H2Exams"]:
            new_list = info.get(sem, [])
            old_list = old_info.get(sem, [])
            for grade in new_list[len(old_list):]:
                prefix = "Klassenarbeitsnote" if sem.endswith("Exams") else "Note"
                msg = f"[{user_name}] Neue {prefix} in {subject} ({sem[:2]}): {grade}"
                if show_avg:
                    avg = info.get("YearAverage")
                    if avg is not None:
                        msg += f". Damit stehst du jetzt {avg} [\"YearAverage\"]"
                messages.append(msg)
        for key, label in [("H1FinalGrade", "HJ1"), ("H2FinalGrade", "HJ2")]:
            new_final = info.get(key)
            if new_final is not None and new_final != old_info.get(key):
                messages.append(
                    f"[{user_name}] Zeugnisnote ({label}) in {subject} steht fest: {new_final}"
                )
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
    modified["subjects"]["Deutsch"]["H1FinalGrade"] = 3

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
    assert "YearAverage" in sent[0]
    assert any("Zeugnisnote" in s for s in sent)
    assert len(sent) == len(messages)


def test_new_exam_grade(monkeypatch):
    main = setup_env(monkeypatch)
    html = open("index.html", encoding="utf-8").read()
    base = main.parse_grades(html)
    old = {"Test": json.loads(json.dumps(base))}

    modified = json.loads(json.dumps(base))
    modified["subjects"]["Deutsch"]["H1Exams"].append("2")

    messages = compute_messages(old, {"subjects": modified["subjects"]}, "Test")
    assert any("Klassenarbeitsnote" in m for m in messages)


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


def test_debug_local_no_credentials(monkeypatch):
    monkeypatch.setenv("DEBUG_LOCAL", "true")
    monkeypatch.setenv("USER1", "Debug")
    monkeypatch.delenv("USERNAME1", raising=False)
    monkeypatch.delenv("PASSWORD1", raising=False)
    monkeypatch.delenv("USER2", raising=False)
    monkeypatch.delenv("USERNAME2", raising=False)
    monkeypatch.delenv("PASSWORD2", raising=False)
    monkeypatch.setenv("DISCORD_TOKEN", "t")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "1")

    import importlib
    import main
    importlib.reload(main)

    assert len(main.USERS) == 1
    assert main.USERS[0]["name"] == "Debug"


def test_fetch_html_debug_local(monkeypatch):
    monkeypatch.setenv("DEBUG_LOCAL", "true")
    main = setup_env(monkeypatch)
    server, thread = start_server(os.getcwd())
    try:
        session = requests.Session()
        data = main.fetch_html("", "", session=session)
    finally:
        server.shutdown()
        thread.join()
    assert "Deutsch" in data["subjects"]


def test_parse_with_stray_text(monkeypatch):
    main = setup_env(monkeypatch)
    html = open("index.html", encoding="utf-8").read()
    modified = html.replace("<td>2</td><td></td>", "<td>2</td>1<td></td>", 1)

    base = main.parse_grades(html)
    changed = main.parse_grades(modified)

    assert len(changed["subjects"]["Deutsch"]["H1Grades"]) == len(base["subjects"]["Deutsch"]["H1Grades"]) + 1
    msgs = compute_messages({"Test": base}, {"subjects": changed["subjects"]}, "Test")
    assert any("Neue Note" in m for m in msgs)


def test_exams_without_decimal(monkeypatch):
    main = setup_env(monkeypatch)
    html = open("index.html", encoding="utf-8").read()
    data = main.parse_grades(html)
    exams = data["subjects"]["Deutsch"]["H1Exams"]
    assert all("," not in e for e in exams)


def test_disable_year_average(monkeypatch):
    monkeypatch.setenv("SHOW_YEAR_AVERAGE", "false")
    main = setup_env(monkeypatch)
    html = open("index.html", encoding="utf-8").read()
    base = main.parse_grades(html)
    old = {"Test": json.loads(json.dumps(base))}

    modified = json.loads(json.dumps(base))
    modified["subjects"]["Deutsch"]["H1Grades"].append("2")

    msgs = compute_messages(old, {"subjects": modified["subjects"]}, "Test")
    assert not any("YearAverage" in m for m in msgs)

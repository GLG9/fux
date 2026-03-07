import importlib
import json
import os
import re
import threading
import http.server
from functools import partial

import requests
import pytest


def clear_user_env(monkeypatch):
    for key in list(os.environ):
        if re.fullmatch(r"(USER|USERNAME|PASSWORD)\d+", key):
            monkeypatch.setenv(key, "")


def start_server(directory):
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    server = http.server.ThreadingHTTPServer(("localhost", 8000), handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    return server, thread


def setup_env(monkeypatch):
    clear_user_env(monkeypatch)
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


def pick_subject(data, key=None):
    subjects = data["subjects"]
    if key:
        for subject, info in subjects.items():
            if info.get(key):
                return subject
    return next(iter(subjects))


def test_fetch_and_parse(monkeypatch):
    main = setup_env(monkeypatch)
    server, thread = start_server(os.getcwd())
    try:
        res = requests.get("http://localhost:8000/index.html")
        data = main.parse_grades(res.text)
    finally:
        server.shutdown()
        thread.join()
    subject = pick_subject(data)
    assert subject in data["subjects"]
    assert isinstance(data["subjects"][subject], dict)
    assert len(data.get("PeriodLabels", [])) == 4


def test_no_new_grades(monkeypatch):
    main = setup_env(monkeypatch)
    html = open("index.html", encoding="utf-8").read()
    base = main.parse_grades(html)
    old_copy = json.loads(json.dumps(base))
    messages = main.collect_messages(
        "Test", base, old_copy, show_year_average=main.SHOW_YEAR_AVERAGE
    )
    assert messages == []


def test_new_grade_and_final(monkeypatch):
    main = setup_env(monkeypatch)
    html = open("index.html", encoding="utf-8").read()
    base = main.parse_grades(html)
    old = json.loads(json.dumps(base))

    # add a grade and change final grade
    modified = json.loads(json.dumps(base))
    subject = pick_subject(base)
    modified["subjects"][subject]["H1Grades"].append("3")
    modified["subjects"][subject]["YearAverage"] = 10.5
    modified["subjects"][subject]["H1FinalGrade"] = 3
    modified["subjects"][subject]["FinalGrade"] = 3

    messages = main.collect_messages(
        "Test", modified, old, show_year_average=main.SHOW_YEAR_AVERAGE
    )

    sent = []

    class DummyResponse:
        status_code = 204
        text = ""

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.append(json["content"])
        return DummyResponse()

    monkeypatch.setattr(requests, "post", fake_post)

    for msg in messages:
        requests.post(
            "https://discord.com/api/channels/123/messages",
            json={"content": msg},
            timeout=main.REQUEST_TIMEOUT_SECONDS,
        )

    assert any(f"Neue Note in {subject}" in m for m in sent)
    assert any("Damit stehst du jetzt 10,50" in m for m in sent)
    assert any("Zeugnisnote (HJ1)" in m for m in sent)
    assert len(sent) == len(messages) == 1


def test_new_exam_grade(monkeypatch):
    main = setup_env(monkeypatch)
    html = open("index.html", encoding="utf-8").read()
    base = main.parse_grades(html)
    old = json.loads(json.dumps(base))

    modified = json.loads(json.dumps(base))
    subject = pick_subject(base)
    modified["subjects"][subject]["H1Exams"].append("2")

    messages = main.collect_messages(
        "Test", modified, old, show_year_average=main.SHOW_YEAR_AVERAGE
    )
    assert any("Klassenarbeitsnote" in m for m in messages)


def test_sparse_user_indexes(monkeypatch):
    clear_user_env(monkeypatch)
    monkeypatch.setenv("USER2", "Sparse")
    monkeypatch.setenv("USERNAME2", "user2")
    monkeypatch.setenv("PASSWORD2", "pass2")
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
    import importlib
    import main
    importlib.reload(main)
    assert any(user["username"] == "user2" for user in main.USERS)


def test_fetch_html_returns_none_on_error(monkeypatch):
    main = setup_env(monkeypatch)

    def fail_get(self, *args, **kwargs):
        raise requests.RequestException("fail")

    monkeypatch.setattr(requests.Session, "get", fail_get)

    session = requests.Session()
    html = main.fetch_html("u", "p", session=session)
    assert html is None


def test_debug_local_no_credentials(monkeypatch):
    clear_user_env(monkeypatch)
    monkeypatch.setenv("DEBUG_LOCAL", "true")
    monkeypatch.setenv("USER1", "Debug")
    monkeypatch.setenv("USERNAME1", "")
    monkeypatch.setenv("PASSWORD1", "")
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
    assert pick_subject(data) in data["subjects"]


def test_parse_with_stray_text(monkeypatch):
    main = setup_env(monkeypatch)
    html = """
    <table id='student_main_grades_table_1'><tbody>
    <tr><td>Mathe</td><td>1</td><td></td><td>2</td><td>3,0</td><td class='final_average'>4,0</td></tr>
    </tbody></table>
    """
    modified = html.replace("<td>2</td><td>3,0</td>", "<td>2</td>1<td>3,0</td>", 1)

    base = main.parse_grades(html)
    changed = main.parse_grades(modified)

    assert len(changed["subjects"]["Mathe"]["H1Grades"]) == len(base["subjects"]["Mathe"]["H1Grades"]) + 1
    msgs = main.collect_messages(
        "Test",
        changed,
        base,
        show_year_average=main.SHOW_YEAR_AVERAGE,
    )
    assert any("Neue Note" in m for m in msgs)


def test_exams_without_decimal(monkeypatch):
    main = setup_env(monkeypatch)
    html = open("index.html", encoding="utf-8").read()
    data = main.parse_grades(html)
    subject = pick_subject(data, "H1Exams")
    exams = data["subjects"][subject]["H1Exams"]
    assert all("," not in e for e in exams)


def test_disable_year_average(monkeypatch):
    monkeypatch.setenv("SHOW_YEAR_AVERAGE", "false")
    main = setup_env(monkeypatch)
    html = open("index.html", encoding="utf-8").read()
    base = main.parse_grades(html)
    old = json.loads(json.dumps(base))

    modified = json.loads(json.dumps(base))
    subject = pick_subject(base)
    modified["subjects"][subject]["H1Grades"].append("2")
    modified["subjects"][subject]["YearAverage"] = 9.0

    msgs = main.collect_messages(
        "Test",
        modified,
        old,
        show_year_average=main.SHOW_YEAR_AVERAGE,
    )
    assert msgs
    assert not any("Damit stehst du jetzt" in m for m in msgs)


def test_new_grade_third_period(monkeypatch):
    main = setup_env(monkeypatch)
    html = open("index.html", encoding="utf-8").read()
    base = main.parse_grades(html)
    old = json.loads(json.dumps(base))

    modified = json.loads(json.dumps(base))
    subject = pick_subject(base)
    modified["subjects"][subject]["H3Grades"].append("15")

    msgs = main.collect_messages(
        "Test",
        modified,
        old,
        show_year_average=main.SHOW_YEAR_AVERAGE,
    )
    assert msgs
    assert any("(H3)" in m for m in msgs)


def test_final_grade_fourth_period(monkeypatch):
    main = setup_env(monkeypatch)
    html = open("index.html", encoding="utf-8").read()
    base = main.parse_grades(html)
    old = json.loads(json.dumps(base))

    modified = json.loads(json.dumps(base))
    subject = pick_subject(base)
    modified["subjects"][subject]["H4FinalGrade"] = 11

    msgs = main.collect_messages(
        "Test",
        modified,
        old,
        show_year_average=main.SHOW_YEAR_AVERAGE,
    )
    assert msgs
    assert any("Zeugnisnote (HJ4)" in m for m in msgs)


def test_collect_messages_without_period_labels(monkeypatch):
    main = setup_env(monkeypatch)
    html = open("index.html", encoding="utf-8").read()
    base = main.parse_grades(html)
    old = json.loads(json.dumps(base))
    old.pop("PeriodLabels", None)

    modified = json.loads(json.dumps(base))
    subject = pick_subject(base)
    modified["subjects"][subject]["H1Grades"].append("12")

    msgs = main.collect_messages(
        "Test",
        modified,
        old,
        show_year_average=main.SHOW_YEAR_AVERAGE,
    )
    assert msgs
    assert any("(H1)" in m for m in msgs)

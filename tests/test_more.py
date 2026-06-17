import importlib
import json
from datetime import datetime
from bs4 import BeautifulSoup
import os
import re
import sys
import pathlib
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


def clear_user_env(monkeypatch):
    for key in list(os.environ):
        if re.fullmatch(r"(USER|USERNAME|PASSWORD)\d+", key):
            monkeypatch.setenv(key, "")



def setup_basic_env(monkeypatch):
    clear_user_env(monkeypatch)
    monkeypatch.setenv("USER1", "Test")
    monkeypatch.setenv("USERNAME1", "u")
    monkeypatch.setenv("PASSWORD1", "p")
    monkeypatch.setenv("DISCORD_TOKEN", "t")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "1")
    monkeypatch.delenv("DEBUG_LOCAL", raising=False)
    import main
    importlib.reload(main)
    return main


def test_iter_cells_with_text(monkeypatch):
    m = setup_basic_env(monkeypatch)
    row = BeautifulSoup("<tr><td>A</td>text<td>B</td></tr>", "html.parser").tr
    cells = m._iter_cells(row)
    assert [c.get_text(strip=True) for c in cells] == ["A", "text", "B"]


def test_parse_semester_table_simple(monkeypatch):
    m = setup_basic_env(monkeypatch)
    html = """
    <table><tbody>
    <tr><td>Mathe</td><td>1</td><td>2</td><td>3</td><td class='final_average'>4,5</td><td>5,5</td></tr>
    </tbody></table>
    """
    table = BeautifulSoup(html, "html.parser").table
    parsed = m._parse_semester_table(table)
    info = parsed["Mathe"]
    assert info["tests"] == ["1", "2"]
    assert info["grades"] == ["3"]
    assert info["grades_average"] == 5.5
    assert info["average"] == 4.5


def test_parse_semester_table_uses_current_period_final_average(monkeypatch):
    m = setup_basic_env(monkeypatch)
    html = """
    <table data-period='2'><tbody>
    <tr>
    <td>Mathe</td><td></td><td></td><td>12</td><td>12,00</td>
    <td class='final_average'>12,75</td><td class='final_average'>12,00</td>
    </tr>
    </tbody></table>
    """
    table = BeautifulSoup(html, "html.parser").table
    parsed = m._parse_semester_table(table)
    info = parsed["Mathe"]
    assert info["grades"] == ["12"]
    assert info["grades_average"] == 12.0
    assert info["average"] == 12.0


def test_parse_grades_final_extra_subject(monkeypatch):
    m = setup_basic_env(monkeypatch)
    html = """
    <table id='student_main_grades_table_all'><tbody>
    <tr><td>Mathe</td><td class='final_average'>1</td></tr>
    </tbody></table>
    <table id='student_main_grades_table_1'><tbody></tbody></table>
    <table id='student_main_grades_table_2'><tbody></tbody></table>
    <div id='student_final_grades_container'><table><tbody>
    <tr><td>Physik</td><td class='display_final_grade'>2</td></tr>
    </tbody></table></div>
    """
    data = m.parse_grades(html)
    assert "Mathe" in data["subjects"]
    assert "Physik" in data["subjects"]
    assert data["subjects"]["Physik"]["FinalGrade"] == 2


def test_parse_grades_all_table_grouped_period_averages(monkeypatch):
    m = setup_basic_env(monkeypatch)
    html = """
    <table id='student_main_grades_table_all'>
    <thead>
    <tr>
    <th class='fixed_1'></th>
    <th class='text-center' colspan='3'>1. Halbjahr | N1 Ø 11,50</th>
    <th class='text-center' colspan='4'>2. Halbjahr | N2 Ø 12,00</th>
    </tr>
    </thead>
    <tbody>
    <tr>
    <td>Mathe</td>
    <td>12</td><td>12,00</td><td class='final_average'>12,75</td>
    <td>13</td><td>13,00</td><td class='final_average'>12,75</td><td class='final_average'>12,00</td>
    </tr>
    </tbody></table>
    """
    data = m.parse_grades(html)
    info = data["subjects"]["Mathe"]
    assert data["PeriodLabels"] == ["H1", "H2"]
    assert data["N1"] == 11.5
    assert data["N2"] == 12.0
    assert info["H1Average"] == 12.75
    assert info["H2Average"] == 12.0
    assert info["CurrentPeriodAverage"] == 12.0
    assert info["YearAverage"] == 12.0


def test_negative_average_placeholders_are_ignored(monkeypatch):
    m = setup_basic_env(monkeypatch)
    html = """
    <table id='student_main_grades_table_1'><tbody>
    <tr><td>Mathe</td><td></td><td></td><td>12</td><td>12,00</td><td class='final_average'>12,00</td></tr>
    </tbody></table>
    <table id='student_main_grades_table_2'><tbody>
    <tr><td>Mathe</td><td></td><td></td><td>12</td><td>12,00</td><td class='final_average'>-1,00</td></tr>
    </tbody></table>
    <table id='student_main_grades_table_all'>
    <thead><tr>
    <th class='text-center'>12,00</th>
    <th class='text-center'>-1,00</th>
    <th class='text-center'>-1,00</th>
    </tr></thead>
    <tbody>
    <tr><td>Mathe</td><td class='final_average'>12,00</td><td class='final_average'>-1,00</td><td class='final_average'>-1,00</td></tr>
    </tbody></table>
    <div id='student_final_grades_container'><table><tbody>
    <tr>
    <td>Mathe</td>
    <td class='score_display display_avg'>12,00</td><td class='score_display display_final_grade'></td>
    <td class='score_display display_avg'>-1,00</td><td class='score_display display_final_grade'></td>
    </tr>
    </tbody></table></div>
    """
    data = m.parse_grades(html)
    assert data["subjects"]["Mathe"]["H2Average"] is None
    assert data["subjects"]["Mathe"]["CurrentPeriodAverage"] is None
    assert data["subjects"]["Mathe"]["YearAverage"] is None

    old = json.loads(json.dumps(data))
    modified = json.loads(json.dumps(data))
    modified["subjects"]["Mathe"]["H2Grades"].append("12")

    msgs = m.collect_messages("Test", modified, old, show_year_average=True)
    assert msgs
    assert not any("-1,00" in msg for msg in msgs)
    assert not any("Damit stehst du aktuell bei" in msg for msg in msgs)


def test_year_average_uses_latest_active_period_average(monkeypatch):
    m = setup_basic_env(monkeypatch)
    html = """
    <table id='student_main_grades_table_1'><tbody>
    <tr>
    <td>Mathe</td><td>12</td><td>12,00</td><td>12</td><td>12,00</td><td class='final_average'>12,75</td>
    </tr>
    </tbody></table>
    <table id='student_main_grades_table_2'><tbody>
    <tr>
    <td>Mathe</td><td></td><td></td><td>13</td><td>13,00</td>
    <td class='final_average'>12,75</td><td class='final_average'>12,00</td>
    </tr>
    </tbody></table>
    <div id='student_final_grades_container'><table><tbody>
    <tr>
    <td>Mathe</td>
    <td class='score_display display_avg'>12,75</td><td class='score_display display_final_grade'>13</td>
    <td class='score_display display_avg'>-1,00</td><td class='score_display display_final_grade'></td>
    </tr>
    </tbody></table></div>
    """
    data = m.parse_grades(html)
    assert data["subjects"]["Mathe"]["H2Average"] == 12.0
    assert data["subjects"]["Mathe"]["CurrentPeriodAverage"] == 12.0
    assert data["subjects"]["Mathe"]["YearAverage"] == 12.0

    old = json.loads(json.dumps(data))
    modified = json.loads(json.dumps(data))
    modified["subjects"]["Mathe"]["H2Grades"].append("15")

    msgs = m.collect_messages("Test", modified, old, show_year_average=True)
    assert msgs
    assert any("Damit stehst du aktuell bei 12,00" in msg for msg in msgs)


def test_final_only_second_period_subject_is_reported(monkeypatch):
    m = setup_basic_env(monkeypatch)
    html = """
    <table id='student_main_grades_table_1'><tbody></tbody></table>
    <table id='student_main_grades_table_2'><tbody>
    <tr><td>Skikurs1 - 2. KHJ</td><td></td><td></td><td></td><td></td><td class='final_average'></td><td class='final_average'></td></tr>
    </tbody></table>
    <div id='student_final_grades_container'><table><tbody>
    <tr>
    <td>Skikurs1 - 2. KHJ</td>
    <td class='score_display display_avg'></td><td class='score_display display_final_grade'></td>
    <td class='score_display display_avg'></td><td class='score_display display_final_grade'>15</td>
    </tr>
    </tbody></table></div>
    """
    data = m.parse_grades(html)
    info = data["subjects"]["Skikurs1 - 2. KHJ"]
    assert info["H1FinalGrade"] is None
    assert info["H2FinalGrade"] == 15
    assert info["FinalGrade"] == 15

    msgs = m.collect_messages(
        "Test",
        data,
        {"subjects": {"Skikurs1 - 2. KHJ": {"H2FinalGrade": None}}},
        show_year_average=True,
    )
    assert any("Zeugnisnote (HJ2) in Skikurs1 - 2. KHJ steht fest: 15" in msg for msg in msgs)


def test_collect_messages_keeps_real_half_year_number(monkeypatch):
    m = setup_basic_env(monkeypatch)
    new = {
        "PeriodLabels": ["H2"],
        "subjects": {
            "Mathe": {
                "H2Exams": [],
                "H2Grades": [],
                "H2GradesAverage": None,
                "H2Average": 12.0,
                "H2FinalGrade": 12,
                "CurrentPeriodAverage": 12.0,
                "YearAverage": 12.0,
                "FinalGrade": 12,
            }
        },
    }
    old = {"subjects": {"Mathe": {"H2FinalGrade": None, "YearAverage": None}}}
    msgs = m.collect_messages("Test", new, old, show_year_average=True)
    assert msgs
    assert any("Zeugnisnote (HJ2)" in msg for msg in msgs)


def test_list_diff_insertion(monkeypatch):
    m = setup_basic_env(monkeypatch)
    old = ["10", "9"]
    new = ["11", "10", "9"]
    assert m._list_diff(old, new) == ["11"]


def test_check_env_missing(monkeypatch):
    clear_user_env(monkeypatch)
    monkeypatch.setenv("USER1", "Test")
    monkeypatch.setenv("USERNAME1", "u")
    monkeypatch.setenv("PASSWORD1", "p")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "")
    monkeypatch.setenv("DISCORD_TOKEN", "t")
    importlib.invalidate_caches()
    import main
    with pytest.raises(SystemExit):
        importlib.reload(main)


def test_load_json_file_corrupt_returns_empty(monkeypatch, tmp_path):
    m = setup_basic_env(monkeypatch)
    path = tmp_path / "old_grades_Test.json"
    path.write_text("{", encoding="utf-8")
    assert m._load_json_file(str(path)) == {}


def test_write_json_file_roundtrip(monkeypatch, tmp_path):
    m = setup_basic_env(monkeypatch)
    path = tmp_path / "grades_Test.json"
    payload = {"subjects": {"Mathe": {"H1Grades": ["12"]}}}
    m._write_json_file(str(path), payload)
    assert json.loads(path.read_text(encoding="utf-8")) == payload


def test_single_line_log_text(monkeypatch):
    m = setup_basic_env(monkeypatch)
    assert m._single_line_log_text("Zeile 1\nZeile 2\nZeile 3") == "Zeile 1 | Zeile 2 | Zeile 3"


def test_send_startup_message(monkeypatch):
    m = setup_basic_env(monkeypatch)
    sent = []
    monkeypatch.setattr(m, "_send_discord_message", lambda content: sent.append(content) or True)

    assert m._send_startup_message(datetime(2026, 6, 16, 9, 45))
    assert sent == ["[System] Fux Noten-Checker gestartet (16.06.2026 09:45)."]


def test_consume_startup_message_request_once(monkeypatch, tmp_path):
    m = setup_basic_env(monkeypatch)
    marker = tmp_path / ".send_startup_message"
    marker.write_text("", encoding="utf-8")

    assert m._consume_startup_message_request(str(marker))
    assert not marker.exists()
    assert not m._consume_startup_message_request(str(marker))


def test_seconds_until_next_interval_on_boundary(monkeypatch):
    m = setup_basic_env(monkeypatch)
    now = datetime(2026, 3, 16, 8, 30, 0)
    assert m._seconds_until_next_interval(now=now, interval_minutes=30) == 0.0


def test_seconds_until_next_interval_aligns_to_full_half_hour(monkeypatch):
    m = setup_basic_env(monkeypatch)
    now = datetime(2026, 3, 16, 8, 31, 15)
    assert m._seconds_until_next_interval(now=now, interval_minutes=30) == 28 * 60 + 45


def test_should_run_now_on_startup_with_small_boundary_delay(monkeypatch):
    m = setup_basic_env(monkeypatch)
    now = datetime(2026, 3, 16, 6, 0, 1)
    assert m._should_run_now_on_startup(now=now, interval_minutes=30, startup_grace_seconds=5.0)


def test_should_not_run_now_on_startup_far_from_boundary(monkeypatch):
    m = setup_basic_env(monkeypatch)
    now = datetime(2026, 3, 16, 6, 7, 0)
    assert not m._should_run_now_on_startup(now=now, interval_minutes=30, startup_grace_seconds=5.0)


def test_fetch_html_success(monkeypatch):
    m = setup_basic_env(monkeypatch)
    html = open("index.html", encoding="utf-8").read()

    class DummyResp:
        def __init__(self, text="", status=200, url=""):
            self.text = text
            self.status_code = status
            self.url = url

    class DummySession:
        def __init__(self):
            self.headers = {}
            self.calls = []
        def get(self, url, **kwargs):
            self.calls.append(("get", url, kwargs))
            if "webinfo" in url and "account" not in url:
                return DummyResp('<input name="_nonce" value="x"><input name="_f_secure" value="y">')
            return DummyResp(html)
        def post(self, url, data=None, allow_redirects=True, **kwargs):
            self.calls.append(("post", url, kwargs))
            return DummyResp("", url="/account")

    session = DummySession()
    data = m.fetch_html("u", "p", session=session)
    assert data["subjects"]
    assert any(c[0] == "post" for c in session.calls)
    assert all(c[2].get("timeout") == m.REQUEST_TIMEOUT_SECONDS for c in session.calls)


def test_fetch_html_rejects_unexpected_account_page(monkeypatch):
    m = setup_basic_env(monkeypatch)

    class DummyResp:
        def __init__(self, text="", status=200, url=""):
            self.text = text
            self.status_code = status
            self.url = url

    class DummySession:
        def __init__(self):
            self.headers = {}
        def get(self, url, **kwargs):
            if "webinfo" in url and "account" not in url:
                return DummyResp('<input name="_nonce" value="x"><input name="_f_secure" value="y">')
            return DummyResp("<html>Bitte erneut anmelden</html>", url="/webinfo/account/")
        def post(self, url, data=None, allow_redirects=True, **kwargs):
            return DummyResp("", url="/account")

    assert m.fetch_html("u", "p", session=DummySession()) is None


def test_run_once_keeps_failed_discord_subject_pending(monkeypatch, tmp_path):
    m = setup_basic_env(monkeypatch)
    monkeypatch.chdir(tmp_path)

    new_data = {
        "PeriodLabels": ["H1"],
        "subjects": {
            "Mathe": {"H1Grades": ["12"], "H1Exams": [], "H1FinalGrade": None, "CurrentPeriodAverage": 12.0, "YearAverage": 12.0},
            "Physik": {"H1Grades": ["11"], "H1Exams": [], "H1FinalGrade": None, "CurrentPeriodAverage": 11.0, "YearAverage": 11.0},
        },
    }
    old = {
        "PeriodLabels": ["H1"],
        "subjects": {
            "Mathe": {"H1Grades": [], "H1Exams": [], "H1FinalGrade": None, "CurrentPeriodAverage": None, "YearAverage": None},
            "Physik": {"H1Grades": [], "H1Exams": [], "H1FinalGrade": None, "CurrentPeriodAverage": None, "YearAverage": None},
        },
    }
    m.USERS[:] = [{"name": "Test", "username": "u", "password": "p"}]
    m.old_data = {"Test": old}
    monkeypatch.setattr(m, "fetch_html", lambda username, password, session=None: new_data)

    sent = []
    def fake_send(msg):
        sent.append(msg)
        return "Mathe" in msg
    monkeypatch.setattr(m, "_send_discord_message", fake_send)
    monkeypatch.setattr(m.time, "sleep", lambda _: None)

    m.run_once()

    stored = json.loads((tmp_path / "old_grades_Test.json").read_text(encoding="utf-8"))
    assert stored["subjects"]["Mathe"]["H1Grades"] == ["12"]
    assert stored["subjects"]["Physik"]["H1Grades"] == []
    assert json.loads((tmp_path / "grades_Test.json").read_text(encoding="utf-8")) == new_data
    assert len(sent) == 2

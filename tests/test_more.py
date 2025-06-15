import importlib
import json
from bs4 import BeautifulSoup
import os
import sys
import pathlib
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import main


def setup_basic_env(monkeypatch):
    monkeypatch.setenv("USER1", "Test")
    monkeypatch.setenv("USERNAME1", "u")
    monkeypatch.setenv("PASSWORD1", "p")
    monkeypatch.setenv("DISCORD_TOKEN", "t")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "1")
    monkeypatch.delenv("DEBUG_LOCAL", raising=False)
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


def test_check_env_missing(monkeypatch):
    monkeypatch.setenv("USER1", "Test")
    monkeypatch.setenv("USERNAME1", "u")
    monkeypatch.setenv("PASSWORD1", "p")
    monkeypatch.delenv("DISCORD_CHANNEL_ID", raising=False)
    monkeypatch.setenv("DISCORD_TOKEN", "t")
    importlib.invalidate_caches()
    with pytest.raises(SystemExit):
        importlib.reload(main)


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
        def get(self, url):
            self.calls.append(("get", url))
            if "webinfo" in url and "account" not in url:
                return DummyResp('<input name="_nonce" value="x"><input name="_f_secure" value="y">')
            return DummyResp(html)
        def post(self, url, data=None, allow_redirects=True):
            self.calls.append(("post", url))
            return DummyResp("", url="/account")

    session = DummySession()
    data = m.fetch_html("u", "p", session=session)
    assert "Deutsch" in data["subjects"]
    assert any(c[0] == "post" for c in session.calls)

import inspect
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"


def run_main(argv):
    from csv_tool.cli import main

    return main(argv)


def write_csv(path, text, newline="\n"):
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))
    return path


def expected_bytes(rows):
    return (json.dumps(rows, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def numbers_in(message, *paths):
    for p in paths:
        message = message.replace(str(p), "")
    return [int(n) for n in re.findall(r"\d+", message)]


def assert_clean_error(capsys, code):
    out, err = capsys.readouterr()
    assert code == 1
    assert out == ""
    assert err.startswith("error:")
    assert "Traceback" not in err
    assert len(err.strip().splitlines()) == 1
    return err


SAMPLE = "name,age,city\nAlice,30,Paris\nBob,25,Berlin\n"
SEMI = "name;age;city\nAlice;30;Paris\nBob;25;Berlin\n"
TABS = "name\tage\tcity\nAlice\t30\tParis\nBob\t25\tBerlin\n"
SAMPLE_ROWS = [
    {"name": "Alice", "age": "30", "city": "Paris"},
    {"name": "Bob", "age": "25", "city": "Berlin"},
]


def assert_sample_output(capsys, code):
    out, err = capsys.readouterr()
    assert code == 0
    assert err == ""
    data = json.loads(out)
    assert data == SAMPLE_ROWS
    for obj in data:
        assert list(obj) == ["name", "age", "city"]
        assert all(isinstance(v, str) for v in obj.values())
    return out


# AC-1


@pytest.mark.parametrize("flag", ["-d", "--delimiter"])
def test_semicolon_delimiter(tmp_path, capsys, flag):
    src = write_csv(tmp_path / "in.csv", SEMI)
    code = run_main([str(src), flag, ";"])
    assert_sample_output(capsys, code)


def test_delimiter_option_before_input(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", SEMI)
    code = run_main(["-d", ";", str(src)])
    assert_sample_output(capsys, code)


def test_delimiter_equals_form(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", SEMI)
    code = run_main([str(src), "--delimiter=;"])
    assert_sample_output(capsys, code)


@pytest.mark.parametrize("delim", ["|", ":", " "])
def test_other_single_character_delimiters(tmp_path, capsys, delim):
    src = write_csv(tmp_path / "in.csv", SAMPLE.replace(",", delim))
    code = run_main([str(src), "-d", delim])
    assert_sample_output(capsys, code)


# AC-2


@pytest.mark.parametrize("delim", ["\t", "\\t"], ids=["literal_tab", "escape_tab"])
def test_tab_delimiter(tmp_path, capsys, delim):
    src = write_csv(tmp_path / "in.csv", TABS)
    code = run_main([str(src), "-d", delim])
    assert_sample_output(capsys, code)


@pytest.mark.parametrize("delim", ["\t", "\\t"], ids=["literal_tab", "escape_tab"])
def test_tab_delimiter_long_flag(tmp_path, capsys, delim):
    src = write_csv(tmp_path / "in.csv", TABS)
    code = run_main([str(src), "--delimiter", delim])
    assert_sample_output(capsys, code)


# AC-3


def test_default_output_bytes_unchanged(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    assert run_main([str(src)]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert out.encode("utf-8") == expected_bytes(SAMPLE_ROWS)


@pytest.mark.parametrize("flag", ["-d", "--delimiter"])
def test_explicit_comma_matches_default(tmp_path, capsys, flag):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    assert run_main([str(src)]) == 0
    default_out, _ = capsys.readouterr()
    code = run_main([str(src), flag, ","])
    out, err = capsys.readouterr()
    assert code == 0
    assert err == ""
    assert out == default_out
    assert out.encode("utf-8") == expected_bytes(SAMPLE_ROWS)


def test_default_does_not_split_on_semicolon(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", "a;b\n1;2\n")
    assert run_main([str(src)]) == 0
    out, _ = capsys.readouterr()
    assert json.loads(out) == [{"a;b": "1;2"}]


# AC-4


def test_quoting_with_semicolon_delimiter(tmp_path, capsys):
    text = (
        "name;quote;note\n"
        '"Smith; J";"say ""hi""";"line one\nline two"\n'
        "plain;x;y\n"
    )
    src = write_csv(tmp_path / "in.csv", text)
    code = run_main([str(src), "-d", ";"])
    out, err = capsys.readouterr()
    assert code == 0
    assert err == ""
    assert json.loads(out) == [
        {"name": "Smith; J", "quote": 'say "hi"', "note": "line one\nline two"},
        {"name": "plain", "quote": "x", "note": "y"},
    ]


def test_commas_are_literal_with_semicolon_delimiter(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", "x;y\na,b;c\n")
    code = run_main([str(src), "-d", ";"])
    out, err = capsys.readouterr()
    assert code == 0
    assert err == ""
    assert json.loads(out) == [{"x": "a,b", "y": "c"}]


# AC-5


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_blank_and_whitespace_lines_skipped_with_semicolon(tmp_path, capsys, newline):
    text = (
        "\n  \n"
        "name;age;city\n\n   \nAlice;30;Paris\n\t\n\nBob;25;Berlin\n \t \n\n"
    )
    src = write_csv(tmp_path / "in.csv", text, newline)
    code = run_main([str(src), "-d", ";"])
    assert_sample_output(capsys, code)


def test_blank_lines_skipped_with_tab(tmp_path, capsys):
    text = "\n   \n" + TABS.replace("\nBob", "\n\n  \nBob") + "\n"
    src = write_csv(tmp_path / "in.csv", text)
    code = run_main([str(src), "-d", "\\t"])
    assert_sample_output(capsys, code)


def test_delimiter_only_line_is_a_real_row_with_semicolon(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", "a;b;c\n;;\n")
    code = run_main([str(src), "-d", ";"])
    out, err = capsys.readouterr()
    assert code == 0
    assert err == ""
    assert json.loads(out) == [{"a": "", "b": "", "c": ""}]


def test_tab_only_line_is_a_real_row_with_tab(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", "a\tb\tc\n\t\t\n")
    code = run_main([str(src), "-d", "\t"])
    out, err = capsys.readouterr()
    assert code == 0
    assert err == ""
    assert json.loads(out) == [{"a": "", "b": "", "c": ""}]


# AC-6


def test_too_many_fields_with_semicolon(tmp_path, capsys):
    # header line 1, bad row on line 5: expected 3, actual 4
    text = "name;age;city\nAlice;x;Paris\n\nBob;y;Berlin\nEve;z;Rome;extra\n"
    src = write_csv(tmp_path / "in.csv", text)
    code = run_main([str(src), "-d", ";"])
    err = assert_clean_error(capsys, code)
    nums = numbers_in(err, src)
    for n in (5, 3, 4):
        assert n in nums


def test_too_few_fields_with_tab(tmp_path, capsys):
    # header line 1, bad row on line 7: expected 4, actual 2
    text = "a\tb\tc\td\np\tq\tr\ts\n\np\tq\tr\ts\n  \np\tq\tr\ts\np\tq\n"
    src = write_csv(tmp_path / "in.csv", text)
    code = run_main([str(src), "-d", "\\t"])
    err = assert_clean_error(capsys, code)
    nums = numbers_in(err, src)
    for n in (7, 4, 2):
        assert n in nums


def test_fields_are_counted_with_chosen_delimiter(tmp_path, capsys):
    # commas do not split under -d ';': line 3 has 3 fields, header has 2
    text = "x;y\na,b,c;d\ne;f;g\n"
    src = write_csv(tmp_path / "in.csv", text)
    code = run_main([str(src), "-d", ";"])
    err = assert_clean_error(capsys, code)
    nums = numbers_in(err, src)
    for n in (3, 2):
        assert n in nums


def test_line_number_counts_multiline_fields_with_semicolon(tmp_path, capsys):
    # quoted field spans lines 2-4, good row on line 5, bad row on line 6
    text = 'a;b;c\np;"one\ntwo\nthree";r\np;q;r\np;q\n'
    src = write_csv(tmp_path / "in.csv", text)
    code = run_main([str(src), "-d", ";"])
    err = assert_clean_error(capsys, code)
    nums = numbers_in(err, src)
    for n in (6, 3, 2):
        assert n in nums


@pytest.mark.parametrize("existing", [False, True])
def test_bad_row_with_semicolon_leaves_output_alone(tmp_path, capsys, existing):
    src = write_csv(tmp_path / "in.csv", "a;b;c\np;q;r\np;q\n")
    dest = tmp_path / "OUT.json"
    if existing:
        dest.write_text("original contents\n", encoding="utf-8")
    code = run_main([str(src), "-d", ";", "-o", str(dest)])
    assert_clean_error(capsys, code)
    if existing:
        assert dest.read_text(encoding="utf-8") == "original contents\n"
    else:
        assert not dest.exists()


@pytest.mark.parametrize("text", ["a;b;c\n", "a;b;c", "a;b;c\n\n  \n"])
def test_header_only_with_semicolon_gives_empty_array(tmp_path, capsys, text):
    src = write_csv(tmp_path / "in.csv", text)
    code = run_main([str(src), "-d", ";"])
    out, err = capsys.readouterr()
    assert code == 0
    assert err == ""
    assert json.loads(out) == []


@pytest.mark.parametrize("text", ["", "\n\n", "  \n\t\n"])
def test_no_header_with_semicolon_is_error(tmp_path, capsys, text):
    src = write_csv(tmp_path / "in.csv", text)
    code = run_main([str(src), "-d", ";"])
    err = assert_clean_error(capsys, code)
    assert "header" in err.lower()


# AC-7


INVALID = ["", ";;", "ab", '"', "\n", "\r", "\\n", "\\x09", "tab"]


@pytest.mark.parametrize("value", INVALID, ids=repr)
@pytest.mark.parametrize("flag", ["-d", "--delimiter"])
def test_invalid_delimiter_is_usage_error(tmp_path, capsys, flag, value):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    dest = tmp_path / "OUT.json"
    with pytest.raises(SystemExit) as exc:
        run_main([str(src), "-o", str(dest), flag, value])
    out, err = capsys.readouterr()
    assert exc.value.code == 2
    assert out == ""
    assert "delimiter" in err.lower()
    assert "Traceback" not in err
    assert not dest.exists()


@pytest.mark.parametrize("flag", ["-d", "--delimiter"])
def test_delimiter_requires_value(tmp_path, capsys, flag):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    with pytest.raises(SystemExit) as exc:
        run_main([str(src), flag])
    out, err = capsys.readouterr()
    assert exc.value.code == 2
    assert out == ""
    assert "delimiter" in err.lower()


# AC-8


def test_help_lists_delimiter_option(capsys):
    with pytest.raises(SystemExit) as exc:
        run_main(["--help"])
    out, _ = capsys.readouterr()
    assert exc.value.code == 0
    assert re.search(r"(?<![\w-])-d\b", out)
    assert "--delimiter" in out


# AC-9


def _run_module(args, cwd):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_DIR)
    return subprocess.run(
        [sys.executable, "-m", "csv_tool", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd,
        env=env,
        timeout=60,
    )


def test_subprocess_semicolon(tmp_path):
    src = write_csv(tmp_path / "in.csv", SEMI)
    result = _run_module(["-d", ";", str(src)], tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout) == SAMPLE_ROWS


def test_subprocess_tab_escape(tmp_path):
    src = write_csv(tmp_path / "in.csv", TABS)
    result = _run_module(["-d", "\\t", str(src)], tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == SAMPLE_ROWS


def test_subprocess_semicolon_with_output(tmp_path):
    src = write_csv(tmp_path / "in.csv", SEMI)
    dest = tmp_path / "out.json"
    result = _run_module(["-d", ";", str(src), "-o", str(dest)], tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""
    assert dest.read_bytes() == expected_bytes(SAMPLE_ROWS)


def test_subprocess_invalid_delimiter(tmp_path):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    result = _run_module(["-d", ";;", str(src)], tmp_path)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "delimiter" in result.stderr.lower()
    assert "Traceback" not in result.stderr


# AC-10


def test_main_signature_unchanged():
    from csv_tool.cli import main

    params = inspect.signature(main).parameters
    assert list(params) == ["argv"]
    assert params["argv"].default is None


def test_read_rows_defaults_to_comma(tmp_path):
    from csv_tool.cli import read_rows

    src = write_csv(tmp_path / "in.csv", SAMPLE)
    assert read_rows(str(src)) == SAMPLE_ROWS


def test_read_rows_accepts_delimiter(tmp_path):
    from csv_tool.cli import read_rows

    params = inspect.signature(read_rows).parameters
    assert "delimiter" in params
    assert params["delimiter"].default == ","
    src = write_csv(tmp_path / "in.csv", SEMI)
    assert read_rows(str(src), delimiter=";") == SAMPLE_ROWS

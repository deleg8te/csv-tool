import importlib
import importlib.util
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
    return err


SAMPLE = "name,age,city\nAlice,30,Paris\nBob,25,Berlin\n"
SAMPLE_ROWS = [
    {"name": "Alice", "age": "30", "city": "Paris"},
    {"name": "Bob", "age": "25", "city": "Berlin"},
]


# AC-1


def test_main_is_importable_function_with_optional_argv():
    from csv_tool.cli import main

    assert callable(main)
    params = inspect.signature(main).parameters
    assert list(params) == ["argv"]
    assert params["argv"].default is None


def test_dunder_main_exists_and_raises_systemexit_of_main():
    spec = importlib.util.find_spec("csv_tool.__main__")
    assert spec is not None and spec.origin is not None
    source = Path(spec.origin).read_text(encoding="utf-8")
    assert "raise SystemExit(main())" in source


def test_missing_input_argument_is_usage_error(capsys):
    with pytest.raises(SystemExit) as exc:
        run_main([])
    assert exc.value.code == 2


def test_output_option_requires_value(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    with pytest.raises(SystemExit) as exc:
        run_main([str(src), "-o"])
    assert exc.value.code == 2


def test_main_with_none_uses_sys_argv(tmp_path, capsys, monkeypatch):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    monkeypatch.setattr(sys, "argv", ["csv_tool", str(src)])
    assert run_main(None) == 0
    assert json.loads(capsys.readouterr().out) == SAMPLE_ROWS


# AC-2


def test_converts_rows_to_json_on_stdout(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    code = run_main([str(src)])
    out, err = capsys.readouterr()
    assert code == 0
    assert err == ""
    data = json.loads(out)
    assert data == SAMPLE_ROWS
    for obj in data:
        assert list(obj) == ["name", "age", "city"]
        assert all(isinstance(v, str) for v in obj.values())


# AC-3


@pytest.mark.parametrize("flag", ["-o", "--output"])
def test_writes_json_to_output_file(tmp_path, capsys, flag):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    dest = tmp_path / "OUT.json"
    code = run_main([str(src), flag, str(dest)])
    out, err = capsys.readouterr()
    assert code == 0
    assert out.strip() == ""
    assert err == ""
    assert json.loads(dest.read_text(encoding="utf-8")) == SAMPLE_ROWS


# AC-4


def test_quoted_fields_are_unquoted(tmp_path, capsys):
    text = (
        "name,quote,note\n"
        '"Smith, J","say ""hi""","line one\nline two"\n'
        "plain,x,y\n"
    )
    src = write_csv(tmp_path / "in.csv", text)
    code = run_main([str(src)])
    out, _ = capsys.readouterr()
    assert code == 0
    assert json.loads(out) == [
        {"name": "Smith, J", "quote": 'say "hi"', "note": "line one\nline two"},
        {"name": "plain", "quote": "x", "note": "y"},
    ]


def test_non_ascii_round_trips(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", "name,city\nZoë,東京\n")
    code = run_main([str(src)])
    out, _ = capsys.readouterr()
    assert code == 0
    assert json.loads(out) == [{"name": "Zoë", "city": "東京"}]


def test_non_ascii_round_trips_to_output_file(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", "name,city\nZoë,東京\n")
    dest = tmp_path / "out.json"
    assert run_main([str(src), "-o", str(dest)]) == 0
    data = json.loads(dest.read_bytes().decode("utf-8"))
    assert data == [{"name": "Zoë", "city": "東京"}]


def test_leading_bom_is_tolerated(tmp_path, capsys):
    src = tmp_path / "in.csv"
    src.write_bytes(b"\xef\xbb\xbf" + "name,city\nZoë,東京\n".encode("utf-8"))
    code = run_main([str(src)])
    out, _ = capsys.readouterr()
    assert code == 0
    assert json.loads(out) == [{"name": "Zoë", "city": "東京"}]


# AC-5


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_blank_lines_are_skipped(tmp_path, capsys, newline):
    text = "name,age,city\n\nAlice,30,Paris\n\n\nBob,25,Berlin\n\n"
    src = write_csv(tmp_path / "in.csv", text, newline)
    code = run_main([str(src)])
    out, err = capsys.readouterr()
    assert code == 0
    assert err == ""
    assert json.loads(out) == SAMPLE_ROWS


def test_two_rows_plus_three_blank_lines_yield_two_objects(tmp_path, capsys):
    text = "name,age,city\nAlice,30,Paris\n\nBob,25,Berlin\n\n\n"
    src = write_csv(tmp_path / "in.csv", text)
    code = run_main([str(src)])
    out, _ = capsys.readouterr()
    assert code == 0
    assert len(json.loads(out)) == 2


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_whitespace_only_lines_are_skipped(tmp_path, capsys, newline):
    text = "name,age,city\n   \nAlice,30,Paris\n\t\n \t \nBob,25,Berlin\n  \n"
    src = write_csv(tmp_path / "in.csv", text, newline)
    code = run_main([str(src)])
    out, err = capsys.readouterr()
    assert code == 0
    assert err == ""
    assert json.loads(out) == SAMPLE_ROWS


def test_blank_lines_before_header_are_skipped(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", "\n  \n" + SAMPLE)
    code = run_main([str(src)])
    out, _ = capsys.readouterr()
    assert code == 0
    assert json.loads(out) == SAMPLE_ROWS


def test_blank_line_inside_quoted_field_is_kept(tmp_path, capsys):
    text = 'a,b\n"top\n\nbottom",z\n"x\n   \ny",w\n'
    src = write_csv(tmp_path / "in.csv", text)
    code = run_main([str(src)])
    out, _ = capsys.readouterr()
    assert code == 0
    assert json.loads(out) == [
        {"a": "top\n\nbottom", "b": "z"},
        {"a": "x\n   \ny", "b": "w"},
    ]


def test_delimiter_only_line_is_a_real_row(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", "a,b,c\n,,\n")
    code = run_main([str(src)])
    out, _ = capsys.readouterr()
    assert code == 0
    assert json.loads(out) == [{"a": "", "b": "", "c": ""}]


# AC-6


def test_missing_input_file(tmp_path, capsys):
    missing = tmp_path / "does_not_exist.csv"
    code = run_main([str(missing)])
    err = assert_clean_error(capsys, code)
    assert str(missing) in err
    assert len(err.strip().splitlines()) == 1


def test_missing_input_file_does_not_create_output(tmp_path, capsys):
    missing = tmp_path / "does_not_exist.csv"
    dest = tmp_path / "OUT.json"
    code = run_main([str(missing), "-o", str(dest)])
    assert_clean_error(capsys, code)
    assert not dest.exists()


def test_directory_as_input_is_reported_cleanly(tmp_path, capsys):
    folder = tmp_path / "adir"
    folder.mkdir()
    code = run_main([str(folder)])
    err = assert_clean_error(capsys, code)
    assert str(folder) in err


def test_unwritable_output_is_reported_cleanly(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    dest = tmp_path / "no_such_dir" / "out.json"
    code = run_main([str(src), "-o", str(dest)])
    assert_clean_error(capsys, code)


# AC-7


def test_row_with_too_many_fields(tmp_path, capsys):
    # header line 1, bad row on line 5: expected 3, actual 4
    text = "name,age,city\nAlice,x,Paris\n\nBob,y,Berlin\nEve,z,Rome,extra\n"
    src = write_csv(tmp_path / "in.csv", text)
    code = run_main([str(src)])
    err = assert_clean_error(capsys, code)
    nums = numbers_in(err, src)
    for n in (5, 3, 4):
        assert n in nums


def test_row_with_too_few_fields(tmp_path, capsys):
    # header line 1, bad row on line 7: expected 4, actual 2
    text = "a,b,c,d\np,q,r,s\n\np,q,r,s\n  \np,q,r,s\np,q\n"
    src = write_csv(tmp_path / "in.csv", text)
    code = run_main([str(src)])
    err = assert_clean_error(capsys, code)
    nums = numbers_in(err, src)
    for n in (7, 4, 2):
        assert n in nums


def test_line_number_counts_physical_lines_of_multiline_fields(tmp_path, capsys):
    # quoted field spans lines 2-4, good row on line 5, bad row on line 6:
    # expected 3, actual 2
    text = 'a,b,c\np,"one\ntwo\nthree",r\np,q,r\np,q\n'
    src = write_csv(tmp_path / "in.csv", text)
    code = run_main([str(src)])
    err = assert_clean_error(capsys, code)
    nums = numbers_in(err, src)
    for n in (6, 3, 2):
        assert n in nums


# AC-8


def _bad_row_file(tmp_path):
    return write_csv(tmp_path / "in.csv", "a,b,c\np,q,r\np,q\n")


def test_bad_row_does_not_create_output(tmp_path, capsys):
    dest = tmp_path / "OUT.json"
    code = run_main([str(_bad_row_file(tmp_path)), "-o", str(dest)])
    assert_clean_error(capsys, code)
    assert not dest.exists()


@pytest.mark.parametrize("kind", ["bad_row", "missing", "no_header"])
def test_error_leaves_existing_output_unchanged(tmp_path, capsys, kind):
    if kind == "bad_row":
        src = _bad_row_file(tmp_path)
    elif kind == "missing":
        src = tmp_path / "missing.csv"
    else:
        src = write_csv(tmp_path / "in.csv", "\n\n")
    dest = tmp_path / "OUT.json"
    dest.write_text("original contents\n", encoding="utf-8")
    code = run_main([str(src), "-o", str(dest)])
    assert_clean_error(capsys, code)
    assert dest.read_text(encoding="utf-8") == "original contents\n"


# AC-9


@pytest.mark.parametrize("text", ["a,b,c\n", "a,b,c", "a,b,c\n\n  \n\n"])
def test_header_only_gives_empty_array(tmp_path, capsys, text):
    src = write_csv(tmp_path / "in.csv", text)
    code = run_main([str(src)])
    out, err = capsys.readouterr()
    assert code == 0
    assert err == ""
    assert json.loads(out) == []


@pytest.mark.parametrize("text", ["", "\n\n\n", "  \n\t\n", "\r\n\r\n"])
def test_file_without_header_is_error(tmp_path, capsys, text):
    src = write_csv(tmp_path / "in.csv", text)
    code = run_main([str(src)])
    err = assert_clean_error(capsys, code)
    assert "header" in err.lower()


# AC-10


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


def test_subprocess_good_file(tmp_path):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    result = _run_module([str(src)], tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == SAMPLE_ROWS


def test_subprocess_missing_file(tmp_path):
    result = _run_module([str(tmp_path / "missing.csv")], tmp_path)
    assert result.returncode != 0
    assert result.stderr.startswith("error:")
    assert "Traceback" not in result.stderr
    assert result.stdout == ""


# --version: AC-1, AC-3


def test_version_option_prints_version_and_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        run_main(["--version"])
    out, err = capsys.readouterr()
    assert exc.value.code == 0
    assert out == "csv_tool 0.1.0\n"
    assert err == ""


def test_version_option_does_not_require_input(capsys):
    with pytest.raises(SystemExit) as exc:
        run_main(["--version"])
    out, err = capsys.readouterr()
    assert exc.value.code != 2
    assert "usage" not in (out + err).lower()
    assert "error" not in (out + err).lower()


# --version: AC-4


def test_version_option_with_input_does_not_convert(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    dest = tmp_path / "OUT.json"
    with pytest.raises(SystemExit) as exc:
        run_main([str(src), "-o", str(dest), "--version"])
    out, err = capsys.readouterr()
    assert exc.value.code == 0
    assert out == "csv_tool 0.1.0\n"
    assert err == ""
    assert not dest.exists()


# --version: AC-6


def test_help_lists_version_option(capsys):
    with pytest.raises(SystemExit) as exc:
        run_main(["--help"])
    out, _ = capsys.readouterr()
    assert exc.value.code == 0
    assert "--version" in out


# --version: AC-2


def test_subprocess_version(tmp_path):
    import csv_tool

    result = _run_module(["--version"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "csv_tool 0.1.0\n"
    assert result.stdout == f"csv_tool {csv_tool.__version__}\n"
    assert result.stderr == ""
    assert "Traceback" not in result.stdout + result.stderr

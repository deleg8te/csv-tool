import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"

SAMPLE = "name,age,city\nAlice,30,Paris\nBob,25,Berlin\n"
SAMPLE_KEYS = ["name", "age", "city"]
SAMPLE_ROWS = [
    {"name": "Alice", "age": "30", "city": "Paris"},
    {"name": "Bob", "age": "25", "city": "Berlin"},
]
ORIGINAL = "original contents\n"


def run_main(argv):
    from csv_tool.cli import main

    return main(argv)


def write_csv(path, text, newline="\n"):
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))
    return path


def expected_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def assert_keys_output(capsys, code, keys):
    out, err = capsys.readouterr()
    assert code == 0, err
    assert err == ""
    assert out.encode("utf-8") == expected_bytes(keys)
    return out


def assert_clean_error(capsys, code):
    out, err = capsys.readouterr()
    assert code == 1
    assert out == ""
    assert err.startswith("error:")
    assert "Traceback" not in err
    assert len(err.strip().splitlines()) == 1
    return err


def listing(directory):
    return sorted(p.name for p in Path(directory).iterdir())


def same_path(a, b):
    return os.path.abspath(os.fspath(a)) == os.path.abspath(os.fspath(b))


def spy_replace(monkeypatch):
    calls = []
    real_replace = os.replace

    def fake_replace(src, dst, *args, **kwargs):
        calls.append(
            {"src": os.fspath(src), "dst": os.fspath(dst), "content": Path(src).read_bytes()}
        )
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", fake_replace)
    return calls


# AC-1


def test_keys_prints_header_as_json_array(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    code = run_main([str(src), "--keys"])
    out = assert_keys_output(capsys, code, SAMPLE_KEYS)
    data = json.loads(out)
    assert data == SAMPLE_KEYS
    assert all(isinstance(k, str) for k in data)
    assert "Alice" not in out
    assert "Bob" not in out
    assert "{" not in out


# AC-2


def test_keys_position_does_not_matter(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    code_before = run_main(["--keys", str(src)])
    out_before = assert_keys_output(capsys, code_before, SAMPLE_KEYS)
    code_after = run_main([str(src), "--keys"])
    out_after = assert_keys_output(capsys, code_after, SAMPLE_KEYS)
    assert out_before == out_after


# AC-3


@pytest.mark.parametrize(
    "header, keys",
    [
        ("z,a,m", ["z", "a", "m"]),
        ("a,b,a", ["a", "b", "a"]),
        ("x,x,x", ["x", "x", "x"]),
    ],
)
def test_keys_keep_file_order_and_duplicates(tmp_path, capsys, header, keys):
    src = write_csv(tmp_path / "in.csv", header + "\n1,2,3\n")
    code = run_main([str(src), "--keys"])
    assert_keys_output(capsys, code, keys)


# AC-4


def test_quoted_header_names_are_unquoted(tmp_path, capsys):
    text = '"Smith, J","say ""hi""",x,"line one\nline two"\n1,2,3,4\n'
    src = write_csv(tmp_path / "in.csv", text)
    code = run_main([str(src), "--keys"])
    assert_keys_output(capsys, code, ["Smith, J", 'say "hi"', "x", "line one\nline two"])


def test_non_ascii_header_is_literal_utf8(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", "Zoë,東京\na,b\n")
    code = run_main([str(src), "--keys"])
    out = assert_keys_output(capsys, code, ["Zoë", "東京"])
    assert "Zoë" in out
    assert "東京" in out
    assert "\\u" not in out


def test_leading_bom_is_not_part_of_first_key(tmp_path, capsys):
    src = tmp_path / "in.csv"
    src.write_bytes(b"\xef\xbb\xbf" + "name,city\nZoë,東京\n".encode("utf-8"))
    code = run_main([str(src), "--keys"])
    out = assert_keys_output(capsys, code, ["name", "city"])
    assert "﻿" not in out


def test_surrounding_whitespace_is_kept(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", " name,age ,  city  \n1,2,3\n")
    code = run_main([str(src), "--keys"])
    assert_keys_output(capsys, code, [" name", "age ", "  city  "])


# AC-5


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_blank_and_whitespace_lines_before_header_skipped(tmp_path, capsys, newline):
    src = write_csv(tmp_path / "in.csv", "\n  \n\t\n\n" + SAMPLE, newline)
    code = run_main([str(src), "--keys"])
    assert_keys_output(capsys, code, SAMPLE_KEYS)


# AC-6


@pytest.mark.parametrize(
    "text", ["a,b,c\n", "a,b,c", "a,b,c\n\n  \n\n", "a,b,c\r\n\r\n"]
)
def test_header_only_file_gives_keys(tmp_path, capsys, text):
    src = write_csv(tmp_path / "in.csv", text)
    code = run_main([str(src), "--keys"])
    out = assert_keys_output(capsys, code, ["a", "b", "c"])
    assert json.loads(out) != []


# AC-7


@pytest.mark.parametrize("flag", ["-d", "--delimiter"])
def test_keys_with_semicolon_delimiter(tmp_path, capsys, flag):
    src = write_csv(tmp_path / "in.csv", SAMPLE.replace(",", ";"))
    code = run_main([str(src), "--keys", flag, ";"])
    assert_keys_output(capsys, code, SAMPLE_KEYS)


@pytest.mark.parametrize("delim", ["\t", "\\t"], ids=["literal_tab", "escape_tab"])
def test_keys_with_tab_delimiter(tmp_path, capsys, delim):
    src = write_csv(tmp_path / "in.csv", SAMPLE.replace(",", "\t"))
    code = run_main(["--keys", "-d", delim, str(src)])
    assert_keys_output(capsys, code, SAMPLE_KEYS)


def test_keys_default_delimiter_does_not_split_on_semicolon(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", "a;b\n1;2\n")
    code = run_main([str(src), "--keys"])
    assert_keys_output(capsys, code, ["a;b"])


@pytest.mark.parametrize("value", ["", ";;", "ab", '"', "\\n"], ids=repr)
def test_keys_with_invalid_delimiter_is_usage_error(tmp_path, capsys, value):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    with pytest.raises(SystemExit) as exc:
        run_main([str(src), "--keys", "-d", value])
    out, err = capsys.readouterr()
    assert exc.value.code == 2
    assert out == ""
    assert "delimiter" in err.lower()
    assert "Traceback" not in err


# AC-8


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("flag", ["-o", "--output"])
def test_keys_to_output_file_is_atomic(tmp_path, capsys, monkeypatch, flag, existing):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "neighbour.txt").write_text("keep\n", encoding="utf-8")
    dest = out_dir / "OUT.json"
    if existing:
        dest.write_text(ORIGINAL, encoding="utf-8")
    before = listing(out_dir)
    calls = spy_replace(monkeypatch)
    code = run_main([str(src), "--keys", flag, str(dest)])
    out, err = capsys.readouterr()
    assert code == 0, err
    assert out == ""
    assert err == ""
    assert dest.read_bytes() == expected_bytes(SAMPLE_KEYS)
    assert len(calls) == 1
    call = calls[0]
    assert same_path(call["dst"], dest)
    assert not same_path(call["src"], dest)
    assert os.path.dirname(os.path.abspath(call["src"])) == str(out_dir.resolve())
    assert call["content"] == expected_bytes(SAMPLE_KEYS)
    assert listing(out_dir) == sorted(set(before) | {"OUT.json"})


# AC-9


@pytest.mark.parametrize(
    "text",
    ["a,b,c\np,q\n", "a,b,c\np,q,r,s\n", "a,b,c\np,q,r\n\np\n"],
    ids=["too_few", "too_many", "later_bad_row"],
)
def test_keys_does_not_validate_data_rows(tmp_path, capsys, text):
    src = write_csv(tmp_path / "in.csv", text)
    code = run_main([str(src), "--keys"])
    assert_keys_output(capsys, code, ["a", "b", "c"])


def test_keys_stops_reading_after_header(tmp_path, capsys):
    # Undecodable bytes far past the header would fail a full read.
    src = tmp_path / "in.csv"
    body = ("p,q,r\n" * 200_000).encode("utf-8")
    src.write_bytes(b"a,b,c\n" + body + b"\xff\xfe,bad\n")
    code = run_main([str(src), "--keys"])
    assert_keys_output(capsys, code, ["a", "b", "c"])


# AC-10


def _error_input(kind, tmp_path):
    if kind == "missing":
        return tmp_path / "missing.csv"
    if kind == "directory":
        folder = tmp_path / "adir"
        folder.mkdir()
        return folder
    if kind == "empty":
        return write_csv(tmp_path / "in.csv", "")
    return write_csv(tmp_path / "in.csv", "\n  \n\t\n\r\n")


@pytest.mark.parametrize("kind", ["missing", "directory", "empty", "blank_only"])
def test_keys_input_errors_are_clean(tmp_path, capsys, kind):
    src = _error_input(kind, tmp_path)
    code = run_main([str(src), "--keys"])
    err = assert_clean_error(capsys, code)
    if kind in ("missing", "directory"):
        assert str(src) in err
    else:
        assert "header" in err.lower()


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("kind", ["missing", "directory", "empty", "blank_only"])
def test_keys_input_errors_leave_output_alone(tmp_path, capsys, monkeypatch, kind, existing):
    src = _error_input(kind, tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    dest = out_dir / "OUT.json"
    if existing:
        dest.write_bytes(ORIGINAL.encode("utf-8"))
    before = listing(out_dir)
    calls = spy_replace(monkeypatch)
    code = run_main([str(src), "--keys", "-o", str(dest)])
    assert_clean_error(capsys, code)
    assert calls == []
    assert listing(out_dir) == before
    if existing:
        assert dest.read_bytes() == ORIGINAL.encode("utf-8")
    else:
        assert not dest.exists()


# AC-11


def test_version_takes_precedence_over_keys(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    with pytest.raises(SystemExit) as exc:
        run_main([str(src), "--keys", "--version"])
    out, err = capsys.readouterr()
    assert exc.value.code == 0
    assert out == "csv_tool 0.1.0\n"
    assert err == ""


# AC-12


def test_help_lists_keys_option(capsys):
    with pytest.raises(SystemExit) as exc:
        run_main(["--help"])
    out, _ = capsys.readouterr()
    assert exc.value.code == 0
    assert "--keys" in out


# AC-13


def _run_module(args, cwd, **extra_env):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_DIR)
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "csv_tool", *args],
        capture_output=True,
        cwd=cwd,
        env=env,
        timeout=60,
    )


def test_subprocess_keys(tmp_path):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    result = _run_module(["--keys", str(src)], tmp_path)
    stderr = result.stderr.decode("utf-8", "replace")
    assert result.returncode == 0, stderr
    assert stderr == ""
    assert json.loads(result.stdout.decode("utf-8")) == SAMPLE_KEYS


def test_subprocess_keys_ascii_stdout_encoding_emits_utf8(tmp_path):
    src = write_csv(tmp_path / "in.csv", "Zoë,東京\na,b\n")
    result = _run_module(["--keys", str(src)], tmp_path, PYTHONIOENCODING="ascii")
    stderr = result.stderr.decode("utf-8", "replace")
    assert result.returncode == 0, stderr
    assert stderr == ""
    assert result.stdout == expected_bytes(["Zoë", "東京"])


# AC-14


def test_without_keys_conversion_is_unchanged(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    code = run_main([str(src)])
    out, err = capsys.readouterr()
    assert code == 0
    assert err == ""
    assert out.encode("utf-8") == expected_bytes(SAMPLE_ROWS)


def test_signatures_unchanged():
    from csv_tool.cli import main, read_rows

    params = inspect.signature(main).parameters
    assert list(params) == ["argv"]
    assert params["argv"].default is None
    params = inspect.signature(read_rows).parameters
    assert list(params) == ["path", "delimiter"]
    assert params["delimiter"].default == ","

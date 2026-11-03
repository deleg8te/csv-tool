import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"

SAMPLE = "name,age,city\nAlice,30,Paris\nBob,25,Berlin\n"
SAMPLE_ROWS = [
    {"name": "Alice", "age": "30", "city": "Paris"},
    {"name": "Bob", "age": "25", "city": "Berlin"},
]
SAMPLE_COMPACT = (
    '[{"name":"Alice","age":"30","city":"Paris"},'
    '{"name":"Bob","age":"25","city":"Berlin"}]\n'
)
NON_ASCII = "name,city\nZoë,東京\n"
NON_ASCII_ROWS = [{"name": "Zoë", "city": "東京"}]
NON_ASCII_COMPACT = '[{"name":"Zoë","city":"東京"}]\n'
MULTILINE = 'name,note\n"Smith, J","line one\nline two"\nplain,"a\r\nb"\n'
MULTILINE_ROWS = [
    {"name": "Smith, J", "note": "line one\nline two"},
    {"name": "plain", "note": "a\r\nb"},
]
ORIGINAL = "original contents\n"


def run_main(argv):
    from csv_tool.cli import main

    return main(argv)


def write_csv(path, text):
    path.write_bytes(text.encode("utf-8"))
    return path


def compact_bytes(rows):
    return (
        json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def indented_bytes(rows):
    return (json.dumps(rows, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def assert_clean_error(capsys, code):
    out, err = capsys.readouterr()
    assert code == 1
    assert out == ""
    assert err.startswith("error:")
    assert len(err.strip().splitlines()) == 1
    assert "Traceback" not in err
    return err


def listing(directory):
    return sorted(p.name for p in Path(directory).iterdir())


def capture_stdout_bytes(monkeypatch):
    raw = io.BytesIO()
    stdout = io.TextIOWrapper(raw, encoding="ascii")
    monkeypatch.setattr(sys, "stdout", stdout)
    return raw, stdout


# AC-1


def test_compact_stdout_is_exact_single_line_json(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    code = run_main([str(src), "--compact"])
    out, err = capsys.readouterr()
    assert code == 0
    assert err == ""
    assert out == SAMPLE_COMPACT
    assert out.encode("utf-8") == compact_bytes(SAMPLE_ROWS)


# AC-2


@pytest.mark.parametrize(
    "text,rows",
    [(SAMPLE, SAMPLE_ROWS), (MULTILINE, MULTILINE_ROWS)],
    ids=["sample", "embedded_newlines"],
)
def test_compact_output_is_one_line_and_round_trips(tmp_path, capsys, text, rows):
    src = write_csv(tmp_path / "in.csv", text)
    code = run_main([str(src), "--compact"])
    out, err = capsys.readouterr()
    assert code == 0
    assert err == ""
    assert out.count("\n") == 1
    assert out.endswith("\n")
    assert "\r" not in out
    assert len(out.splitlines()) == 1
    assert json.loads(out) == rows
    assert out.encode("utf-8") == compact_bytes(rows)


def test_compact_escapes_embedded_newlines(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", MULTILINE)
    assert run_main([str(src), "--compact"]) == 0
    out, _ = capsys.readouterr()
    assert '"line one\\nline two"' in out


# AC-3


def test_compact_non_ascii_stdout_bytes_are_utf8(tmp_path, monkeypatch):
    src = write_csv(tmp_path / "in.csv", NON_ASCII)
    raw, stdout = capture_stdout_bytes(monkeypatch)
    code = run_main([str(src), "--compact"])
    stdout.flush()
    assert code == 0
    assert raw.getvalue() == NON_ASCII_COMPACT.encode("utf-8")


def test_compact_non_ascii_capsys(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", NON_ASCII)
    assert run_main([str(src), "--compact"]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert out == NON_ASCII_COMPACT
    assert "\\u" not in out


# AC-4


@pytest.mark.parametrize("flag", ["-o", "--output"])
@pytest.mark.parametrize(
    "text,expected",
    [(SAMPLE, SAMPLE_COMPACT), (NON_ASCII, NON_ASCII_COMPACT)],
    ids=["sample", "non_ascii"],
)
def test_compact_output_file_bytes(tmp_path, capsys, flag, text, expected):
    src = write_csv(tmp_path / "in.csv", text)
    dest = tmp_path / "out.json"
    code = run_main([str(src), "--compact", flag, str(dest)])
    out, err = capsys.readouterr()
    assert code == 0
    assert out == ""
    assert err == ""
    assert dest.read_bytes() == expected.encode("utf-8")


def test_compact_output_file_goes_through_os_replace(tmp_path, capsys, monkeypatch):
    src = write_csv(tmp_path / "in.csv", NON_ASCII)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    dest = out_dir / "OUT.json"
    dest.write_text(ORIGINAL, encoding="utf-8")
    calls = []
    real_replace = os.replace

    def fake_replace(src_path, dst_path, *args, **kwargs):
        calls.append((os.fspath(src_path), os.fspath(dst_path), Path(src_path).read_bytes()))
        return real_replace(src_path, dst_path, *args, **kwargs)

    monkeypatch.setattr(os, "replace", fake_replace)
    assert run_main([str(src), "--compact", "-o", str(dest)]) == 0
    assert len(calls) == 1
    tmp, dst, content = calls[0]
    assert os.path.abspath(dst) == str(dest.resolve())
    assert os.path.abspath(tmp) != str(dest.resolve())
    assert os.path.dirname(os.path.abspath(tmp)) == str(out_dir.resolve())
    assert content == NON_ASCII_COMPACT.encode("utf-8")
    assert dest.read_bytes() == NON_ASCII_COMPACT.encode("utf-8")
    assert listing(out_dir) == ["OUT.json"]


# AC-5


@pytest.mark.parametrize("text,rows", [(SAMPLE, SAMPLE_ROWS), (NON_ASCII, NON_ASCII_ROWS)])
def test_default_stdout_stays_indented(tmp_path, monkeypatch, text, rows):
    src = write_csv(tmp_path / "in.csv", text)
    raw, stdout = capture_stdout_bytes(monkeypatch)
    code = run_main([str(src)])
    stdout.flush()
    assert code == 0
    assert raw.getvalue() == indented_bytes(rows)


@pytest.mark.parametrize("text,rows", [(SAMPLE, SAMPLE_ROWS), (NON_ASCII, NON_ASCII_ROWS)])
def test_default_output_file_stays_indented(tmp_path, capsys, text, rows):
    src = write_csv(tmp_path / "in.csv", text)
    dest = tmp_path / "out.json"
    assert run_main([str(src), "-o", str(dest)]) == 0
    assert dest.read_bytes() == indented_bytes(rows)


def test_compact_and_default_differ_only_in_formatting(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    assert run_main([str(src)]) == 0
    default_out, _ = capsys.readouterr()
    assert run_main([str(src), "--compact"]) == 0
    compact_out, _ = capsys.readouterr()
    assert default_out.encode("utf-8") == indented_bytes(SAMPLE_ROWS)
    assert compact_out.encode("utf-8") == compact_bytes(SAMPLE_ROWS)
    assert json.loads(default_out) == json.loads(compact_out)


# AC-6


@pytest.mark.parametrize("text", ["a,b,c\n", "a,b,c", "a,b,c\n\n  \n"])
def test_compact_header_only_gives_empty_array(tmp_path, capsys, text):
    src = write_csv(tmp_path / "in.csv", text)
    code = run_main([str(src), "--compact"])
    out, err = capsys.readouterr()
    assert code == 0
    assert err == ""
    assert out == "[]\n"


# AC-7


@pytest.mark.parametrize(
    "order",
    [
        ["--compact", "IN"],
        ["IN", "--compact"],
    ],
)
def test_compact_position_stdout(tmp_path, capsys, order):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    argv = [str(src) if a == "IN" else a for a in order]
    code = run_main(argv)
    out, err = capsys.readouterr()
    assert code == 0
    assert err == ""
    assert out == SAMPLE_COMPACT


@pytest.mark.parametrize(
    "order",
    [
        ["--compact", "IN", "-o", "OUT"],
        ["IN", "--compact", "-o", "OUT"],
        ["IN", "-o", "OUT", "--compact"],
        ["-o", "OUT", "--compact", "IN"],
        ["-o", "OUT", "IN", "--compact"],
        ["--compact", "-o", "OUT", "IN"],
    ],
)
def test_compact_position_with_output(tmp_path, capsys, order):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    dest = tmp_path / "out.json"
    mapping = {"IN": str(src), "OUT": str(dest)}
    argv = [mapping.get(a, a) for a in order]
    code = run_main(argv)
    out, err = capsys.readouterr()
    assert code == 0
    assert out == ""
    assert err == ""
    assert dest.read_bytes() == SAMPLE_COMPACT.encode("utf-8")


def test_compact_takes_no_value(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    with pytest.raises(SystemExit) as exc:
        run_main([str(src), "--compact=yes"])
    assert exc.value.code == 2
    # A following positional is the input, not a value for --compact.
    assert run_main(["--compact", str(src)]) == 0
    out, _ = capsys.readouterr()
    assert out == SAMPLE_COMPACT


# AC-8


def _input_for(kind, tmp_path):
    if kind == "bad_row":
        return write_csv(tmp_path / "in.csv", "a,b,c\np,q,r\np,q\n")
    if kind == "missing":
        return tmp_path / "missing.csv"
    return write_csv(tmp_path / "in.csv", "\n\n")


@pytest.mark.parametrize("kind", ["bad_row", "missing", "no_header"])
def test_compact_errors_on_stdout_mode(tmp_path, capsys, kind):
    src = _input_for(kind, tmp_path)
    code = run_main([str(src), "--compact"])
    err = assert_clean_error(capsys, code)
    if kind == "no_header":
        assert "header" in err.lower()


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("kind", ["bad_row", "missing", "no_header"])
def test_compact_errors_leave_output_untouched(tmp_path, capsys, kind, existing):
    src = _input_for(kind, tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    dest = out_dir / "OUT.json"
    if existing:
        dest.write_text(ORIGINAL, encoding="utf-8")
    before = listing(out_dir)
    code = run_main([str(src), "--compact", "-o", str(dest)])
    assert_clean_error(capsys, code)
    assert listing(out_dir) == before
    if existing:
        assert dest.read_text(encoding="utf-8") == ORIGINAL
    else:
        assert not dest.exists()


@pytest.mark.parametrize("kind", ["bad_row", "missing", "no_header"])
def test_compact_error_message_matches_default(tmp_path, capsys, kind):
    src = _input_for(kind, tmp_path)
    default_code = run_main([str(src)])
    _, default_err = capsys.readouterr()
    compact_code = run_main([str(src), "--compact"])
    _, compact_err = capsys.readouterr()
    assert compact_code == default_code == 1
    assert compact_err == default_err


# AC-9


def test_help_lists_compact_option(capsys):
    with pytest.raises(SystemExit) as exc:
        run_main(["--help"])
    out, _ = capsys.readouterr()
    assert exc.value.code == 0
    assert "--compact" in out


# AC-10


def _run_module(args, cwd):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_DIR)
    return subprocess.run(
        [sys.executable, "-m", "csv_tool", *args],
        capture_output=True,
        cwd=cwd,
        env=env,
        timeout=60,
    )


@pytest.mark.parametrize(
    "text,expected",
    [(SAMPLE, SAMPLE_COMPACT), (NON_ASCII, NON_ASCII_COMPACT)],
    ids=["sample", "non_ascii"],
)
def test_subprocess_compact(tmp_path, text, expected):
    src = write_csv(tmp_path / "in.csv", text)
    result = _run_module([str(src), "--compact"], tmp_path)
    stderr = result.stderr.decode("utf-8", "replace")
    assert result.returncode == 0, stderr
    assert stderr == ""
    assert result.stdout == expected.encode("utf-8")
    assert result.stdout.count(b"\n") == 1

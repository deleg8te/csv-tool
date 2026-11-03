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
NON_ASCII_COMPACT = '[{"name":"Zoë","city":"東京"}]\n'.encode("utf-8")
MULTILINE = 'name,note\n"Smith, J","line one\nline two"\nplain,y\n'
MULTILINE_ROWS = [
    {"name": "Smith, J", "note": "line one\nline two"},
    {"name": "plain", "note": "y"},
]
ORIGINAL = "original contents\n"


def run_main(argv):
    from csv_tool.cli import main

    return main(argv)


def write_csv(path, text):
    path.write_bytes(text.encode("utf-8"))
    return path


def compact_bytes(rows):
    text = json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + "\n"
    return text.encode("utf-8")


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


def run_to_bytes(monkeypatch, argv):
    raw = io.BytesIO()
    stdout = io.TextIOWrapper(raw, encoding="ascii")
    monkeypatch.setattr(sys, "stdout", stdout)
    code = run_main(argv)
    stdout.flush()
    return code, raw.getvalue()


# AC-1


def test_compact_sample_stdout_is_exact(tmp_path, capsys):
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
    [(SAMPLE, SAMPLE_ROWS), (MULTILINE, MULTILINE_ROWS), (NON_ASCII, NON_ASCII_ROWS)],
)
def test_compact_output_is_a_single_line(tmp_path, capsys, text, rows):
    src = write_csv(tmp_path / "in.csv", text)
    code = run_main([str(src), "--compact"])
    out, err = capsys.readouterr()
    assert code == 0
    assert err == ""
    assert out.count("\n") == 1
    assert out.endswith("\n")
    assert "\r" not in out
    assert json.loads(out) == rows


def test_compact_escapes_embedded_newlines(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", MULTILINE)
    assert run_main([str(src), "--compact"]) == 0
    out, _ = capsys.readouterr()
    assert "line one\\nline two" in out
    assert out.encode("utf-8") == compact_bytes(MULTILINE_ROWS)


# AC-3


def test_compact_non_ascii_stdout_bytes(tmp_path, monkeypatch):
    src = write_csv(tmp_path / "in.csv", NON_ASCII)
    code, data = run_to_bytes(monkeypatch, [str(src), "--compact"])
    assert code == 0
    assert data == NON_ASCII_COMPACT


def test_compact_non_ascii_capsys(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", NON_ASCII)
    assert run_main([str(src), "--compact"]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert out.encode("utf-8") == NON_ASCII_COMPACT
    assert "\\u" not in out


# AC-4


@pytest.mark.parametrize("flag", ["-o", "--output"])
@pytest.mark.parametrize(
    "text,expected",
    [(SAMPLE, SAMPLE_COMPACT.encode("utf-8")), (NON_ASCII, NON_ASCII_COMPACT)],
)
def test_compact_output_file_bytes(tmp_path, capsys, flag, text, expected):
    src = write_csv(tmp_path / "in.csv", text)
    dest = tmp_path / "out.json"
    assert run_main([str(src), "--compact", flag, str(dest)]) == 0
    out, err = capsys.readouterr()
    assert out == ""
    assert err == ""
    assert dest.read_bytes() == expected


@pytest.mark.parametrize("existing", [False, True])
def test_compact_output_file_uses_atomic_replace(tmp_path, capsys, monkeypatch, existing):
    src = write_csv(tmp_path / "in.csv", NON_ASCII)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    dest = out_dir / "OUT.json"
    if existing:
        dest.write_text(ORIGINAL, encoding="utf-8")
    before = listing(out_dir)
    calls = spy_replace(monkeypatch)
    assert run_main([str(src), "-o", str(dest), "--compact"]) == 0
    assert len(calls) == 1
    call = calls[0]
    assert same_path(call["dst"], dest)
    assert not same_path(call["src"], dest)
    assert os.path.dirname(os.path.abspath(call["src"])) == str(out_dir.resolve())
    assert call["content"] == NON_ASCII_COMPACT
    assert dest.read_bytes() == NON_ASCII_COMPACT
    assert listing(out_dir) == sorted(set(before) | {"OUT.json"})


# AC-5


@pytest.mark.parametrize(
    "text,rows",
    [(SAMPLE, SAMPLE_ROWS), (NON_ASCII, NON_ASCII_ROWS), (MULTILINE, MULTILINE_ROWS)],
)
def test_default_stdout_is_still_indented(tmp_path, monkeypatch, text, rows):
    src = write_csv(tmp_path / "in.csv", text)
    code, data = run_to_bytes(monkeypatch, [str(src)])
    assert code == 0
    assert data == indented_bytes(rows)


def test_default_output_file_is_still_indented(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", NON_ASCII)
    dest = tmp_path / "out.json"
    assert run_main([str(src), "-o", str(dest)]) == 0
    assert dest.read_bytes() == indented_bytes(NON_ASCII_ROWS)


def test_compact_and_default_differ_but_parse_the_same(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    assert run_main([str(src)]) == 0
    default_out, _ = capsys.readouterr()
    assert run_main([str(src), "--compact"]) == 0
    compact_out, _ = capsys.readouterr()
    assert default_out != compact_out
    assert json.loads(default_out) == json.loads(compact_out) == SAMPLE_ROWS


# AC-6


@pytest.mark.parametrize("text", ["a,b,c\n", "a,b,c", "a,b,c\n\n  \n"])
def test_compact_header_only_is_empty_array(tmp_path, capsys, text):
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
    assert run_main(argv) == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert out == SAMPLE_COMPACT


@pytest.mark.parametrize(
    "order",
    [
        ["--compact", "IN", "-o", "OUT"],
        ["IN", "--compact", "-o", "OUT"],
        ["IN", "-o", "OUT", "--compact"],
        ["-o", "OUT", "--compact", "IN"],
        ["--compact", "-o", "OUT", "IN"],
        ["-o", "OUT", "IN", "--compact"],
    ],
)
def test_compact_position_with_output(tmp_path, capsys, order):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    dest = tmp_path / "out.json"
    mapping = {"IN": str(src), "OUT": str(dest)}
    argv = [mapping.get(a, a) for a in order]
    assert run_main(argv) == 0
    out, err = capsys.readouterr()
    assert out == ""
    assert err == ""
    assert dest.read_bytes() == SAMPLE_COMPACT.encode("utf-8")


def test_compact_takes_no_value(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    with pytest.raises(SystemExit) as exc:
        run_main([str(src), "--compact=yes"])
    assert exc.value.code == 2


def test_compact_does_not_consume_following_input(tmp_path, capsys):
    # if --compact took a value it would swallow the input path
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    assert run_main(["--compact", str(src)]) == 0
    out, _ = capsys.readouterr()
    assert json.loads(out) == SAMPLE_ROWS


# AC-8


def _input_for(kind, tmp_path):
    if kind == "bad_row":
        return write_csv(tmp_path / "in.csv", "a,b,c\np,q,r\np,q\n")
    if kind == "missing":
        return tmp_path / "missing.csv"
    return write_csv(tmp_path / "in.csv", "\n\n")


@pytest.mark.parametrize("kind", ["bad_row", "missing", "no_header"])
def test_compact_input_errors_on_stdout(tmp_path, capsys, kind):
    src = _input_for(kind, tmp_path)
    code = run_main([str(src), "--compact"])
    assert_clean_error(capsys, code)


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("kind", ["bad_row", "missing", "no_header"])
def test_compact_input_errors_leave_output_alone(
    tmp_path, capsys, monkeypatch, kind, existing
):
    src = _input_for(kind, tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    dest = out_dir / "OUT.json"
    if existing:
        dest.write_text(ORIGINAL, encoding="utf-8")
    before = listing(out_dir)
    calls = spy_replace(monkeypatch)
    code = run_main(["--compact", str(src), "-o", str(dest)])
    assert_clean_error(capsys, code)
    assert calls == []
    assert listing(out_dir) == before
    if existing:
        assert dest.read_text(encoding="utf-8") == ORIGINAL
    else:
        assert not dest.exists()


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


def test_subprocess_compact_sample(tmp_path):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    result = _run_module([str(src), "--compact"], tmp_path)
    stderr = result.stderr.decode("utf-8", "replace")
    assert result.returncode == 0, stderr
    assert stderr == ""
    assert result.stdout == SAMPLE_COMPACT.encode("utf-8")


def test_subprocess_compact_non_ascii(tmp_path):
    src = write_csv(tmp_path / "in.csv", NON_ASCII)
    result = _run_module([str(src), "--compact"], tmp_path)
    stderr = result.stderr.decode("utf-8", "replace")
    assert result.returncode == 0, stderr
    assert result.stdout == NON_ASCII_COMPACT
    assert result.stdout.count(b"\n") == 1

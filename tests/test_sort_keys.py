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
SORTED_KEYS = ["age", "city", "name"]
ORIGINAL = "original contents\n"


def run_main(argv):
    from csv_tool.cli import main

    return main(argv)


def write_csv(path, text, newline="\n"):
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))
    return path


def expected_bytes(value, sort_keys=False):
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=sort_keys)
    return (text + "\n").encode("utf-8")


SORTED_BYTES = expected_bytes(SAMPLE_ROWS, sort_keys=True)


def assert_output(capsys, code, expected):
    out, err = capsys.readouterr()
    assert code == 0, err
    assert err == ""
    assert out.encode("utf-8") == expected
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


def test_sort_keys_writes_sorted_objects(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    code = run_main([str(src), "--sort-keys"])
    out = assert_output(capsys, code, SORTED_BYTES)
    for obj in json.loads(out):
        assert list(obj) == SORTED_KEYS


# AC-2


def test_sort_keys_only_changes_key_order(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    code_plain = run_main([str(src)])
    out_plain = assert_output(capsys, code_plain, expected_bytes(SAMPLE_ROWS))
    code_sorted = run_main([str(src), "--sort-keys"])
    out_sorted = assert_output(capsys, code_sorted, SORTED_BYTES)
    plain = json.loads(out_plain)
    sorted_rows = json.loads(out_sorted)
    assert plain == sorted_rows
    assert len(sorted_rows) == 2
    assert [r["name"] for r in sorted_rows] == ["Alice", "Bob"]
    assert out_plain != out_sorted


def test_sort_keys_with_duplicate_headers_keeps_last_value(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", "b,a,b\n1,2,3\n")
    code = run_main([str(src), "--sort-keys"])
    rows = [{"a": "2", "b": "3"}]
    out = assert_output(capsys, code, expected_bytes(rows, sort_keys=True))
    assert list(json.loads(out)[0]) == ["a", "b"]


# AC-3


def test_sort_keys_uses_code_point_order_and_literal_utf8(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", "b,B,a,_x,é\n1,2,3,4,Zoë東京\n")
    code = run_main([str(src), "--sort-keys"])
    rows = [{"b": "1", "B": "2", "a": "3", "_x": "4", "é": "Zoë東京"}]
    out = assert_output(capsys, code, expected_bytes(rows, sort_keys=True))
    assert list(json.loads(out)[0]) == ["B", "_x", "a", "b", "é"]
    assert "é" in out
    assert "Zoë東京" in out
    assert "\\u" not in out


# AC-4


def test_without_sort_keys_output_is_unchanged(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", "z,a,m\n1,2,3\n")
    rows = [{"z": "1", "a": "2", "m": "3"}]
    code = run_main([str(src)])
    out = assert_output(capsys, code, expected_bytes(rows))
    assert list(json.loads(out)[0]) == ["z", "a", "m"]
    code = run_main([str(src), "--sort-keys"])
    out = assert_output(capsys, code, expected_bytes(rows, sort_keys=True))
    assert list(json.loads(out)[0]) == ["a", "m", "z"]


# AC-5


def test_sort_keys_position_does_not_matter(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    code_before = run_main(["--sort-keys", str(src)])
    out_before = assert_output(capsys, code_before, SORTED_BYTES)
    code_after = run_main([str(src), "--sort-keys"])
    out_after = assert_output(capsys, code_after, SORTED_BYTES)
    assert out_before == out_after


# AC-6


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("flag", ["-o", "--output"])
def test_sort_keys_to_output_file_is_atomic(tmp_path, capsys, monkeypatch, flag, existing):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "neighbour.txt").write_text("keep\n", encoding="utf-8")
    dest = out_dir / "OUT.json"
    if existing:
        dest.write_text(ORIGINAL, encoding="utf-8")
    before = listing(out_dir)
    calls = spy_replace(monkeypatch)
    code = run_main([str(src), "--sort-keys", flag, str(dest)])
    out, err = capsys.readouterr()
    assert code == 0, err
    assert out == ""
    assert err == ""
    assert dest.read_bytes() == SORTED_BYTES
    assert len(calls) == 1
    call = calls[0]
    assert same_path(call["dst"], dest)
    assert not same_path(call["src"], dest)
    assert os.path.dirname(os.path.abspath(call["src"])) == str(out_dir.resolve())
    assert call["content"] == SORTED_BYTES
    assert listing(out_dir) == sorted(set(before) | {"OUT.json"})


# AC-7


@pytest.mark.parametrize("flag", ["-d", "--delimiter"])
def test_sort_keys_with_semicolon_delimiter(tmp_path, capsys, flag):
    src = write_csv(tmp_path / "in.csv", SAMPLE.replace(",", ";"))
    code = run_main([str(src), "--sort-keys", flag, ";"])
    assert_output(capsys, code, SORTED_BYTES)


@pytest.mark.parametrize("delim", ["\t", "\\t"], ids=["literal_tab", "escape_tab"])
def test_sort_keys_with_tab_delimiter(tmp_path, capsys, delim):
    src = write_csv(tmp_path / "in.csv", SAMPLE.replace(",", "\t"))
    code = run_main(["--sort-keys", "-d", delim, str(src)])
    assert_output(capsys, code, SORTED_BYTES)


@pytest.mark.parametrize("value", ["", ";;", "ab", '"', "\\n"], ids=repr)
def test_sort_keys_with_invalid_delimiter_is_usage_error(tmp_path, capsys, value):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    with pytest.raises(SystemExit) as exc:
        run_main([str(src), "--sort-keys", "-d", value])
    out, err = capsys.readouterr()
    assert exc.value.code == 2
    assert out == ""
    assert "delimiter" in err.lower()
    assert "Traceback" not in err


# AC-8


def test_sort_keys_with_output_and_delimiter(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", SAMPLE.replace(",", ";"))
    dest = tmp_path / "out.json"
    code = run_main(["--sort-keys", "-o", str(dest), "-d", ";", str(src)])
    out, err = capsys.readouterr()
    assert code == 0, err
    assert out == ""
    assert err == ""
    assert dest.read_bytes() == SORTED_BYTES


# AC-9


@pytest.mark.parametrize("text", ["a,b,c\n", "a,b,c", "a,b,c\n\n  \n"])
def test_sort_keys_header_only_gives_empty_array(tmp_path, capsys, text):
    src = write_csv(tmp_path / "in.csv", text)
    code = run_main([str(src), "--sort-keys"])
    assert_output(capsys, code, b"[]\n")


def _error_input(kind, tmp_path):
    if kind == "missing":
        return tmp_path / "missing.csv"
    if kind == "directory":
        folder = tmp_path / "adir"
        folder.mkdir()
        return folder
    if kind == "empty":
        return write_csv(tmp_path / "in.csv", "")
    if kind == "blank_only":
        return write_csv(tmp_path / "in.csv", "\n  \n\t\n\r\n")
    return write_csv(tmp_path / "in.csv", "a,b,c\np,q,r\np,q\n")


ERROR_KINDS = ["missing", "directory", "empty", "blank_only", "bad_row"]


@pytest.mark.parametrize("kind", ERROR_KINDS)
def test_sort_keys_input_errors_are_clean(tmp_path, capsys, kind):
    src = _error_input(kind, tmp_path)
    code = run_main([str(src), "--sort-keys"])
    assert_clean_error(capsys, code)


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("kind", ERROR_KINDS)
def test_sort_keys_input_errors_leave_output_alone(
    tmp_path, capsys, monkeypatch, kind, existing
):
    src = _error_input(kind, tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    dest = out_dir / "OUT.json"
    if existing:
        dest.write_bytes(ORIGINAL.encode("utf-8"))
    before = listing(out_dir)
    calls = spy_replace(monkeypatch)
    code = run_main([str(src), "--sort-keys", "-o", str(dest)])
    assert_clean_error(capsys, code)
    assert calls == []
    assert listing(out_dir) == before
    if existing:
        assert dest.read_bytes() == ORIGINAL.encode("utf-8")
    else:
        assert not dest.exists()


# AC-10


@pytest.mark.parametrize(
    "header, keys",
    [("name,age,city", SAMPLE_KEYS), ("z,a,m", ["z", "a", "m"]), ("b,a,b", ["b", "a", "b"])],
)
def test_sort_keys_does_not_affect_keys_mode(tmp_path, capsys, header, keys):
    src = write_csv(tmp_path / "in.csv", header + "\n1,2,3\n")
    code_plain = run_main([str(src), "--keys"])
    out_plain = assert_output(capsys, code_plain, expected_bytes(keys))
    code_sorted = run_main([str(src), "--keys", "--sort-keys"])
    out_sorted = assert_output(capsys, code_sorted, expected_bytes(keys))
    assert out_plain == out_sorted


def test_sort_keys_with_keys_output_and_delimiter(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", "z;a;m\n1;2;3\n")
    dest = tmp_path / "out.json"
    code = run_main([str(src), "--sort-keys", "--keys", "-d", ";", "-o", str(dest)])
    out, err = capsys.readouterr()
    assert code == 0, err
    assert out == ""
    assert err == ""
    assert dest.read_bytes() == expected_bytes(["z", "a", "m"])


# AC-11


def test_version_takes_precedence_over_sort_keys(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    with pytest.raises(SystemExit) as exc:
        run_main([str(src), "--sort-keys", "--version"])
    out, err = capsys.readouterr()
    assert exc.value.code == 0
    assert out == "csv_tool 0.1.0\n"
    assert err == ""


def test_help_lists_sort_keys_option(capsys):
    with pytest.raises(SystemExit) as exc:
        run_main(["--help"])
    out, _ = capsys.readouterr()
    assert exc.value.code == 0
    assert "--sort-keys" in out


# AC-12


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


def test_subprocess_sort_keys(tmp_path):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    result = _run_module(["--sort-keys", str(src)], tmp_path)
    stderr = result.stderr.decode("utf-8", "replace")
    assert result.returncode == 0, stderr
    assert stderr == ""
    assert result.stdout == SORTED_BYTES


def test_subprocess_sort_keys_ascii_stdout_encoding_emits_utf8(tmp_path):
    src = write_csv(tmp_path / "in.csv", "name,Zoë\n東京,é\n")
    result = _run_module(["--sort-keys", str(src)], tmp_path, PYTHONIOENCODING="ascii")
    stderr = result.stderr.decode("utf-8", "replace")
    assert result.returncode == 0, stderr
    assert stderr == ""
    rows = [{"name": "東京", "Zoë": "é"}]
    assert result.stdout == expected_bytes(rows, sort_keys=True)
    assert list(json.loads(result.stdout.decode("utf-8"))[0]) == ["Zoë", "name"]


# AC-13


def test_signatures_unchanged():
    from csv_tool.cli import main, read_rows

    params = inspect.signature(main).parameters
    assert list(params) == ["argv"]
    assert params["argv"].default is None
    params = inspect.signature(read_rows).parameters
    assert list(params) == ["path", "delimiter"]
    assert params["delimiter"].default == ","

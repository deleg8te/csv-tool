import builtins
import errno
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"

NON_ASCII = "name,city\nZoë,東京\n"
NON_ASCII_ROWS = [{"name": "Zoë", "city": "東京"}]
SAMPLE = "name,age,city\nAlice,30,Paris\nBob,25,Berlin\n"
SAMPLE_ROWS = [
    {"name": "Alice", "age": "30", "city": "Paris"},
    {"name": "Bob", "age": "25", "city": "Berlin"},
]
ORIGINAL = "original contents\n"


def run_main(argv):
    from csv_tool.cli import main

    return main(argv)


def write_csv(path, text):
    path.write_bytes(text.encode("utf-8"))
    return path


def expected_bytes(rows):
    return (json.dumps(rows, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def assert_clean_error(capsys, code):
    out, err = capsys.readouterr()
    assert code == 1
    assert out == ""
    assert err.startswith("error:")
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


def setup_existing_output(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    dest = out_dir / "OUT.json"
    dest.write_text(ORIGINAL, encoding="utf-8")
    (out_dir / "neighbour.txt").write_text("keep\n", encoding="utf-8")
    src = write_csv(tmp_path / "in.csv", NON_ASCII)
    return src, dest, out_dir


class _FailingFile:
    """Delegates to a real file but fails with ENOSPC partway through a write."""

    def __init__(self, f):
        self._f = f

    def write(self, data):
        self._f.write(data[: len(data) // 2])
        self._f.flush()
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    def writelines(self, lines):
        self.write("".join(lines) if lines and isinstance(lines[0], str) else b"".join(lines))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._f.close()
        return False

    def __iter__(self):
        return iter(self._f)

    def __getattr__(self, name):
        return getattr(self._f, name)


def make_writes_fail(monkeypatch, input_path):
    real_open = io.open
    real_os_write = os.write

    def failing_open(file, mode="r", *args, **kwargs):
        f = real_open(file, mode, *args, **kwargs)
        is_input = not isinstance(file, int) and same_path(file, input_path)
        if not is_input and any(c in mode for c in "wxa+"):
            return _FailingFile(f)
        return f

    def failing_os_write(fd, data):
        if fd in (0, 1, 2):
            return real_os_write(fd, data)
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    monkeypatch.setattr(builtins, "open", failing_open)
    monkeypatch.setattr(io, "open", failing_open)
    monkeypatch.setattr(os, "write", failing_os_write)


# AC-1


def test_subprocess_ascii_stdout_encoding_emits_utf8(tmp_path):
    src = write_csv(tmp_path / "in.csv", NON_ASCII)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_DIR)
    env["PYTHONIOENCODING"] = "ascii"
    result = subprocess.run(
        [sys.executable, "-m", "csv_tool", str(src)],
        capture_output=True,
        cwd=tmp_path,
        env=env,
        timeout=60,
    )
    stderr = result.stderr.decode("utf-8", "replace")
    assert result.returncode == 0, stderr
    assert stderr == ""
    assert json.loads(result.stdout.decode("utf-8")) == NON_ASCII_ROWS


# AC-2


def test_stdout_bytes_go_to_buffer_whatever_the_encoding(tmp_path, monkeypatch):
    src = write_csv(tmp_path / "in.csv", NON_ASCII)
    raw = io.BytesIO()
    stdout = io.TextIOWrapper(raw, encoding="ascii")
    monkeypatch.setattr(sys, "stdout", stdout)
    code = run_main([str(src)])
    stdout.flush()
    assert code == 0
    assert json.loads(raw.getvalue().decode("utf-8")) == NON_ASCII_ROWS


def test_text_buffered_before_bytes_keeps_order(tmp_path, monkeypatch):
    src = write_csv(tmp_path / "in.csv", NON_ASCII)
    raw = io.BytesIO()
    stdout = io.TextIOWrapper(raw, encoding="ascii")
    stdout.write("prefix\n")
    monkeypatch.setattr(sys, "stdout", stdout)
    code = run_main([str(src)])
    stdout.flush()
    assert code == 0
    assert raw.getvalue() == b"prefix\n" + expected_bytes(NON_ASCII_ROWS)


# AC-3


def test_stdout_without_buffer_gets_text(tmp_path, monkeypatch):
    src = write_csv(tmp_path / "in.csv", NON_ASCII)
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)
    code = run_main([str(src)])
    assert code == 0
    assert stdout.getvalue() == expected_bytes(NON_ASCII_ROWS).decode("utf-8")


# AC-4


def test_stdout_bytes_are_exact_json(tmp_path, monkeypatch):
    src = write_csv(tmp_path / "in.csv", NON_ASCII)
    raw = io.BytesIO()
    stdout = io.TextIOWrapper(raw, encoding="ascii")
    monkeypatch.setattr(sys, "stdout", stdout)
    assert run_main([str(src)]) == 0
    stdout.flush()
    assert raw.getvalue() == expected_bytes(NON_ASCII_ROWS)


def test_capsys_stdout_is_exact_json(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", NON_ASCII)
    assert run_main([str(src)]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert out.encode("utf-8") == expected_bytes(NON_ASCII_ROWS)


@pytest.mark.parametrize("existing", [False, True])
def test_output_file_bytes_are_exact_json_and_stdout_empty(tmp_path, capsys, existing):
    src = write_csv(tmp_path / "in.csv", NON_ASCII)
    dest = tmp_path / "out.json"
    if existing:
        dest.write_text(ORIGINAL, encoding="utf-8")
    assert run_main([str(src), "-o", str(dest)]) == 0
    out, err = capsys.readouterr()
    assert out == ""
    assert err == ""
    assert dest.read_bytes() == expected_bytes(NON_ASCII_ROWS)


# AC-5


@pytest.mark.parametrize("relative", [False, True])
def test_output_is_written_via_temp_file_and_os_replace(
    tmp_path, capsys, monkeypatch, relative
):
    src = write_csv(tmp_path / "in.csv", NON_ASCII)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    dest = out_dir / "OUT.json"
    dest.write_text(ORIGINAL, encoding="utf-8")
    calls = spy_replace(monkeypatch)
    if relative:
        monkeypatch.chdir(out_dir)
        dest_arg = "OUT.json"
    else:
        dest_arg = str(dest)
    assert run_main([str(src), "-o", dest_arg]) == 0
    assert len(calls) == 1
    call = calls[0]
    assert same_path(call["dst"], dest)
    assert not same_path(call["src"], dest)
    assert os.path.dirname(os.path.abspath(call["src"])) == str(out_dir.resolve())
    assert call["content"] == expected_bytes(NON_ASCII_ROWS)
    assert dest.read_bytes() == expected_bytes(NON_ASCII_ROWS)


# AC-6, AC-8


def test_write_failure_leaves_existing_output_and_no_temp(tmp_path, capsys, monkeypatch):
    src, dest, out_dir = setup_existing_output(tmp_path)
    before = listing(out_dir)
    make_writes_fail(monkeypatch, src)
    code = run_main([str(src), "-o", str(dest)])
    monkeypatch.undo()
    err = assert_clean_error(capsys, code)
    assert str(dest) in err
    assert dest.read_text(encoding="utf-8") == ORIGINAL
    assert listing(out_dir) == before


# AC-7, AC-8


def test_replace_failure_leaves_existing_output_and_no_temp(tmp_path, capsys, monkeypatch):
    src, dest, out_dir = setup_existing_output(tmp_path)
    before = listing(out_dir)
    calls = []

    def failing_replace(src_path, dst_path, *args, **kwargs):
        calls.append((os.fspath(src_path), os.fspath(dst_path)))
        raise OSError(errno.EIO, os.strerror(errno.EIO))

    monkeypatch.setattr(os, "replace", failing_replace)
    code = run_main([str(src), "-o", str(dest)])
    monkeypatch.undo()
    err = assert_clean_error(capsys, code)
    assert calls, "os.replace was never called"
    assert str(dest) in err
    assert dest.read_text(encoding="utf-8") == ORIGINAL
    assert listing(out_dir) == before


# AC-8


@pytest.mark.parametrize("existing", [False, True])
def test_success_leaves_no_temp_files(tmp_path, capsys, monkeypatch, existing):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "neighbour.txt").write_text("keep\n", encoding="utf-8")
    dest = out_dir / "OUT.json"
    if existing:
        dest.write_text(ORIGINAL, encoding="utf-8")
    before = listing(out_dir)
    calls = spy_replace(monkeypatch)
    assert run_main([str(src), "-o", str(dest)]) == 0
    assert calls, "os.replace was never called"
    assert listing(out_dir) == sorted(set(before) | {"OUT.json"})
    assert json.loads(dest.read_text(encoding="utf-8")) == SAMPLE_ROWS


# AC-9


def test_output_is_existing_directory(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    parent = tmp_path / "parent"
    parent.mkdir()
    target = parent / "adir"
    target.mkdir()
    (target / "inside.txt").write_text("inner\n", encoding="utf-8")
    parent_before = listing(parent)
    code = run_main([str(src), "-o", str(target)])
    assert_clean_error(capsys, code)
    assert target.is_dir()
    assert listing(target) == ["inside.txt"]
    assert (target / "inside.txt").read_text(encoding="utf-8") == "inner\n"
    assert listing(parent) == parent_before


# AC-10


def test_missing_output_parent_creates_nothing(tmp_path, capsys):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    before = listing(tmp_path)
    dest = tmp_path / "no_such_dir" / "out.json"
    code = run_main([str(src), "-o", str(dest)])
    err = assert_clean_error(capsys, code)
    assert str(dest) in err
    assert listing(tmp_path) == before
    assert not dest.parent.exists()


# AC-11


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits only")
def test_new_output_gets_umask_based_mode(tmp_path, capsys, monkeypatch):
    src = write_csv(tmp_path / "in.csv", SAMPLE)
    dest = tmp_path / "out.json"
    calls = spy_replace(monkeypatch)
    old_umask = os.umask(0o022)
    try:
        assert run_main([str(src), "-o", str(dest)]) == 0
    finally:
        os.umask(old_umask)
    assert calls, "os.replace was never called"
    assert dest.stat().st_mode & 0o777 == 0o644


# AC-12


def _input_for(kind, tmp_path):
    if kind == "bad_row":
        return write_csv(tmp_path / "in.csv", "a,b,c\np,q,r\np,q\n")
    if kind == "missing":
        return tmp_path / "missing.csv"
    return write_csv(tmp_path / "in.csv", "\n\n")


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("kind", ["bad_row", "missing", "no_header"])
def test_input_error_creates_no_output_or_temp(tmp_path, capsys, monkeypatch, kind, existing):
    src = _input_for(kind, tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    dest = out_dir / "OUT.json"
    if existing:
        dest.write_text(ORIGINAL, encoding="utf-8")
    before = listing(out_dir)
    calls = spy_replace(monkeypatch)
    code = run_main([str(src), "-o", str(dest)])
    assert_clean_error(capsys, code)
    assert calls == []
    assert listing(out_dir) == before
    if existing:
        assert dest.read_text(encoding="utf-8") == ORIGINAL
    else:
        assert not dest.exists()

"""Command-line interface: convert a CSV file with a header row to JSON."""

import argparse
import contextlib
import csv
import json
import os
import sys
import tempfile

from csv_tool import __version__


class CsvError(Exception):
    """Raised when the input CSV is malformed."""


def _is_blank(record: list[str]) -> bool:
    return not record or (len(record) == 1 and not record[0].strip())


def read_rows(path: str, delimiter: str = ",") -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        header: list[str] | None = None
        rows: list[dict[str, str]] = []
        for record in reader:
            if _is_blank(record):
                continue
            if header is None:
                header = record
                continue
            if len(record) != len(header):
                raise CsvError(
                    f"{path}: line {reader.line_num}: "
                    f"expected {len(header)} fields, got {len(record)}"
                )
            rows.append(dict(zip(header, record)))
    if header is None:
        raise CsvError(f"{path}: file has no header row")
    return rows


def _read_header(path: str, delimiter: str = ",") -> list[str]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        for record in csv.reader(f, delimiter=delimiter):
            if not _is_blank(record):
                return record
    raise CsvError(f"{path}: file has no header row")


def _delimiter(value: str) -> str:
    if value == "\\t":
        return "\t"
    if len(value) != 1 or value in '"\r\n':
        raise argparse.ArgumentTypeError(
            f"invalid delimiter {value!r}: must be a single character or \\t"
        )
    return value


def _write_stdout(text: str) -> None:
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(text)
        return
    sys.stdout.flush()
    buffer.write(text.encode("utf-8"))
    buffer.flush()


def _current_umask() -> int:
    umask = os.umask(0)
    os.umask(umask)
    return umask


def _write_atomic(path: str, data: bytes) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    prefix = "." + os.path.basename(path) + "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=prefix, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
        if os.name == "posix":
            os.chmod(tmp, 0o666 & ~_current_umask())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="csv_tool", description="Convert a CSV file to a JSON array."
    )
    parser.add_argument("input", help="input CSV file with a header row")
    parser.add_argument("-o", "--output", help="write JSON here instead of stdout")
    parser.add_argument(
        "-d",
        "--delimiter",
        type=_delimiter,
        default=",",
        help="field delimiter: a single character, or \\t for tab (default: ,)",
    )
    parser.add_argument(
        "--keys",
        action="store_true",
        help="print the header's column names as a JSON array instead of rows",
    )
    parser.add_argument(
        "--sort-keys",
        action="store_true",
        help="write each object's keys in sorted order",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    args = parser.parse_args(argv)

    try:
        data: list[str] | list[dict[str, str]]
        if args.keys:
            data = _read_header(args.input, args.delimiter)
        else:
            data = read_rows(args.input, args.delimiter)
    except OSError as e:
        print(f"error: cannot read {args.input}: {e.strerror or e}", file=sys.stderr)
        return 1
    except CsvError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except (csv.Error, UnicodeDecodeError) as e:
        print(f"error: {args.input}: {e}", file=sys.stderr)
        return 1

    sort_keys = args.sort_keys and not args.keys
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=sort_keys) + "\n"
    if args.output is None:
        _write_stdout(text)
        return 0
    try:
        _write_atomic(args.output, text.encode("utf-8"))
    except OSError as e:
        print(f"error: cannot write {args.output}: {e.strerror or e}", file=sys.stderr)
        return 1
    return 0

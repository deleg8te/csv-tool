"""Command-line interface: convert a CSV file with a header row to JSON."""

import argparse
import csv
import json
import sys


class CsvError(Exception):
    """Raised when the input CSV is malformed."""


def _is_blank(record: list[str]) -> bool:
    return not record or (len(record) == 1 and not record[0].strip())


def read_rows(path: str) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="csv_tool", description="Convert a CSV file to a JSON array."
    )
    parser.add_argument("input", help="input CSV file with a header row")
    parser.add_argument("-o", "--output", help="write JSON here instead of stdout")
    args = parser.parse_args(argv)

    try:
        rows = read_rows(args.input)
    except OSError as e:
        print(f"error: cannot read {args.input}: {e.strerror or e}", file=sys.stderr)
        return 1
    except CsvError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except (csv.Error, UnicodeDecodeError) as e:
        print(f"error: {args.input}: {e}", file=sys.stderr)
        return 1

    text = json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
    if args.output is None:
        sys.stdout.write(text)
        return 0
    try:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as e:
        print(f"error: cannot write {args.output}: {e.strerror or e}", file=sys.stderr)
        return 1
    return 0

#!/usr/bin/env python3
"""Scan GUI Python files for Chinese text that should go through Qt i18n."""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
TR_CALL_RE = re.compile(
    r"""(?:self\.tr|tr|QCoreApplication\.translate)\(\s*"""
    r"""(?P<quote>['\"])(?P<text>(?:\\.|(?!\1).)*)\1""",
    re.DOTALL,
)
HARDCODED_STRING_RE = re.compile(
    r"""(?P<quote>['\"])(?P<text>(?:\\.|(?!\1).)*)\1""",
    re.DOTALL,
)
SKIP_DIRS = {"__pycache__", ".git"}


def decode_py_string(raw: str, quote: str) -> str:
    return ast.literal_eval(f"{quote}{raw}{quote}")


def iter_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def find_tr_strings(path: Path) -> list[tuple[int, str]]:
    text = path.read_text(encoding="utf-8")
    results: list[tuple[int, str]] = []
    for match in TR_CALL_RE.finditer(text):
        try:
            value = decode_py_string(match.group("text"), match.group("quote"))
        except (SyntaxError, ValueError):
            continue
        if CHINESE_RE.search(value):
            line = text.count("\n", 0, match.start()) + 1
            results.append((line, value))
    return results


def find_hardcoded_chinese(path: Path) -> list[tuple[int, str, str]]:
    """Find Chinese string literals outside tr()/translate() calls."""
    text = path.read_text(encoding="utf-8")
    findings: list[tuple[int, str, str]] = []
    for match in HARDCODED_STRING_RE.finditer(text):
        start = match.start()
        try:
            value = decode_py_string(match.group("text"), match.group("quote"))
        except (SyntaxError, ValueError):
            continue
        if not CHINESE_RE.search(value):
            continue
        prefix = text[max(0, start - 40):start]
        if re.search(r"(?:self\.)?tr\(\s*$", prefix) or "translate(" in prefix:
            continue
        if value.strip().startswith("#"):
            continue
        line = text.count("\n", 0, start) + 1
        snippet = text.splitlines()[line - 1].strip()
        findings.append((line, value, snippet))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "src" / "gui" / "view",
        help="GUI view directory to scan",
    )
    parser.add_argument(
        "--mode",
        choices=("tr", "hardcoded", "all"),
        default="all",
    )
    args = parser.parse_args()

    tr_total = 0
    hardcoded_total = 0

    for path in iter_python_files(args.root):
        rel = path.relative_to(args.root.parents[1])
        if args.mode in ("tr", "all"):
            tr_strings = find_tr_strings(path)
            if tr_strings:
                print(f"\n[{rel}] tr() with Chinese source:")
                for line, value in tr_strings:
                    preview = value.replace("\n", "\\n")
                    if len(preview) > 120:
                        preview = preview[:117] + "..."
                    print(f"  L{line}: {preview}")
                    tr_total += 1
        if args.mode in ("hardcoded", "all"):
            hardcoded = find_hardcoded_chinese(path)
            if hardcoded:
                print(f"\n[{rel}] hardcoded Chinese (not in tr()):")
                for line, value, snippet in hardcoded:
                    preview = value.replace("\n", "\\n")
                    if len(preview) > 80:
                        preview = preview[:77] + "..."
                    print(f"  L{line}: {preview}")
                    print(f"         {snippet}")
                    hardcoded_total += 1

    print(
        f"\nSummary: {tr_total} tr() Chinese strings, "
        f"{hardcoded_total} hardcoded Chinese literals"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

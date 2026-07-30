#!/usr/bin/env python3
"""Generate gallery.th_TH.ts from GUI source strings and Thai translation map."""

from __future__ import annotations

import argparse
import ast
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
TR_METHODS = {"tr", "translate"}


def decode_string(node: ast.Constant) -> str:
    if not isinstance(node.value, str):
        raise TypeError("expected string constant")
    return node.value


def get_tr_strings_from_expr(node: ast.AST) -> list[str]:
    strings: list[str] = []
    if isinstance(node, ast.Call):
        func = node.func
        name = None
        if isinstance(func, ast.Attribute) and func.attr in TR_METHODS:
            name = func.attr
        elif isinstance(func, ast.Name) and func.id in TR_METHODS:
            name = func.id
        if name and node.args:
            arg0 = node.args[0]
            if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                strings.append(arg0.value)
            elif isinstance(arg0, ast.JoinedStr):
                template = "".join(
                    part.value if isinstance(part, ast.Constant) else "{}" for part in arg0.values
                )
                strings.append(template)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        for side in (node.left, node.right):
            strings.extend(get_tr_strings_from_expr(side))
    return strings


class TrExtractor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.context: str | None = None
        self.entries: dict[str, set[str]] = defaultdict(set)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        previous = self.context
        self.context = node.name
        self.generic_visit(node)
        self.context = previous

    def visit_Call(self, node: ast.Call) -> None:
        if self.context:
            for value in get_tr_strings_from_expr(node):
                if CHINESE_RE.search(value) or "{" in value:
                    self.entries[self.context].add(value)
        self.generic_visit(node)


def collect_entries(root: Path) -> dict[str, set[str]]:
    extractor = TrExtractor()
    for path in sorted(root.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue
        extractor.visit(tree)
    return extractor.entries


def xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_ts(entries: dict[str, set[str]], translations: dict[str, str]) -> str:
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "<!DOCTYPE TS>",
        '<TS version="2.1" language="th_TH" sourcelanguage="zh_CN">',
    ]
    missing: list[str] = []
    for context in sorted(entries):
        lines.append("<context>")
        lines.append(f"    <name>{xml_escape(context)}</name>")
        for source in sorted(entries[context]):
            translation = translations.get(source)
            if translation is None:
                missing.append(source)
                translation = source
                unfinished = ' type="unfinished"'
            else:
                unfinished = ""
            lines.append("    <message>")
            lines.append(f"        <source>{xml_escape(source)}</source>")
            lines.append(f"        <translation{unfinished}>{xml_escape(translation)}</translation>")
            lines.append("    </message>")
        lines.append("</context>")
    lines.append("</TS>")
    if missing:
        print(f"Warning: {len(missing)} strings missing Thai translation", file=sys.stderr)
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "src" / "gui" / "view",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "src" / "gui" / "resource" / "i18n" / "gallery.th_TH.ts",
    )
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from i18n_th_map import TH_TRANSLATIONS  # noqa: WPS433

    entries = collect_entries(args.root)
    ts_content = build_ts(entries, TH_TRANSLATIONS)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(ts_content, encoding="utf-8")
    total = sum(len(v) for v in entries.values())
    print(f"Wrote {args.output} ({total} messages in {len(entries)} contexts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

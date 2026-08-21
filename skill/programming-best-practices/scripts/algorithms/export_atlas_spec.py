#!/usr/bin/env python3
"""Read-only TipTap JSON to Markdown exporter for the Atlas source note."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


def _inline(node: dict[str, Any]) -> str:
    if node.get("type") == "text":
        text = str(node.get("text") or "")
        for mark in node.get("marks") or []:
            kind = mark.get("type")
            if kind == "code":
                text = f"`{text}`"
            elif kind == "bold":
                text = f"**{text}**"
            elif kind == "italic":
                text = f"*{text}*"
            elif kind == "strike":
                text = f"~~{text}~~"
            elif kind == "link":
                text = f"[{text}]({(mark.get('attrs') or {}).get('href', '')})"
        return text
    if node.get("type") == "hardBreak":
        return "  \n"
    return "".join(_inline(child) for child in node.get("content") or [])


def _blocks(nodes: list[dict[str, Any]], indent: int = 0) -> list[str]:
    lines: list[str] = []
    prefix = "  " * indent
    for node in nodes:
        kind = node.get("type")
        children = node.get("content") or []
        if kind == "heading":
            lines.extend([f"{'#' * int((node.get('attrs') or {}).get('level', 1))} {_inline(node)}", ""])
        elif kind == "paragraph":
            lines.extend([prefix + _inline(node), ""])
        elif kind == "horizontalRule":
            lines.extend(["---", ""])
        elif kind == "codeBlock":
            language = (node.get("attrs") or {}).get("language") or ""
            lines.extend([f"```{language}", _inline(node), "```", ""])
        elif kind == "blockquote":
            rendered = _blocks(children, indent)
            lines.extend([f"> {line}" if line else ">" for line in rendered])
            lines.append("")
        elif kind in {"bulletList", "orderedList", "taskList"}:
            ordered = kind == "orderedList"
            start = int((node.get("attrs") or {}).get("start", 1))
            for index, item in enumerate(children):
                item_lines = _blocks(item.get("content") or [], indent + 1)
                while item_lines and not item_lines[-1]:
                    item_lines.pop()
                marker = f"{start + index}." if ordered else "-"
                if item_lines:
                    first = item_lines[0].lstrip()
                    lines.append(f"{prefix}{marker} {first}")
                    lines.extend(prefix + "  " + line for line in item_lines[1:])
                else:
                    lines.append(f"{prefix}{marker}")
            lines.append("")
        elif kind in {"table", "tableRow", "tableCell", "tableHeader"}:
            # TipTap tables are retained cell-by-cell in source order. Markdown
            # table syntax is synthesized only at row level.
            if kind == "table":
                rows = []
                for row in children:
                    rows.append([" ".join(_inline(cell).split()) for cell in row.get("content") or []])
                for index, row in enumerate(rows):
                    lines.append("| " + " | ".join(row) + " |")
                    if index == 0:
                        lines.append("| " + " | ".join("---" for _ in row) + " |")
                lines.append("")
        else:
            text = _inline(node)
            if text:
                lines.extend([prefix + text, ""])
            elif children:
                lines.extend(_blocks(children, indent))
    return lines


def export(db_path: Path, page_id: str, output: Path) -> None:
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        row = connection.execute("SELECT title, content FROM pages WHERE id = ?", (page_id,)).fetchone()
    if not row:
        raise ValueError(f"Atlas page not found: {page_id}")
    title, raw = row
    document = json.loads(raw)
    headings = sum(1 for node in document.get("content") or [] if node.get("type") == "heading")
    header = [
        f"# Especificación Atlas: {title}", "",
        f"- Página: `{page_id}`", f"- Fuente: `{db_path}`",
        "- Acceso: SQLite read-only (`mode=ro`); la base de datos no se modifica.",
        f"- Encabezados TipTap de nivel superior exportados: {headings}",
        "- Precedencia: las revisiones posteriores de la nota prevalecen sobre texto anterior cuando existe conflicto.",
        "", "---", "",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(header + _blocks(document.get("content") or [])).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db", type=Path)
    parser.add_argument("page_id")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    export(args.db, args.page_id, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

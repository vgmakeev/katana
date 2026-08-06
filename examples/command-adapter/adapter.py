from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    request = json.load(sys.stdin)
    source = Path(request["path"])
    lines = source.read_text().splitlines(keepends=True)
    symbols = []
    byte_offset = 0
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip("\r\n")
        if not line.startswith("section "):
            byte_offset += len(raw_line.encode())
            continue
        name = line.removeprefix("section ").strip()
        end_byte = byte_offset + len(raw_line.encode())
        symbols.append(
            {
                "name": name,
                "kind": "section",
                "signature": line,
                "start_line": line_number,
                "end_line": line_number,
                "start_byte": byte_offset,
                "end_byte": end_byte,
                "code_lines": 1,
                "references": [],
                "tags": [],
                "meta": {},
            }
        )
        byte_offset = end_byte
    sys.stdout.write(
        json.dumps(
            {
                "protocol_version": 1,
                "content_hash": request["content_hash"],
                "capabilities": {
                    "parser": "example_line_parser",
                    "strategy": "section_prefix",
                    "precision": "document_sections",
                    "safe_apply": False,
                    "capabilities": {
                        "outline": True,
                        "source_locations": True,
                    },
                    "limitations": ["example parser for protocol demonstration only"],
                },
                "symbols": symbols,
                "meta": {"request_content_hash": request["content_hash"]},
            }
        )
        + "\n"
    )


if __name__ == "__main__":
    main()

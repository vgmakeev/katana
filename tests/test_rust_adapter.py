from __future__ import annotations

import subprocess
from pathlib import Path

from katana import (
    SourceSplitMove,
    analyze_source_file,
    apply_source_split,
    source_parser_capabilities,
)

RUST_MODULE = """//! Example crate.

use std::fmt::Debug;

pub struct Thing {
    value: i32,
}

impl Thing {
    pub fn new(value: i32) -> Self {
        Self { value }
    }

    fn doubled(&self) -> i32 {
        helper(self.value) * 2
    }
}

#[inline]
fn helper(value: i32) -> i32 {
    value + 1
}
"""


def test_rust_map_exposes_exact_items_and_impl_methods(tmp_path: Path) -> None:
    source = tmp_path / "lib.rs"
    source.write_text(RUST_MODULE)

    document = analyze_source_file(source)
    payload = document.to_payload()

    assert document.adapter_id == "tree-sitter-rust"
    assert [symbol.name for symbol in document.symbols] == [
        "Thing",
        "Thing::new",
        "Thing::doubled",
        "helper",
    ]
    assert document.symbols[1].signature == "pub fn new(value: i32) -> Self"
    assert tuple(reference.name for reference in document.symbols[2].references) == ("helper",)
    assert payload["symbols"][3]["span"]["start_byte"] == RUST_MODULE.index("#[inline]")
    assert "value + 1" not in str(payload)
    assert source_parser_capabilities(source) == {
        "language": "rust",
        "parser": "tree_sitter_rust",
        "strategy": "tree_sitter_items",
        "precision": "syntax_top_level_and_impl_items",
        "safe_apply": True,
        "verifications": ["cargo_fmt", "cargo_check"],
        "limitations": ["moves preserve lexical scope through Rust include! fragments"],
    }


def test_rust_apply_moves_impl_items_without_changing_scope(tmp_path: Path) -> None:
    source = tmp_path / "lib.rs"
    target = tmp_path / "thing_methods.rs"
    source.write_text(RUST_MODULE)

    apply_source_split(
        source,
        (
            SourceSplitMove(
                target=target,
                symbols=("Thing::new", "Thing::doubled"),
            ),
        ),
        force=True,
    )

    assert 'include!("thing_methods.rs");' in source.read_text()
    assert "pub fn new(value: i32) -> Self" in target.read_text()
    assert "fn doubled(&self) -> i32" in target.read_text()
    completed = subprocess.run(
        ["rustc", "--edition=2024", "--crate-type=lib", str(source)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_rust_apply_moves_attributed_top_level_items(tmp_path: Path) -> None:
    source = tmp_path / "lib.rs"
    target = tmp_path / "helpers.rs"
    source.write_text(RUST_MODULE)

    apply_source_split(
        source,
        (SourceSplitMove(target=target, symbols=("helper",)),),
        force=True,
    )

    assert 'include!("helpers.rs");' in source.read_text()
    assert target.read_text().startswith("#[inline]\nfn helper")
    completed = subprocess.run(
        ["rustc", "--edition=2024", "--crate-type=lib", str(source)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr

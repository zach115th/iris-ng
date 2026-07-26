#!/usr/bin/env python3
"""Neutralize removed-`pkg_resources` imports in two pinned dependencies.

`setuptools >= 81` stopped shipping `pkg_resources`; `setuptools >= 83` is
required to fix a MANIFEST.in sdist-exclusion CVE. Two transitive deps still
import the removed module at module-load time on live app code paths, which
crash-loops gunicorn on boot:

  - docxcompose/properties.py     -> pkg_resources.resource_string(...) for a
    bundled XML template. CANNOT bump docxcompose: the vendored
    docx_generator==0.8.0 wheel hard-pins docxcompose==1.1.2 (and the whole
    reporter stack is deliberately frozen). So we rewrite the call to
    importlib.resources instead.
  - graphene_sqlalchemy/utils.py  -> pkg_resources.get_distribution(...).
    parsed_version version checks. Rewritten to importlib.metadata +
    packaging.version (packaging is already installed).

This runs at image-build time, AFTER `pip install`, inside the compile-image
stage, so the patched venv is what gets copied into the final image. It is:
  * content-matched via regex (tolerant of whitespace / line-number drift),
  * idempotent (a per-file marker short-circuits a re-run),
  * fail-loud: every target is asserted. If a future dependency bump moves the
    code, the build FAILS here instead of silently regressing.
"""
import re
import sysconfig
from pathlib import Path

PURELIB = Path(sysconfig.get_paths()["purelib"])


def apply(rel_path: str, subs, marker: str) -> None:
    path = PURELIB / rel_path
    if not path.is_file():
        raise SystemExit(f"[depatch] target file not found: {path}")
    text = path.read_text(encoding="utf-8")
    if marker in text:
        print(f"[depatch] already patched: {rel_path}")
        return
    for pattern, repl in subs:
        text, n = re.subn(pattern, repl, text)
        if n == 0:
            raise SystemExit(
                f"[depatch] expected pattern not found in {rel_path}:\n  {pattern!r}\n"
                "The dependency version likely changed; review and update this patch."
            )
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"[depatch] patched: {rel_path}")


# docxcompose 1.1.2 -- bundled-template read
apply(
    "docxcompose/properties.py",
    [
        (
            r"(?m)^import pkg_resources\b",
            "import importlib.resources as _iris_ir  # depatched: pkg_resources removed in setuptools>=81",
        ),
        (
            r"pkg_resources\.resource_string\(\s*'docxcompose'\s*,\s*'templates/custom\.xml'\s*\)",
            "_iris_ir.files('docxcompose').joinpath('templates/custom.xml').read_bytes()",
        ),
    ],
    marker="_iris_ir",
)

# graphene-sqlalchemy 3.0.0rc1 -- installed-version comparisons
apply(
    "graphene_sqlalchemy/utils.py",
    [
        (
            r"(?m)^import pkg_resources\b",
            "from importlib.metadata import version as _iris_dist_version  # depatched\n"
            "from packaging.version import parse as _iris_parse_version",
        ),
        (
            r"pkg_resources\.get_distribution\(\s*\"SQLAlchemy\"\s*\)\.parsed_version\s*<\s*"
            r"pkg_resources\.parse_version\(version_string\)",
            '_iris_parse_version(_iris_dist_version("SQLAlchemy")) < _iris_parse_version(version_string)',
        ),
        (
            r"pkg_resources\.get_distribution\(\s*\"graphene\"\s*\)\.parsed_version\s*<\s*"
            r"pkg_resources\.parse_version\(version_string\)",
            '_iris_parse_version(_iris_dist_version("graphene")) < _iris_parse_version(version_string)',
        ),
    ],
    marker="_iris_parse_version",
)

print("[depatch] done")

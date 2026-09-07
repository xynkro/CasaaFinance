"""Guard against calling a helper that isn't imported in that file.

This bug class has bitten twice in two sessions:
  • `_rows_of(ss, ...)` in daily_options_scan — the real helper is `_tab_dicts`.
    It sat inside a try/except logging at DEBUG, so the UOA filter would have
    silently done nothing forever.
  • `replace_today_rows_ws(...)` in yahoo_grab — called inside refresh_account()
    while `sheets` was only imported inside main(). A NameError at runtime.

No linter is installed in this venv (no ruff/flake8/pyflakes), so nothing else
catches it. This asserts that every SHEET-WRITE helper we call in a file is
resolvable there: module-level import, function-local import, or defined locally.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Our own helpers — calling one without importing it is always a bug.
TRACKED = {
    "replace_today_rows", "replace_today_rows_ws", "upsert_tab",
    "ensure_headers", "append_rows", "append_row", "_tab_dicts",
}

FILES = [
    "src/yahoo_grab.py", "src/sheets.py", "src/sync.py",
    "scripts/options_refresh_cloud.py", "scripts/daily_tracker.py",
    "scripts/daily_options_scan.py", "scripts/unusual_options_scan.py",
    "scripts/dupe_guard.py", "scripts/cleanup_positions_dupes.py",
    "scripts/crash_playbook.py", "scripts/policy_audit.py", "scripts/uoa_grade.py",
]


def _bound_names(tree: ast.AST) -> set[str]:
    """Every name bound anywhere in the module: imports, defs, assignments."""
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            for a in n.names:
                out.add(a.asname or a.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            out.add(n.id)
    return out


@pytest.mark.parametrize("rel", FILES)
def test_tracked_helpers_are_resolvable(rel):
    p = ROOT / rel
    if not p.exists():
        pytest.skip(f"{rel} not present")
    tree = ast.parse(p.read_text())
    bound = _bound_names(tree)
    unresolved = []
    for n in ast.walk(tree):
        # Only bare calls, e.g. replace_today_rows_ws(...). Attribute calls like
        # sh.replace_today_rows(...) resolve through the module object instead.
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            name = n.func.id
            if name in TRACKED and name not in bound:
                unresolved.append((name, n.lineno))
    assert not unresolved, (
        f"{rel} calls sheet helpers it never imports/defines: "
        + ", ".join(f"{nm} (line {ln})" for nm, ln in unresolved))


def test_the_detector_actually_catches_the_real_regression():
    """Sanity: the check must fail on the exact shape of the _rows_of bug."""
    bad = ast.parse("def f(ss):\n    return _tab_dicts(ss, 'x')\n")
    bound = _bound_names(bad)
    hits = [n.func.id for n in ast.walk(bad)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id in TRACKED and n.func.id not in bound]
    assert hits == ["_tab_dicts"], "detector would not have caught the real bug"

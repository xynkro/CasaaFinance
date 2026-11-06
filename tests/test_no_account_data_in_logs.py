"""Guard: no account data in anything printed or logged by scripts/ and src/.

This repo and its GitHub Actions logs are PUBLIC. A review (3 Nov 2026) found
job logs carrying real balances, cash, position values and P&L. This test is the
standing guard so that does not come back.

WHAT IT CHECKS
  An AST pass over every ``print(...)`` and ``logger.*(...)`` / ``log.*(...)``
  call in ``scripts/`` and ``src/``. A call FAILS when its arguments (including
  the interpolations inside an f-string) reference an identifier that names
  account data: nlv, net_liq / netliq, cash, upl, mkt_val, market_value, qty,
  quantity. An "identifier" is a variable name, an attribute (``x.cash``), a
  string subscript key (``snap["net_liq_usd"]``) or a ``.get("cash")`` key.
  Matching is by substring, except ``upl`` which needs token boundaries so that
  duplicate / couple / upload do not trip it.

  It also follows ONE hop: a variable assigned from a string-building
  expression (f-string, ``.join``, ``.format``, ``%`` / ``+`` on a string) that
  interpolates such an identifier is itself treated as sensitive when it is
  later logged in the same function. That is how ``snap_desc`` and the
  mechanical-lane ``summary`` leaked.

WHAT IS EXEMPT
  * ``len(...)`` and ``bool(...)``: a count or a True/False presence flag is the
    sanctioned way to log these. Anything inside them is ignored.
  * Code that cannot run when ``GITHUB_ACTIONS`` is set: statements after an
    ``if os.environ.get("GITHUB_ACTIONS"): ... return`` guard in the same block,
    the ``else`` of such an ``if``, or the body of ``if not <same test>``. This is
    how the ``--dry`` previews work: manual dispatch can reach ``--dry`` in a
    public log, so Actions gets a count and a local run keeps the full preview.
    (TestGuardedPreviews below pins each gated preview so the guard cannot be
    dropped quietly.)
  * The explicit ALLOWLIST below: paths that never run in Actions at all.

KNOWN LIMITS (it is a guard, not a taint engine)
  A value that reaches a log through a function return, a loop variable or a
  container is not followed. ``crash_playbook`` builds a whole report string
  through ``render(...)``; that one is covered by a behaviour test below
  instead. Read ``git diff`` when you touch a log line near account data.
"""
from __future__ import annotations

import ast
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCAN_DIRS = ("scripts", "src")

# net_?liq covers net_liq and netliq. `upl` is boundary-checked (see docstring).
SENSITIVE = re.compile(
    r"nlv|net_?liq|cash|mkt_val|market_value|qty|quantity|(?<![a-z])upl(?![a-z])",
    re.I,
)
LOG_RECEIVERS = {"logger", "log", "logging"}
LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}
COUNT_WRAPPERS = {"len", "bool"}


# ───────────────────────── allowlist ─────────────────────────────────────────
# Sites that match the pattern but never run in GitHub Actions (or are not
# account data). Every entry needs a reason. `snippet` is matched against the
# unparsed source of the offending call; None means the whole file. An entry
# that stops matching anything fails test_allowlist_has_no_stale_entries, so
# this list cannot rot.

@dataclass(frozen=True)
class Allow:
    path: str
    snippet: str | None
    reason: str


ALLOWLIST = [
    Allow("scripts/daily_tracker.py", None,
          "Local-only: run by launchd (com.caspar.daily-tracker.plist) or by hand "
          "(bin/casaa). No workflow invokes it."),
    Allow("src/ibkr_grab.py", None,
          "Local-only: grabs from a local TWS/Gateway session, which a runner "
          "cannot have. Run by hand or via bin/casaa."),
    Allow("scripts/risk_parity_recommend.py", None,
          "Local-only: commented out of risk-parity-audit.yml (RETIRED 2026-06-04); "
          "only reachable via `bin/casaa rp-recs`."),
    Allow("scripts/ibkr_flex_sync.py", "NLV $",
          "Interactive no-flag branch (account header line). The workflow only "
          "calls --fields and --sync, which log field names and counts."),
    Allow("scripts/ibkr_flex_sync.py", "UPL $",
          "Interactive no-flag branch (per-position rows). Same as above."),
    Allow("src/sync.py", "qty={o.qty",
          "`sync.py dryrun` subcommand. No workflow runs src/sync.py; only "
          "load_env() is imported from it."),
    Allow("scripts/market_scan.py", "cash=$",
          "Not account data: cash_required is strike x 100, the collateral a "
          "candidate put WOULD need. Same value for anyone."),
]
# (The trigger_alerts `[DRY]` entry that used to be here is gone: that block now
# returns early with counts when GITHUB_ACTIONS is set, which the detector
# recognises, so the full preview no longer needs an allowlist entry.)


# ───────────────────────── detector ──────────────────────────────────────────

@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    names: tuple[str, ...]      # sensitive identifiers referenced directly
    via: tuple[str, ...]        # prebuilt-string variables that carry them
    source: str                 # unparsed call, used for allowlist matching

    def describe(self) -> str:
        bits = list(self.names) + [f"{v} (built from sensitive names)" for v in self.via]
        return f"{self.path}:{self.line}: log call references {', '.join(bits)}"


def _snake(name: str) -> str:
    """camelCase -> camel_Case so token boundaries work on either style."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)


def _walk(node: ast.AST):
    """ast.walk that does not descend into len(...) / bool(...)."""
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in COUNT_WRAPPERS):
        return
    yield node
    for child in ast.iter_child_nodes(node):
        yield from _walk(child)


def _identifiers(node: ast.AST) -> list[str]:
    out: list[str] = []
    for n in _walk(node):
        if isinstance(n, ast.Name):
            out.append(n.id)
        elif isinstance(n, ast.Attribute):
            out.append(n.attr)
        elif (isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant)
              and isinstance(n.slice.value, str)):
            out.append(n.slice.value)
        elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "get" and n.args
              and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)):
            out.append(n.args[0].value)
    return out


def _sensitive(node: ast.AST) -> set[str]:
    return {i for i in _identifiers(node) if SENSITIVE.search(_snake(i))}


def _builds_string(v: ast.AST) -> bool:
    if isinstance(v, ast.BoolOp):
        return any(_builds_string(x) for x in v.values)
    if isinstance(v, ast.IfExp):
        return _builds_string(v.body) or _builds_string(v.orelse)
    if isinstance(v, ast.JoinedStr):
        return True
    if isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute) and v.func.attr in ("join", "format"):
        return True
    if isinstance(v, ast.BinOp) and isinstance(v.op, (ast.Mod, ast.Add)):
        return any(isinstance(x, ast.JoinedStr)
                   or (isinstance(x, ast.Constant) and isinstance(x.value, str))
                   for x in (v.left, v.right))
    return False


def _is_log_call(call: ast.Call) -> bool:
    f = call.func
    if isinstance(f, ast.Name) and f.id == "print":
        return True
    return (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
            and f.value.id in LOG_RECEIVERS and f.attr in LOG_METHODS)


def _scopes(tree: ast.AST):
    """(scope, nodes owned by that scope) for the module and every function."""
    def own(node):
        for c in ast.iter_child_nodes(node):
            if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            yield c
            yield from own(c)

    yield tree, list(own(tree))
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield n, list(own(n))


def _is_actions_flag(expr: ast.AST) -> bool:
    """os.environ.get("GITHUB_ACTIONS") / os.getenv("GITHUB_ACTIONS") / os.environ["GITHUB_ACTIONS"]."""
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute) \
            and expr.func.attr in ("get", "getenv") and expr.args:
        a0 = expr.args[0]
        return isinstance(a0, ast.Constant) and a0.value == "GITHUB_ACTIONS"
    if isinstance(expr, ast.Subscript) and isinstance(expr.slice, ast.Constant):
        return expr.slice.value == "GITHUB_ACTIONS"
    return False


def local_only_ids(tree: ast.AST) -> set[int]:
    """ids of every node that cannot execute when GITHUB_ACTIONS is set.

    Three shapes, all keyed on a test that is exactly the GITHUB_ACTIONS flag
    (or its `not`), so a compound condition never grants an exemption:
      if FLAG: ...; return/raise   -> every later statement in that block
      if FLAG: ... else: <local>   -> the else branch
      if not FLAG: <local>         -> the body
    """
    ids: set[int] = set()

    def mark(stmts):
        for s in stmts:
            for n in ast.walk(s):
                ids.add(id(n))

    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            stmts = getattr(node, field, None)
            if not isinstance(stmts, list):
                continue
            for i, s in enumerate(stmts):
                if not isinstance(s, ast.If):
                    continue
                negated = isinstance(s.test, ast.UnaryOp) and isinstance(s.test.op, ast.Not)
                flag = s.test.operand if negated else s.test
                if not _is_actions_flag(flag):
                    continue
                if negated:
                    mark(s.body)
                else:
                    mark(s.orelse)
                    if s.body and isinstance(s.body[-1], (ast.Return, ast.Raise)):
                        mark(stmts[i + 1:])
    return ids


def find_leaks(source: str, path: str = "<sample>") -> list[Finding]:
    """Every print/logger call in `source` that references account-data names
    and could run in Actions."""
    tree = ast.parse(source)
    local_only = local_only_ids(tree)
    found: list[Finding] = []
    for _scope, nodes in _scopes(tree):
        # variable -> sensitive names baked into the string it was built from
        tainted: list[tuple[int, str, set[str]]] = []
        for n in nodes:
            if isinstance(n, ast.Assign):
                targets, value = n.targets, n.value
            elif isinstance(n, (ast.AnnAssign, ast.AugAssign)) and n.value is not None:
                targets, value = [n.target], n.value
            else:
                continue
            names = _sensitive(value) if _builds_string(value) else set()
            for sub in _walk(value):
                if isinstance(sub, ast.JoinedStr):
                    names |= _sensitive(sub)
            if not names:
                continue
            for t in targets:
                for nm in ast.walk(t):
                    if isinstance(nm, ast.Name) and isinstance(nm.ctx, ast.Store):
                        tainted.append((n.lineno, nm.id, names))

        for n in nodes:
            if not (isinstance(n, ast.Call) and _is_log_call(n)) or id(n) in local_only:
                continue
            parts = list(n.args) + [k.value for k in n.keywords]
            direct: set[str] = set()
            via: set[str] = set()
            for part in parts:
                direct |= _sensitive(part)
                for sub in _walk(part):
                    if (isinstance(sub, ast.Name) and not SENSITIVE.search(_snake(sub.id))
                            and any(v == sub.id and ln < n.lineno for ln, v, _ in tainted)):
                        via.add(sub.id)
            if direct or via:
                found.append(Finding(path, n.lineno, tuple(sorted(direct)),
                                     tuple(sorted(via)), ast.unparse(n)))
    return found


def scan_repo() -> list[Finding]:
    out: list[Finding] = []
    for d in SCAN_DIRS:
        for p in sorted((ROOT / d).rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            rel = p.relative_to(ROOT).as_posix()
            out.extend(find_leaks(p.read_text(encoding="utf-8"), rel))
    return out


def _allowed(f: Finding) -> Allow | None:
    for a in ALLOWLIST:
        if a.path == f.path and (a.snippet is None or a.snippet in f.source):
            return a
    return None


# ───────────────────────── the guard ─────────────────────────────────────────

def test_no_account_data_in_logs():
    leaks = [f for f in scan_repo() if _allowed(f) is None]
    assert not leaks, (
        "print/logger calls that would put account data in a PUBLIC log "
        "(log a count, a field name or a True/False presence flag instead; "
        "len() and bool() are exempt):\n  " + "\n  ".join(f.describe() for f in leaks)
    )


def test_allowlist_has_no_stale_entries():
    raw = scan_repo()
    stale = [a for a in ALLOWLIST
             if not any(f.path == a.path and (a.snippet is None or a.snippet in f.source)
                        for f in raw)]
    assert not stale, "allowlist entries that no longer match anything: " + ", ".join(
        f"{a.path} [{a.snippet}]" for a in stale)
    assert all(a.reason.strip() for a in ALLOWLIST)


# ───────────────── proof the detector actually catches leaks ─────────────────
# Inline samples shaped like the real leaks. If the detector were broken (or
# loosened too far) these would stop failing and this block would go red.

LEAKY_SAMPLES = {
    "f-string interpolation (yahoo_grab / build_daily_plan shape)":
        'logger.info(f"Snapshot: net_liq={net_liq:.2f} cash={cash:.2f}")',
    "plain print of a position quantity (paper executor shape)":
        'print(f"PLAN {label}  x{qty}")',
    "string-subscript key (exposure_posture_run shape)":
        'logger.info(f"caspar {snap_c.get(\'net_liq_usd\', \'n/a\')}")',
    ".get() key inside an f-string (trigger_alerts snap_desc shape)":
        'logger.info(f"{a} {s.get(\'nlv\', 0):,.0f}")',
    "attribute access":
        'log.warning("balance %s", account.cash)',
    "%-style logger args":
        'logger.info("NLV=%s", nlv)',
    "keyword argument value":
        'print("x", sep=str(upl))',
    "via a prebuilt string (snap_desc shape)":
        'def main():\n'
        '    desc = ", ".join(f"{a} {s[\'nlv\']}" for a, s in snaps.items()) or "none"\n'
        '    logger.info(f"Lane plans (snapshots: {desc})")\n',
    "via a prebuilt f-string (summary / size_note shape)":
        'def main():\n'
        '    note = f"Size: ~${pct * nlv:,.0f}"\n'
        '    logger.info(note)\n',
    "camelCase name":
        'print(totalCash)',
}


@pytest.mark.parametrize("why", sorted(LEAKY_SAMPLES))
def test_detector_flags_known_leak_shapes(why):
    found = find_leaks(LEAKY_SAMPLES[why])
    assert found, f"detector missed a leak: {why}"


CLEAN_SAMPLES = {
    "a count":
        'logger.info(f"{len(positions)} positions, {len(cash_rows)} cash rows")',
    "a True/False presence flag":
        'logger.info(f"snapshots present: caspar {bool(snap_c)}, sarah {bool(snap_s)}")',
    "field names as plain text":
        'logger.info("columns: net_liq, cash, upl")',
    "unrelated names that merely contain the letters":
        'print(f"{n_duplicates} duplicates, {uploaded} uploaded, {couple}")',
    "a prebuilt string with no sensitive name":
        'def main():\n    d = ", ".join(f"{a}={n}" for a, n in c.items())\n    logger.info(d)\n',
    "not a log call":
        'total = cash + nlv\nrow = [qty, upl]\n',
    "a non-logger receiver":
        'results.info(f"{cash}")',
}


@pytest.mark.parametrize("why", sorted(CLEAN_SAMPLES))
def test_detector_accepts_counts_and_presence(why):
    assert find_leaks(CLEAN_SAMPLES[why]) == [], why


def test_a_new_leak_in_an_otherwise_clean_file_would_fail_the_guard():
    """End to end: a Finding that matches no allowlist entry is reported."""
    f = find_leaks('logger.info(f"NLV={nlv}")', "scripts/brand_new_script.py")[0]
    assert _allowed(f) is None


def test_allowlist_is_path_scoped():
    """An allowlisted snippet in one file must not excuse the same text elsewhere."""
    f = find_leaks('print(f"Account  NLV ${nlv}")', "scripts/growth_scan.py")[0]
    assert _allowed(f) is None
    f = find_leaks('print(f"Account  NLV ${nlv}")', "scripts/ibkr_flex_sync.py")[0]
    assert _allowed(f) is not None


# ───────────── GITHUB_ACTIONS guards: what is and is not local-only ──────────

GUARD = 'os.environ.get("GITHUB_ACTIONS")'

GUARDED_SAMPLES = {
    "after an early-exit guard (the --dry preview shape)":
        f'def main():\n    if args.dry:\n        if {GUARD}:\n            print(f"{{len(rows)}} rows")\n'
        f'            return 0\n        print(f"cash {{cash}}")\n        return 0\n',
    "the else branch of the flag (the crash_playbook shape)":
        f'if {GUARD}:\n    print("status")\nelse:\n    print(f"cash {{cash}}")\n',
    "under `if not flag`":
        f'if not {GUARD}:\n    for t in held:\n        logger.info(f"{{t}} {{qty}}")\n',
    "os.getenv spelling":
        'if not os.getenv("GITHUB_ACTIONS"):\n    print(qty)\n',
    "subscript spelling":
        'if not os.environ["GITHUB_ACTIONS"]:\n    print(qty)\n',
}


@pytest.mark.parametrize("why", sorted(GUARDED_SAMPLES))
def test_code_that_cannot_run_in_actions_is_exempt(why):
    assert find_leaks(GUARDED_SAMPLES[why]) == [], why


UNGUARDED_SAMPLES = {
    "a leak BEFORE the guard still runs in Actions":
        f'def main():\n    print(f"cash {{cash}}")\n    if {GUARD}:\n        return 0\n',
    "a leak INSIDE the Actions branch is the branch that runs in Actions":
        f'if {GUARD}:\n    print(f"cash {{cash}}")\n',
    "a guard that does not exit exempts nothing after it":
        f'if {GUARD}:\n    print("ci")\nprint(f"cash {{cash}}")\n',
    "a compound condition grants no exemption":
        f'if {GUARD} or verbose:\n    print("x")\n    return 0\nprint(qty)\n',
    "a different env var is not the Actions flag":
        'if not os.environ.get("CI"):\n    print(qty)\n',
    "the negated branch's else runs in Actions":
        f'if not {GUARD}:\n    print("local")\nelse:\n    print(qty)\n',
}


@pytest.mark.parametrize("why", sorted(UNGUARDED_SAMPLES))
def test_guard_lookalikes_do_not_hide_a_leak(why):
    assert find_leaks(UNGUARDED_SAMPLES[why]), why


# These dry-run previews name held tickers or account figures, and a manual
# `dry` dispatch can reach them in a public log. Each must stay behind a
# GITHUB_ACTIONS guard. Most carry no sensitive NAME (just tickers), so the
# detector above cannot see them: this table is what stops the guard being
# deleted quietly. (path, a fragment of the preview call's unparsed source.)
GATED_PREVIEWS = [
    ("scripts/trigger_alerts.py", "[DRY] would fire ACT_NOW"),
    ("scripts/trigger_alerts.py", "[DRY] would fire DEFENSE"),
    ("scripts/trigger_alerts.py", "[DRY] would fire CONCENTRATION"),
    ("scripts/exposure_posture_run.py", "[dry] rationale"),
    ("scripts/risk_parity_audit.py", "_print_dry_table(all_rows)"),
    ("scripts/tv_signals_run.py", "row[1]"),
    ("scripts/screen_gov_confluence.py", "politicians, $"),
    ("scripts/crash_playbook.py", "print(report)"),
]
# Deliberately NOT gated (a small top-N sample of idea candidates, or news /
# earnings rows for a mixed watchlist universe, cannot tell a reader what is
# held): options_yield_screener, finnhub_news_insider, finnhub_calendars,
# daily_options_scan, signal_feedback.


PREVIEW_HELPERS = {"_print_dry_table"}      # a helper whose whole job is to print the table


def _is_preview_call(n: ast.AST) -> bool:
    return isinstance(n, ast.Call) and (
        _is_log_call(n) or (isinstance(n.func, ast.Name) and n.func.id in PREVIEW_HELPERS))


@pytest.mark.parametrize("path,fragment", GATED_PREVIEWS)
def test_dry_previews_stay_behind_the_actions_guard(path, fragment):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    local_only = local_only_ids(tree)
    hits = [n for n in ast.walk(tree) if _is_preview_call(n) and fragment in ast.unparse(n)]
    assert hits, f"{path}: no print/log call contains {fragment!r}; update GATED_PREVIEWS"
    exposed = [n.lineno for n in hits if id(n) not in local_only]
    assert not exposed, (
        f"{path}:{exposed}: {fragment!r} would run in GitHub Actions; keep it behind "
        "`if os.environ.get(\"GITHUB_ACTIONS\")` (print a count there instead)")


# ───────────── the held-book scripts log no ticker names at all ──────────────
# The sensitive-NAME check cannot see a ticker (it is just a string), and these
# three scripts work on the real book, so every log line in them that could run
# in Actions must be ticker-free: counts, the account name, or an exception TYPE.
# (refresh_exit_plans and tv_price_refresh are left out only because each has one
# unreachable-from-Actions line: a logger.debug, and a --dry loop no workflow passes.)

TICKER_NAME = re.compile(r"ticker|^tk$|^t$|^orig$|matched|symbol", re.I)
TICKER_FREE_LOG_FILES = [
    "scripts/trigger_alerts.py",
    "src/yahoo_grab.py",
    "scripts/options_refresh_cloud.py",
]


@pytest.mark.parametrize("path", TICKER_FREE_LOG_FILES)
def test_held_book_scripts_log_no_ticker_names(path):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    local_only = local_only_ids(tree)
    named = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and _is_log_call(n)) or id(n) in local_only:
            continue
        hits = {i for part in list(n.args) + [k.value for k in n.keywords]
                for i in _identifiers(part) if TICKER_NAME.search(i)}
        if hits:
            named.append(f"{path}:{n.lineno}: {sorted(hits)}")
    assert not named, ("log lines that would name a ticker in a PUBLIC log "
                       "(log a count, the account name or the exception type):\n  " + "\n  ".join(named))


def test_ticker_free_check_flags_a_ticker_in_a_log_line():
    """Proof the check above is not vacuous."""
    src = 'logger.warning(f"  {d.ticker} {d.account}: {e}")\nlogger.info(f"tickers: {matched}")\n'
    tree = ast.parse(src)
    flagged = [n for n in ast.walk(tree)
               if isinstance(n, ast.Call) and _is_log_call(n)
               and any(TICKER_NAME.search(i) for part in n.args for i in _identifiers(part))]
    assert len(flagged) == 2


# ───────────────── behaviour: report text still reaches its destination ─────

class _FakeWS:
    def __init__(self, rows):
        self._rows = rows

    def get_all_values(self):
        return self._rows


class _FakeSheet:
    TABS = {
        "macro": [["date", "spx"], ["2026-11-01", "5000"], ["2026-11-02", "4900"]],
        "positions_caspar": [["date", "ticker", "mkt_val"], ["2026-11-02", "AAA", "1000"]],
        "snapshot_caspar": [["date", "net_liq_usd", "cash"], ["2026-11-02", "12345", "6789"]],
    }

    def worksheet(self, name):
        return _FakeWS(self.TABS[name])


def _run_crash_playbook(monkeypatch, capsys, *, in_actions: bool, telegram: bool):
    from scripts import crash_playbook as cp
    from src import telegram as tg

    sent: list[str] = []
    monkeypatch.setattr(cp, "load_env", lambda: None)
    monkeypatch.setattr(cp.sh, "authenticate", lambda: object())
    monkeypatch.setattr(cp.sh, "_open_sheet", lambda client: _FakeSheet())
    monkeypatch.setattr(tg, "send", lambda text, **kw: sent.append(text))
    monkeypatch.setattr(sys, "argv", ["crash_playbook"] + (["--telegram"] if telegram else []))
    if in_actions:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
    else:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert cp.main() == 0
    return capsys.readouterr().out, sent


def test_crash_playbook_prints_one_status_line_in_actions_but_still_dms_the_report(
        monkeypatch, capsys):
    out, sent = _run_crash_playbook(monkeypatch, capsys, in_actions=True, telegram=True)
    assert "[crash-playbook]" in out
    for secret in ("12,345", "6,789", "NLV", "cash $", "HEDGE SLEEVE"):
        assert secret not in out, f"{secret!r} reached the Actions log"
    # The DM is byte-for-byte the full report.
    assert len(sent) == 1
    assert "cash $6,789 of $12,345 NLV" in sent[0]
    assert "HEDGE SLEEVE" in sent[0]


def test_crash_playbook_prints_the_full_report_locally(monkeypatch, capsys):
    out, sent = _run_crash_playbook(monkeypatch, capsys, in_actions=False, telegram=False)
    assert "cash $6,789 of $12,345 NLV" in out
    assert "[crash-playbook]" not in out
    assert sent == []


def test_crash_playbook_report_is_identical_in_both_modes(monkeypatch, capsys):
    _, sent_ci = _run_crash_playbook(monkeypatch, capsys, in_actions=True, telegram=True)
    _, sent_local = _run_crash_playbook(monkeypatch, capsys, in_actions=False, telegram=True)
    assert sent_ci == sent_local


# ───────────────── secrets: keys must not ride in URLs ───────────────────────

TOKEN = "123456:SECRET-BOT-TOKEN"


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self.ok = status < 400
        self.text = "boom"
        self._payload = payload if payload is not None else {}

    def raise_for_status(self):
        import requests
        if not self.ok:
            raise requests.HTTPError(
                f"{self.status_code} Client Error: Bad for url: "
                f"https://api.telegram.org/bot{TOKEN}/sendMessage", response=self)

    def json(self):
        return self._payload


def test_telegram_http_error_carries_no_url_and_is_a_plain_exception(monkeypatch):
    from src import telegram as tg
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(tg.requests, "post", lambda *a, **k: _Resp(403))
    with pytest.raises(RuntimeError) as ei:
        tg.send("hi", chat_id=tg.PERSONAL_CHAT_ID)
    assert str(ei.value) == "telegram http 403"
    assert TOKEN not in repr(ei.value)
    assert ei.value.__cause__ is None and ei.value.__suppress_context__
    assert isinstance(ei.value, Exception)      # every caller does `except Exception`


def test_telegram_connection_error_carries_no_url(monkeypatch):
    import requests
    from src import telegram as tg
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)

    def boom(*a, **k):
        raise requests.ConnectionError(f"Max retries exceeded with url: /bot{TOKEN}/sendMessage")

    monkeypatch.setattr(tg.requests, "post", boom)
    with pytest.raises(RuntimeError) as ei:
        tg.send("hi", chat_id=tg.PERSONAL_CHAT_ID)
    assert TOKEN not in str(ei.value)
    assert "ConnectionError" in str(ei.value)


def test_telegram_success_path_is_unchanged(monkeypatch):
    from src import telegram as tg
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(tg.requests, "post", lambda *a, **k: _Resp(200, {"ok": True, "result": 1}))
    assert tg.send("hi", chat_id=tg.PERSONAL_CHAT_ID) == {"ok": True, "result": 1}


class _CaptureGet:
    """Stands in for requests.get; remembers how it was called."""

    def __init__(self):
        self.calls = []

    def __call__(self, url, **kw):
        self.calls.append((url, kw))
        return _Resp(200, {})


def _assert_key_in_header_only(cap: _CaptureGet):
    calls = [(u, kw) for u, kw in cap.calls if "finnhub.io" in u or u.startswith("some/")]
    assert calls, "no Finnhub request was made"
    for url, kw in calls:
        assert kw["headers"] == {"X-Finnhub-Token": "KEY"}
        assert "token" not in (kw.get("params") or {})
        assert "token=" not in url


@pytest.mark.parametrize("modname", ["finnhub_analyst", "finnhub_news_insider", "finnhub_calendars"])
def test_finnhub_scripts_send_the_key_as_a_header(monkeypatch, modname):
    import importlib
    mod = importlib.import_module(f"scripts.{modname}")
    cap = _CaptureGet()
    monkeypatch.setenv("FINNHUB_API_KEY", "KEY")
    monkeypatch.setattr(mod.requests, "get", cap)
    mod._fh_get("some/path", {"symbol": "X"}, logging.getLogger("t"))
    _assert_key_in_header_only(cap)
    assert cap.calls[0][1]["params"] == {"symbol": "X"}      # other params untouched


def test_screen_gov_confluence_sends_the_key_as_a_header(monkeypatch):
    import requests
    from scripts import screen_gov_confluence as sg
    cap = _CaptureGet()
    monkeypatch.setenv("FINNHUB_API_KEY", "KEY")
    monkeypatch.setattr(requests, "get", cap)
    sg._finnhub_market_cap("XYZ")
    _assert_key_in_header_only(cap)
    assert cap.calls[0][1]["params"] == {"symbol": "XYZ"}


def test_macro_feed_sends_the_key_as_a_header(monkeypatch):
    from src import macro_blackouts as mb
    from src import news_aggregator as na
    cap = _CaptureGet()
    monkeypatch.setattr(mb.requests, "get", cap)
    monkeypatch.setattr(na, "aggregate_rss", lambda timeout=0: [])   # keep it hermetic
    feed = mb.MacroFeed()
    feed._refresh_calendar("KEY", 1.0)
    feed._refresh_news("KEY", 1.0)
    urls = [u for u, _ in cap.calls]
    assert any(u.endswith("/calendar/economic") for u in urls)
    assert any(u.endswith("/news") for u in urls)
    _assert_key_in_header_only(cap)


def test_newsdata_failure_logs_the_exception_type_not_its_text(monkeypatch, caplog):
    import requests
    from src import news_aggregator as na
    monkeypatch.setenv("NEWSDATA_API_KEY", "SECRETKEY")

    def boom(url, **kw):
        raise requests.HTTPError(f"403 Client Error: Forbidden for url: {url}")

    monkeypatch.setattr(na.requests, "get", boom)
    with caplog.at_level(logging.WARNING):
        assert na.fetch_newsdata() == []
    assert "HTTPError" in caplog.text
    assert "SECRETKEY" not in caplog.text

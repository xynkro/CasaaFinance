"""Sarah's book from the IBKR Flex Web Service (SGD base account).

Everything here is SYNTHETIC: obviously round numbers, placeholder tickers,
and a made-up FX rate of 1.25. The repo is public — no real holdings,
balances, tokens or query ids belong in this file.

What these pin down:
  * UNITS — position rows stay in the position's NATIVE currency (what the TWS
    grab wrote and what yahoo_grab / the PWA's toAcctCcy assume), while the
    snapshot totals are SGD. Converting position rows here would make the PWA
    apply the USD->SGD rate a second time.
  * Both ways Sarah can show up (second report / linked in the main report).
  * She can never clobber her Sheet rows with emptiness, and a failure on her
    side can never fail Caspar's sync or leak a token.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.ibkr_flex_sync import (  # noqa: E402
    CASPAR_ACCOUNT,
    SARAH_ACCOUNT,
    SarahDataError,
    _sarah_from_report,
    build_flex_grab,
    parse_account,
    parse_open_positions,
    resolve_sarah,
    run_sync,
)
from src.schema import positions_sarah_from_grab, snapshot_sarah_from_grab  # noqa: E402

TOKEN = "SYNTH-TOKEN-0000"
QID = "SYNTH-QID-0000"
CREDS = {"IB_FLEX_TOKEN_SARAH": TOKEN, "IB_FLEX_QUERY_ID_SARAH": QID}
USDSGD = 1.25   # synthetic


# ── synthetic Flex XML ───────────────────────────────────────────────────────

def _attrs(d: dict) -> str:
    return " ".join(f'{k}="{v}"' for k, v in d.items() if v is not None)


def _op(acct, asset, symbol, qty, mark, value, cost_price, cost_money, upl, ccy, fx, **extra):
    d = dict(accountId=acct, assetCategory=asset, symbol=symbol, position=qty,
             markPrice=mark, positionValue=value, costBasisPrice=cost_price,
             costBasisMoney=cost_money, fifoPnlUnrealized=upl, currency=ccy,
             fxRateToBase=fx, levelOfDetail="SUMMARY")
    d.update(extra)
    return f"<OpenPosition {_attrs(d)}/>"


def _stmt(acct, *, base, total, cash, stock, options=0, positions=(), info=True,
          equity=True, stmt_acct=True, eq_acct=True):
    parts = []
    if info:
        parts.append(f"<AccountInformation {_attrs(dict(accountId=acct, currency=base))}/>")
    if equity:
        eq = dict(accountId=acct if eq_acct else None, currency=base, reportDate="20260101",
                  cash=cash, stock=stock, options=options, total=total)
        parts.append(f"<EquitySummaryInBase><EquitySummaryByReportDateInBase {_attrs(eq)}/>"
                     "</EquitySummaryInBase>")
    parts.append("<OpenPositions>" + "".join(positions) + "</OpenPositions>")
    head = f' accountId="{acct}"' if stmt_acct else ""
    return f'<FlexStatement{head} fromDate="20260101" toDate="20260101">{"".join(parts)}</FlexStatement>'


def _report(*stmts):
    return (f'<FlexQueryResponse queryName="synthetic" type="AF">'
            f'<FlexStatements count="{len(stmts)}">{"".join(stmts)}</FlexStatements>'
            f"</FlexQueryResponse>")


def _sarah_positions(acct=SARAH_ACCOUNT):
    return [
        # USD stock in an SGD-base account: native values in USD, fx USD->SGD
        _op(acct, "STK", "AAA", 10, 100, 1000, 80, 800, 200, "USD", USDSGD),
        # SGX stock: native SGD == base, fx 1
        _op(acct, "STK", "BBB", 100, 3, 300, 2.8, 280, 20, "SGD", 1),
        # short put on the USD name (value/cost negative for a short)
        _op(acct, "OPT", "AAA 260320P90", -1, 2, -200, 3, -300, 100, "USD", USDSGD,
            putCall="P", strike=90, expiry="20260320", multiplier=100,
            underlyingSymbol="AAA"),
    ]


# 1000*1.25 + 300 = 1550 stock ; -200*1.25 = -250 options ; + 478.5 cash
SARAH_NLV, SARAH_CASH, SARAH_STOCK, SARAH_OPTIONS = 1778.5, 478.5, 1550, -250
SARAH_UPL_SGD = 200 * USDSGD + 20 + 100 * USDSGD          # 395.0
FX_BY_SYMBOL = {"AAA": USDSGD, "BBB": 1.0}


def _sarah_stmt(**kw):
    kw.setdefault("positions", _sarah_positions())
    return _stmt(SARAH_ACCOUNT, base="SGD", total=SARAH_NLV, cash=SARAH_CASH,
                 stock=SARAH_STOCK, options=SARAH_OPTIONS, **kw)


def _caspar_stmt():
    return _stmt(CASPAR_ACCOUNT, base="USD", total=5123, cash=623, stock=4500,
                 positions=[_op(CASPAR_ACCOUNT, "STK", "CCC", 45, 100, 4500, 90, 4050,
                                450, "USD", 1)])


def _no_fetch(*_a, **_k):
    raise AssertionError("fetch must not be called")


# ── units: the risky part ────────────────────────────────────────────────────

class TestSarahUnits:
    def _block(self):
        return _sarah_from_report(_report(_sarah_stmt()), {}, unlabelled=True)

    def test_usd_position_in_sgd_account_stays_native(self):
        rows = {r["symbol"]: r for r in self._block()["positions"]}
        aaa = rows["AAA"]
        # Native USD — NOT multiplied by the 1.25 FX rate.
        assert aaa["mkt_val"] == 1000.0 and aaa["last"] == 100.0
        assert aaa["avg_cost"] == 80.0 and aaa["upl"] == 200.0 and aaa["qty"] == 10.0
        # SGX name is already SGD.
        assert rows["BBB"]["mkt_val"] == 300.0 and rows["BBB"]["upl"] == 20.0

    def test_option_row_native_per_contract(self):
        (opt,) = self._block()["options"]
        assert opt["symbol"] == "AAA" and opt["side"] == "short_put"
        assert opt["avg_cost"] == 300.0            # per contract, native USD
        assert opt["mkt_val"] == -200.0 and opt["upl"] == 100.0
        assert opt["expiry"] == "20260320" and opt["strike"] == 90.0

    def test_summary_is_sgd(self):
        s = self._block()["summary"]
        assert s["net_liquidation_sgd"] == SARAH_NLV
        assert s["total_cash_sgd"] == SARAH_CASH
        assert s["total_market_value_mixed"] == SARAH_STOCK
        # Sheet column upl_sgd: native upl x fxRateToBase, summed (SGD).
        assert s["unrealized_pnl_mixed"] == SARAH_UPL_SGD

    def test_weight_pct_is_fx_adjusted(self):
        rows = {r["symbol"]: r for r in self._block()["positions"]}
        assert rows["AAA"]["weight_pct"] == round(1000 * USDSGD / SARAH_NLV * 100, 2)
        assert rows["BBB"]["weight_pct"] == round(300 / SARAH_NLV * 100, 2)

    def test_nothing_shifts_by_the_fx_rate(self):
        """Native rows x fx + cash must reproduce NLV: the same arithmetic the
        PWA (toAcctCcy) and yahoo_grab perform on what we write."""
        b = self._block()
        total = sum(r["mkt_val"] * FX_BY_SYMBOL[r["symbol"]]
                    for r in b["positions"] + b["options"]) + b["summary"]["total_cash_sgd"]
        assert total == pytest.approx(b["summary"]["net_liquidation_sgd"])

    def test_downstream_sheet_rows(self):
        """Through the real sync.py row builders."""
        grab = build_flex_grab({"account": CASPAR_ACCOUNT, "nlv": 5123.0},
                               [], {}, sarah=self._block())
        snap = snapshot_sarah_from_grab(grab)
        assert (snap.net_liq_sgd, snap.cash_sgd, snap.upl_sgd) == (SARAH_NLV, SARAH_CASH, SARAH_UPL_SGD)
        pos = {p.ticker: p for p in positions_sarah_from_grab(grab)}
        assert pos["AAA"].mkt_val == 1000.0 and pos["AAA"].avg_cost == 80.0
        assert pos["AAA"].last == 100.0 and pos["BBB"].mkt_val == 300.0

    def test_margin_fields_carried_not_zeroed(self):
        prev = {"buying_power_sgd": 11.0, "excess_liquidity_sgd": 22.0}
        s = _sarah_from_report(_report(_sarah_stmt()), prev, unlabelled=True)["summary"]
        assert (s["buying_power_sgd"], s["excess_liquidity_sgd"]) == (11.0, 22.0)

    def test_base_currency_position_needs_no_fx_attribute(self):
        pos = [_op(SARAH_ACCOUNT, "STK", "BBB", 100, 3, 300, 2.8, 280, 20, "SGD", None)]
        stmt = _stmt(SARAH_ACCOUNT, base="SGD", total=500, cash=200, stock=300, positions=pos)
        b = _sarah_from_report(_report(stmt), {}, unlabelled=True)
        assert b["summary"]["unrealized_pnl_mixed"] == 20.0


# ── how she shows up ─────────────────────────────────────────────────────────

class TestSecondReport:
    def test_fresh_from_a_second_report(self):
        calls = []

        def fetch(token, qid):
            calls.append((token, qid))
            return _report(_sarah_stmt())

        block, status = resolve_sarah(_report(_caspar_stmt()), {}, CREDS, fetch)
        assert calls == [(TOKEN, QID)]
        assert block["summary"]["net_liquidation_sgd"] == SARAH_NLV
        assert "second report" in status and "fresh" in status
        assert TOKEN not in status and QID not in status

    def test_second_report_without_account_labels_is_hers(self):
        stmt = _sarah_stmt(stmt_acct=False, eq_acct=False, info=True,
                           positions=[p.replace(f'accountId="{SARAH_ACCOUNT}" ', "")
                                      for p in _sarah_positions()])
        # AccountInformation still labelled; strip it entirely for a bare report.
        stmt = stmt.replace(f'<AccountInformation accountId="{SARAH_ACCOUNT}" currency="SGD"/>',
                            '<AccountInformation currency="SGD"/>')
        block, status = resolve_sarah(_report(_caspar_stmt()), {}, CREDS,
                                      lambda t, q: _report(stmt))
        assert block is not None and "second report" in status

    def test_second_report_for_the_wrong_login_is_rejected(self):
        """Token pointed at Caspar's login by mistake -> nothing for her."""
        block, status = resolve_sarah(_report(_caspar_stmt()), {}, CREDS,
                                      lambda t, q: _report(_caspar_stmt()))
        assert block is None and "carried forward" in status


class TestLinkedAccounts:
    def test_one_report_covering_both_accounts(self):
        report = _report(_caspar_stmt(), _sarah_stmt())      # hers is LAST in the document
        block, status = resolve_sarah(report, {}, {}, _no_fetch)   # no second token needed
        assert block["summary"]["net_liquidation_sgd"] == SARAH_NLV
        assert "split from the main report" in status

        # Caspar must be unaffected by her rows: his NLV, not hers (the old
        # "last equity row in the document" logic would have picked hers).
        account = parse_account(report, CASPAR_ACCOUNT)
        assert account["nlv"] == 5123 and account["currency"] == "USD"
        assert parse_account(report)["nlv"] == 5123          # None -> first account named
        grab = build_flex_grab(account, parse_open_positions(report), {}, sarah=block)
        c = grab["accounts"]["caspar"]
        assert [p["symbol"] for p in c["positions"]] == ["CCC"] and c["options"] == []
        assert c["summary"]["net_liquidation"] == 5123.0
        assert grab["accounts"]["sarah"]["summary"]["net_liquidation_sgd"] == SARAH_NLV

    def test_rows_of_both_accounts_mixed_in_one_statement(self):
        """Defensive: no per-account FlexStatement, only row-level accountId."""
        eq = lambda acct, base, total, cash, stock: (   # noqa: E731
            f"<EquitySummaryByReportDateInBase {_attrs(dict(accountId=acct, currency=base, reportDate='20260101', cash=cash, stock=stock, options=0, total=total))}/>")
        body = (f'<AccountInformation accountId="{CASPAR_ACCOUNT}" currency="USD"/>'
                f'<AccountInformation accountId="{SARAH_ACCOUNT}" currency="SGD"/>'
                f"<EquitySummaryInBase>{eq(CASPAR_ACCOUNT, 'USD', 5123, 623, 4500)}"
                f"{eq(SARAH_ACCOUNT, 'SGD', 1550 + 478.5, 478.5, 1550)}</EquitySummaryInBase>"
                "<OpenPositions>"
                + _op(CASPAR_ACCOUNT, "STK", "CCC", 45, 100, 4500, 90, 4050, 450, "USD", 1)
                + "".join(_sarah_positions()[:2]) + "</OpenPositions>")
        report = f'<FlexQueryResponse><FlexStatements count="1"><FlexStatement>{body}</FlexStatement></FlexStatements></FlexQueryResponse>'
        block, _ = resolve_sarah(report, {}, {}, _no_fetch)
        assert block["summary"]["net_liquidation_sgd"] == 2028.5
        assert {r["symbol"] for r in block["positions"]} == {"AAA", "BBB"}
        assert parse_account(report, CASPAR_ACCOUNT)["nlv"] == 5123
        assert [p["symbol"] for p in parse_open_positions(report) if p["account"] == CASPAR_ACCOUNT] == ["CCC"]

    def test_unlabelled_rows_in_a_linked_report_stay_with_caspar(self):
        bare = _stmt(CASPAR_ACCOUNT, base="USD", total=5123, cash=623, stock=4500,
                     stmt_acct=False, eq_acct=False, info=False,
                     positions=[_op(None, "STK", "CCC", 45, 100, 4500, 90, 4050, 450, "USD", 1)])
        block, status = resolve_sarah(_report(bare, _sarah_stmt()), {}, {}, _no_fetch)
        assert block["summary"]["net_liquidation_sgd"] == SARAH_NLV      # not 5123
        assert {r["symbol"] for r in block["positions"]} == {"AAA", "BBB"}


# ── never clobber, never fail his sync ───────────────────────────────────────

PREV_SARAH = {"account_id": SARAH_ACCOUNT, "base_currency": "SGD",
              "summary": {"net_liquidation_sgd": 7777.0},
              "positions": [{"symbol": "OLD", "sec_type": "STK", "qty": 1.0}],
              "options": [], "trades": []}


def _write_prev(tmp_path):
    d = tmp_path / "PortfolioGrabs"
    d.mkdir()
    prev = {"accounts": {"sarah": PREV_SARAH,
                         "caspar": {"summary": {"buying_power": 1.0, "excess_liquidity": 2.0}}}}
    (d / "20200101_PortfolioGrab.json").write_text(json.dumps(prev))
    return d


def _runner(rc):
    calls = []

    def run(cmd, cwd=None):
        calls.append(cmd)
        return SimpleNamespace(returncode=rc)

    run.calls = calls
    return run


def _saved(tmp_path):
    files = sorted((tmp_path / "PortfolioGrabs").glob("2*_PortfolioGrab.json"))
    return json.loads(files[-1].read_text())


class TestFailureIsolation:
    @pytest.mark.parametrize("rc", [0, 1])
    def test_her_fetch_failing_does_not_touch_his_result(self, tmp_path, capsys, rc):
        _write_prev(tmp_path)

        def fetch(token, qid):
            raise RuntimeError(f"SendRequest failed: Fail 1012 token {token} query {qid}")

        runner = _runner(rc)
        got = run_sync(_report(_caspar_stmt()), str(tmp_path), CREDS, fetch=fetch, runner=runner)
        assert got == rc                                  # exit code is HIS sync's
        assert len(runner.calls) == 1                     # his sync still ran
        grab = _saved(tmp_path)
        assert grab["accounts"]["sarah"] == PREV_SARAH    # carried forward verbatim
        assert grab["accounts"]["caspar"]["summary"]["net_liquidation"] == 5123.0
        out = capsys.readouterr().out
        assert "sarah: carried forward" in out and "second report unusable" in out
        assert TOKEN not in out and QID not in out        # redacted

    def test_requests_errors_never_echo_the_token_url(self, tmp_path, capsys):
        _write_prev(tmp_path)

        def fetch(token, qid):
            raise requests.HTTPError(f"403 Client Error: Forbidden for url: "
                                     f"https://example.invalid/x?t={token}&q={qid}&v=3")

        run_sync(_report(_caspar_stmt()), str(tmp_path), CREDS, fetch=fetch, runner=_runner(0))
        out = capsys.readouterr().out
        assert TOKEN not in out and QID not in out and "example.invalid" not in out
        assert "HTTPError" in out

    def test_unexpected_crash_in_resolution_is_contained(self, tmp_path, capsys, monkeypatch):
        import scripts.ibkr_flex_sync as m
        _write_prev(tmp_path)
        monkeypatch.setattr(m, "resolve_sarah", lambda *a, **k: 1 / 0)
        runner = _runner(0)
        assert run_sync(_report(_caspar_stmt()), str(tmp_path), CREDS, runner=runner) == 0
        assert _saved(tmp_path)["accounts"]["sarah"] == PREV_SARAH
        assert "ZeroDivisionError" in capsys.readouterr().out

    def test_fresh_sarah_is_written_and_no_values_are_logged(self, tmp_path, capsys):
        _write_prev(tmp_path)
        runner = _runner(0)
        rc = run_sync(_report(_caspar_stmt()), str(tmp_path), CREDS,
                      fetch=lambda t, q: _report(_sarah_stmt()), runner=runner)
        assert rc == 0
        grab = _saved(tmp_path)
        assert grab["accounts"]["sarah"]["summary"]["net_liquidation_sgd"] == SARAH_NLV
        assert grab["accounts"]["sarah"]["positions"] != PREV_SARAH["positions"]
        out = capsys.readouterr().out
        assert "sarah: fresh from Flex (second report)" in out
        # CI logs are public: no balances / share counts.
        for needle in ("1778", "478", "5123", "623", "4500"):
            assert needle not in out

    @pytest.mark.parametrize("why, stmt", [
        ("no rows at all",
         _stmt(SARAH_ACCOUNT, base="SGD", total=None, cash=None, stock=None,
               info=False, equity=False, positions=[])),
        ("positions but no equity summary",
         _stmt(SARAH_ACCOUNT, base="SGD", total=0, cash=0, stock=0, equity=False,
               positions=_sarah_positions())),
        ("equity summary lacks cash",
         _stmt(SARAH_ACCOUNT, base="SGD", total=SARAH_NLV, cash=None, stock=SARAH_STOCK,
               positions=_sarah_positions())),
        ("zero NLV",
         _stmt(SARAH_ACCOUNT, base="SGD", total=0, cash=0, stock=0, positions=[])),
        ("wrong base currency",
         _stmt(SARAH_ACCOUNT, base="USD", total=SARAH_NLV, cash=SARAH_CASH, stock=SARAH_STOCK,
               positions=_sarah_positions())),
        ("base currency absent",
         _stmt(SARAH_ACCOUNT, base=None, total=SARAH_NLV, cash=SARAH_CASH, stock=SARAH_STOCK,
               positions=_sarah_positions())),
        ("USD position without fxRateToBase",
         _stmt(SARAH_ACCOUNT, base="SGD", total=SARAH_NLV, cash=SARAH_CASH, stock=SARAH_STOCK,
               positions=[_op(SARAH_ACCOUNT, "STK", "AAA", 10, 100, 1000, 80, 800, 200, "USD", None)])),
        ("equity summary shows stock but no positions came back",
         _stmt(SARAH_ACCOUNT, base="SGD", total=SARAH_NLV, cash=SARAH_CASH, stock=SARAH_STOCK,
               positions=[])),
    ])
    def test_incomplete_data_carries_her_forward(self, why, stmt, tmp_path, capsys):
        _write_prev(tmp_path)
        runner = _runner(0)
        rc = run_sync(_report(_caspar_stmt()), str(tmp_path), CREDS,
                      fetch=lambda t, q: _report(stmt), runner=runner)
        assert rc == 0, why
        assert _saved(tmp_path)["accounts"]["sarah"] == PREV_SARAH, why
        assert "sarah: carried forward" in capsys.readouterr().out, why

    def test_incomplete_block_raises_a_reasoned_error(self):
        with pytest.raises(SarahDataError, match="equity summary"):
            _sarah_from_report(_report(_stmt(SARAH_ACCOUNT, base="SGD", total=0, cash=0,
                                             stock=0, equity=False,
                                             positions=_sarah_positions())),
                               {}, unlabelled=True)


class TestInertWithoutCredentials:
    def test_no_credentials_is_unchanged_behaviour(self, tmp_path, capsys):
        _write_prev(tmp_path)
        runner = _runner(0)
        rc = run_sync(_report(_caspar_stmt()), str(tmp_path), {}, fetch=_no_fetch, runner=runner)
        assert rc == 0
        assert _saved(tmp_path)["accounts"]["sarah"] == PREV_SARAH
        assert "carried forward (no Sarah credentials set" in capsys.readouterr().out

    def test_no_credentials_and_no_prior_grab_is_the_empty_default(self, tmp_path):
        runner = _runner(0)
        run_sync(_report(_caspar_stmt()), str(tmp_path), {}, fetch=_no_fetch, runner=runner)
        sarah = _saved(tmp_path)["accounts"]["sarah"]
        # The shape sync.py's per-account gate skips (net_liq 0, no rows) — her
        # Sheet rows are left untouched, exactly as on CI today.
        assert sarah == {"account_id": SARAH_ACCOUNT, "base_currency": "SGD",
                         "summary": {}, "positions": [], "options": [], "trades": []}
        assert snapshot_sarah_from_grab(_saved(tmp_path)).net_liq_sgd == 0
        assert positions_sarah_from_grab(_saved(tmp_path)) == []

    @pytest.mark.parametrize("env, missing", [
        ({"IB_FLEX_TOKEN_SARAH": TOKEN}, "IB_FLEX_QUERY_ID_SARAH"),
        ({"IB_FLEX_QUERY_ID_SARAH": QID}, "IB_FLEX_TOKEN_SARAH"),
        ({"IB_FLEX_TOKEN_SARAH": "  ", "IB_FLEX_QUERY_ID_SARAH": ""}, None),
    ])
    def test_partial_credentials_do_not_fetch(self, env, missing):
        block, status = resolve_sarah(_report(_caspar_stmt()), {}, env, _no_fetch)
        assert block is None and status.startswith("sarah: carried forward")
        if missing:
            assert missing in status
        assert TOKEN not in status and QID not in status

    def test_caspar_only_report_with_her_secrets_unset_matches_old_output_shape(self):
        """Caspar's block is byte-for-byte what it was: the new parse fields
        must not leak into his rows."""
        report = _report(_caspar_stmt())
        grab = build_flex_grab(parse_account(report, CASPAR_ACCOUNT), parse_open_positions(report), {})
        (row,) = grab["accounts"]["caspar"]["positions"]
        assert set(row) == {"symbol", "sec_type", "exchange", "qty", "avg_cost", "last",
                            "mkt_val", "upl", "weight_pct"}
        assert row["weight_pct"] == round(4500 / 5123 * 100, 2)


# ── parser hardening ─────────────────────────────────────────────────────────

class TestParsers:
    def test_lot_rows_are_dropped_when_summary_rows_exist(self):
        pos = [_op(SARAH_ACCOUNT, "STK", "AAA", 10, 100, 1000, 80, 800, 200, "USD", USDSGD),
               _op(SARAH_ACCOUNT, "STK", "AAA", 4, 100, 400, 80, 320, 80, "USD", USDSGD,
                   levelOfDetail="LOT"),
               _op(SARAH_ACCOUNT, "STK", "AAA", 6, 100, 600, 80, 480, 120, "USD", USDSGD,
                   levelOfDetail="LOT")]
        rows = parse_open_positions(_report(_stmt(SARAH_ACCOUNT, base="SGD", total=1, cash=1,
                                                  stock=1, positions=pos)))
        assert [(r["level"], r["qty"]) for r in rows] == [("SUMMARY", 10.0)]

    def test_lot_only_reports_are_left_alone(self):
        pos = [_op(SARAH_ACCOUNT, "STK", "AAA", 4, 100, 400, 80, 320, 80, "USD", USDSGD,
                   levelOfDetail="LOT")]
        rows = parse_open_positions(_report(_stmt(SARAH_ACCOUNT, base="SGD", total=1, cash=1,
                                                  stock=1, positions=pos)))
        assert len(rows) == 1

    def test_latest_equity_row_wins_by_report_date(self):
        def eq(date, total):
            return f'<EquitySummaryByReportDateInBase accountId="{CASPAR_ACCOUNT}" currency="USD" reportDate="{date}" cash="1" stock="1" total="{total}"/>'
        xml = (f'<FlexQueryResponse><FlexStatements count="1"><FlexStatement accountId="{CASPAR_ACCOUNT}">'
               f"<EquitySummaryInBase>{eq('20260102', 222)}{eq('20260101', 111)}</EquitySummaryInBase>"
               "</FlexStatement></FlexStatements></FlexQueryResponse>")
        assert parse_account(xml, CASPAR_ACCOUNT)["nlv"] == 222

    def test_native_currency_and_fx_are_exposed(self):
        rows = parse_open_positions(_report(_sarah_stmt()))
        by = {r["symbol"]: r for r in rows}
        assert by["AAA"]["currency"] == "USD" and by["AAA"]["fx_to_base"] == USDSGD
        assert by["BBB"]["currency"] == "SGD" and by["BBB"]["fx_to_base"] == 1.0


def test_a_position_with_no_cost_basis_books_no_profit():
    from scripts.ibkr_flex_sync import _flex_stock_row
    row = _flex_stock_row({"symbol": "XXX", "qty": 10.0, "mark": 50.0, "value": 500.0,
                           "cost_price": 0.0, "cost_money": 0.0, "upl": 0.0}, 1000.0)
    assert (row["avg_cost"], row["upl"]) == (0.0, 0.0)


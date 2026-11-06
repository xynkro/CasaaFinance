"""Privacy routing for Telegram sends.

The Finance supergroup has other members, so any message bound for a PERSONAL
topic (Multi-Day-Swing, Options-Intel) — which discloses balances, holdings,
P&L, plan sizing, or account-tailored ideas — must be redirected to the owner's
DM. Impersonal lanes (Macro News, Insider Trading) stay in the group.
"""
from __future__ import annotations

import pytest

import src.telegram as tg


@pytest.fixture
def captured(monkeypatch):
    """Capture the payload send() would POST, without hitting the network."""
    box: dict = {}

    class FakeResp:
        ok = True
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True, "result": {}}

    def fake_post(url, json=None, timeout=None):
        box["payload"] = json
        return FakeResp()

    monkeypatch.setattr(tg.requests, "post", fake_post)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    return box


def test_personal_topic_redirects_to_dm(captured):
    tg.send("holdings + pnl", message_thread_id=tg.OPTIONS_INTEL_TOPIC)
    assert captured["payload"]["chat_id"] == tg.PERSONAL_CHAT_ID
    assert "message_thread_id" not in captured["payload"]


def test_multi_day_swing_also_redirects_to_dm(captured):
    tg.send("cash floor breached", message_thread_id=tg.MULTI_DAY_SWING_TOPIC)
    assert captured["payload"]["chat_id"] == tg.PERSONAL_CHAT_ID
    assert "message_thread_id" not in captured["payload"]


def test_impersonal_topic_stays_in_group(captured):
    tg.send("CPI cooler than expected", message_thread_id=tg.MACRO_NEWS_TOPIC)
    assert captured["payload"]["chat_id"] == tg.FINANCE_CHAT_ID
    assert captured["payload"]["message_thread_id"] == tg.MACRO_NEWS_TOPIC


def test_macro_news_in_the_group_carries_no_account_data(captured):
    tg.ping_macro_news("Meta outlook cut", source="CNBC", url="https://x.test",
                       context="exposure CASH_PRIORITY · GEX NEGATIVE_TREND")
    payload = captured["payload"]
    assert payload["chat_id"] == tg.FINANCE_CHAT_ID
    assert "exposure" not in payload["text"] and "CASH_PRIORITY" not in payload["text"]
    assert "GEX NEGATIVE_TREND" in payload["text"]


def test_macro_news_drops_the_line_when_context_is_account_only(captured):
    tg.ping_macro_news("Meta outlook cut", source="CNBC", context="exposure REDUCE_ONLY")
    assert "📍" not in captured["payload"]["text"]


def test_macro_news_cannot_name_held_tickers(captured):
    with pytest.raises(TypeError):
        tg.ping_macro_news("Meta outlook cut", held=["META"])


def test_explicit_chat_id_is_never_overridden(captured):
    tg.send("ad-hoc", chat_id="555", message_thread_id=tg.OPTIONS_INTEL_TOPIC)
    assert captured["payload"]["chat_id"] == "555"


def test_daily_ideas_dm_goes_to_dm(captured):
    tg.ping_daily_ideas("📈 <b>Ideas</b>\nSize: Sarah 4 sh · Caspar 1 sh")
    assert captured["payload"]["chat_id"] == tg.PERSONAL_CHAT_ID
    assert captured["payload"]["parse_mode"] == "HTML"
    assert "message_thread_id" not in captured["payload"]


def test_daily_ideas_dm_fails_closed(captured, monkeypatch):
    monkeypatch.setattr(tg, "PERSONAL_CHAT_ID", tg.FINANCE_CHAT_ID)
    with pytest.raises(tg.PrivacyRoutingError):
        tg.ping_daily_ideas("cash $90")
    assert "payload" not in captured


# ── 2026-10-30 leak: empty TELEGRAM_CHAT_ID in CI fell through to the group ──
import importlib


def _reload_with(monkeypatch, **env):
    for k in ("TELEGRAM_PERSONAL_CHAT_ID", "TELEGRAM_USER_CASPAR", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return importlib.reload(tg)


@pytest.fixture
def reload_tg(monkeypatch):
    yield lambda **env: _reload_with(monkeypatch, **env)
    for k in ("TELEGRAM_PERSONAL_CHAT_ID", "TELEGRAM_USER_CASPAR", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(k, raising=False)
    importlib.reload(tg)


def _capture(monkeypatch, mod):
    box = {}

    class R:
        ok = True; status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"ok": True, "result": {}}

    monkeypatch.setattr(mod.requests, "post", lambda url, json=None, timeout=None: (box.update(payload=json), R())[1])
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    return box


def test_regression_ci_empty_chat_id_still_reaches_the_dm(monkeypatch, reload_tg):
    """The exact CI shape: the secret doesn't exist, so the var is ''."""
    mod = reload_tg(TELEGRAM_CHAT_ID="")
    box = _capture(monkeypatch, mod)
    mod.send("🪫 CASH FLOOR: caspar cash $80", message_thread_id=mod.MULTI_DAY_SWING_TOPIC)
    assert box["payload"]["chat_id"] == "922547929"
    assert box["payload"]["chat_id"] != mod.FINANCE_CHAT_ID
    assert "message_thread_id" not in box["payload"]


def test_group_id_is_never_accepted_as_personal(monkeypatch, reload_tg):
    mod = reload_tg(TELEGRAM_CHAT_ID="-1003942004211")
    assert mod.PERSONAL_CHAT_ID == "922547929"


def test_dedicated_personal_var_wins(monkeypatch, reload_tg):
    mod = reload_tg(TELEGRAM_PERSONAL_CHAT_ID="111", TELEGRAM_CHAT_ID="222")
    assert mod.PERSONAL_CHAT_ID == "111"


def test_send_fails_closed_if_personal_ever_points_at_a_group(monkeypatch, reload_tg):
    mod = reload_tg()
    box = _capture(monkeypatch, mod)
    monkeypatch.setattr(mod, "PERSONAL_CHAT_ID", mod.FINANCE_CHAT_ID)
    with pytest.raises(mod.PrivacyRoutingError):
        mod.send("holdings", message_thread_id=mod.OPTIONS_INTEL_TOPIC)
    assert "payload" not in box          # nothing was posted


def test_explicit_dm_sends_from_scripts_use_the_resolved_id(monkeypatch, reload_tg):
    """policy_audit / dupe_guard / crash_playbook pass chat_id=tg.PERSONAL_CHAT_ID."""
    mod = reload_tg(TELEGRAM_CHAT_ID="")
    box = _capture(monkeypatch, mod)
    mod.send("audit report", chat_id=mod.PERSONAL_CHAT_ID)
    assert box["payload"]["chat_id"] == "922547929"

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


def test_explicit_chat_id_is_never_overridden(captured):
    tg.send("ad-hoc", chat_id="555", message_thread_id=tg.OPTIONS_INTEL_TOPIC)
    assert captured["payload"]["chat_id"] == "555"


def test_cash_floor_ping_goes_to_dm(captured):
    # End-to-end through the real ping: the literal "how low am I" message.
    tg.ping_cash_floor(account="caspar", cash=487.0, nlv=27000.0, floor=540.0)
    assert captured["payload"]["chat_id"] == tg.PERSONAL_CHAT_ID
    assert "message_thread_id" not in captured["payload"]

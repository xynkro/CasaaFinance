"""Tests for the inert email→news pipeline (Bloomberg briefings + MF rec nudge).

No live Gmail, no network. Every Gmail call is monkeypatched. The headline
safety property — `fetch_email_news()` returns `[]` with no creds — is asserted
explicitly so the committed code provably changes nothing until Caspar adds the
GMAIL_* token.
"""
from __future__ import annotations

import src.gmail_client as gmail_client
import src.news_aggregator as na


# ── A captured Bloomberg "Five Things" style briefing ────────────────────────
# Leading "View in browser" line + the zero-width-non-joiner spacer runs that
# Bloomberg's HTML→text emails embed, then a real lede. fetch_email_news must
# strip the boilerplate and keep the lede in the summary.
_BLOOMBERG_SUBJECT = "AI stocks lose favor"
_BLOOMBERG_PLAINTEXT = (
    "View in browser\n"
    "‌ ‌ ‌ ‌ ‌ ‌ ‌ ‌ ‌ ‌\n"
    "Investors pulled back from the priciest corners of the AI trade on "
    "Thursday as Treasury yields climbed and a soft auction rattled the "
    "long end. Here's what you need to know to start your day."
)


def _bloomberg_message(msg_id: str) -> dict:
    return {
        "id": msg_id,
        "subject": _BLOOMBERG_SUBJECT,
        "sender": "Bloomberg <noreply@news.bloomberg.com>",
        "date": "Thu, 05 Jun 2026 11:30:00 +0000",
        "plaintext": _BLOOMBERG_PLAINTEXT,
    }


def test_fetch_email_news_parses_bloomberg_briefing(monkeypatch):
    """One email → one normalised news item with boilerplate stripped."""
    # Pretend the env is configured so we get past the inert guard.
    monkeypatch.setenv("GMAIL_CLIENT_ID", "x")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "x")
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN", "x")

    monkeypatch.setattr(gmail_client, "search", lambda *a, **k: ["m1"])
    monkeypatch.setattr(gmail_client, "get_message", lambda mid: _bloomberg_message(mid))

    items = na.fetch_email_news()
    assert len(items) == 1
    item = items[0]

    # Shape — same keys as every other news item in the pipeline.
    assert set(item) >= {"id", "datetime", "headline", "summary",
                         "source", "url", "category"}
    assert item["headline"] == "AI stocks lose favor"
    assert item["source"] == "Bloomberg Email"
    assert item["category"] == "bloomberg-email"
    assert item["url"] == ""
    assert item["id"] == na._stable_id("m1", _BLOOMBERG_SUBJECT)
    # Date header parsed via the shared RSS parser → ISO-8601 UTC.
    assert item["datetime"].startswith("2026-06-05T11:30:00")

    # Boilerplate stripped: no "View in browser", no zero-width spacers; the
    # real lede survives.
    summary = item["summary"]
    assert "View in browser" not in summary
    assert "‌" not in summary
    assert summary.startswith("Investors pulled back")


def test_fetch_email_news_skips_empty_subject(monkeypatch):
    monkeypatch.setenv("GMAIL_CLIENT_ID", "x")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "x")
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN", "x")
    monkeypatch.setattr(gmail_client, "search", lambda *a, **k: ["m1"])
    monkeypatch.setattr(
        gmail_client, "get_message",
        lambda mid: {"id": mid, "subject": "", "sender": "x",
                     "date": "Thu, 05 Jun 2026 11:30:00 +0000", "plaintext": "body"},
    )
    assert na.fetch_email_news() == []


# ── MF new-recommendation matcher (pure) ─────────────────────────────────────

def test_mf_new_rec_emails_matches_real_rec():
    msgs = [
        {"subject": "Our next recommendation is ready", "sender": "Stock Advisor <hi@fool.com>"},
    ]
    out = na.mf_new_rec_emails(msgs)
    assert len(out) == 1
    assert out[0]["subject"].startswith("Our next recommendation")


def test_mf_new_rec_emails_rejects_marketing():
    msgs = [
        {"subject": "[Urgent] Your Epic order status", "sender": "The Motley Fool <hi@fool.com>"},
        {"subject": "Create New Password", "sender": "fool.com"},
        {"subject": "50% off Stock Advisor — new recommendation inside", "sender": "hi@fool.com"},
        {"subject": "New recommendation just dropped", "sender": "Some Other Newsletter <hi@example.com>"},
    ]
    # Epic/order → marketing word; password → marketing word; "% off" → marketing
    # word; non-fool sender → not MF. None should match.
    assert na.mf_new_rec_emails(msgs) == []


def test_mf_new_rec_emails_matches_various_patterns():
    msgs = [
        {"subject": "New buy alert: a high-conviction name", "sender": "hi@fool.com"},
        {"subject": "Your new Stock Advisor pick", "sender": "hi@fool.com"},
        {"subject": "New buy for your portfolio", "sender": "hi@fool.com"},
    ]
    assert len(na.mf_new_rec_emails(msgs)) == 3


# ── Inert safety property: no creds → no work, no network ────────────────────

def test_gmail_client_inert_without_creds(monkeypatch):
    """search() returns [] with the three GMAIL_* vars unset — no network."""
    for k in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    assert gmail_client._access_token() is None
    assert gmail_client.search("from:news.bloomberg.com newer_than:1d") == []


def test_fetch_email_news_inert_without_creds(monkeypatch):
    """fetch_email_news() returns [] with no creds — the headline guarantee."""
    for k in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    assert na.fetch_email_news() == []


# ── Telegram: new "refresh" kind on ping_curated_pick ────────────────────────

def test_ping_curated_pick_refresh_kind(monkeypatch):
    """The new 'refresh' kind renders the 🔔 refresh-in-session nudge; existing
    kinds are unchanged."""
    import src.telegram as tg

    captured: dict = {}

    def _fake_send(text, **kwargs):
        captured["text"] = text
        captured["kwargs"] = kwargs
        return {"ok": True}

    monkeypatch.setattr(tg, "send", _fake_send)

    tg.ping_curated_pick("refresh", "MF")
    assert "🔔" in captured["text"]
    assert "New MF rec emailed — refresh in-session" in captured["text"]

    # Existing kind still works (regression guard).
    captured.clear()
    tg.ping_curated_pick("new_rec", "NVDA")
    assert "🧠" in captured["text"]
    assert "New Motley Fool rec" in captured["text"]

# tests/test_curated_alerts.py
from scripts.ingest_curated_picks import curated_alerts

PREV = [{"ticker":"GLW","role":"reference"},{"ticker":"GLW","role":"watchlist"}]
NEW  = [{"ticker":"GLW","role":"reference"},{"ticker":"GLW","role":"watchlist"},
        {"ticker":"FPS","role":"watchlist"},{"ticker":"FPS","role":"reference"},
        {"ticker":"GLW","role":"overlay"}]

def test_new_rec_and_overlay_detected():
    al = {(a["kind"], a["ticker"]) for a in curated_alerts(PREV, NEW)}
    assert ("new_rec","FPS") in al        # FPS newly appears
    assert ("overlay","GLW") in al        # GLW newly overlay-eligible
    assert ("new_rec","GLW") not in al    # GLW already known

def test_no_alerts_when_unchanged():
    assert curated_alerts(NEW, NEW) == []

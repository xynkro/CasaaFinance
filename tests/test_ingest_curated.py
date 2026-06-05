# tests/test_ingest_curated.py
from scripts.ingest_curated_picks import classify_picks

DATA = {
  "as_of": "2026-06-05",
  "foundational": ["AMZN"],
  "new_recs": ["FPS"],
  "rankings": ["GLW"],
  "scorecard": [
    {"ticker":"FPS","price":64.04,"rec_date":"2026-06-05","type":"","market_cap":"19.66B",
     "adj_rec_price":64.59,"return_since_rec":None,"return_vs_sp":None},
    {"ticker":"GLW","price":197.70,"rec_date":"2026-05-22","type":"Cautious","market_cap":"170.15B",
     "adj_rec_price":191.60,"return_since_rec":3.19,"return_vs_sp":1.27},
    {"ticker":"AMZN","price":254.02,"rec_date":"2026-03-20","type":"Cautious","market_cap":"2.73T",
     "adj_rec_price":208.76,"return_since_rec":21.57,"return_vs_sp":6.51},
  ],
}

def _roles(rows, tk):
    return {r.role for r in rows if r.ticker == tk}

def test_every_scorecard_name_is_reference():
    rows = classify_picks(DATA, today="2026-06-05")
    assert "reference" in _roles(rows, "GLW")
    assert "reference" in _roles(rows, "AMZN")

def test_foundational_is_core():
    rows = classify_picks(DATA, today="2026-06-05")
    assert "core" in _roles(rows, "AMZN")
    assert "core" not in _roles(rows, "GLW")

def test_new_rec_and_ranking_are_watchlist():
    rows = classify_picks(DATA, today="2026-06-05")
    assert "watchlist" in _roles(rows, "FPS")
    assert "watchlist" in _roles(rows, "GLW")

def test_overlay_only_recent_and_near_rec_price():
    rows = classify_picks(DATA, today="2026-06-05")
    # FPS: rec 0 days ago, price 64.04 vs adj 64.59 (~0.9%) → overlay
    assert "overlay" in _roles(rows, "FPS")
    # AMZN: rec 77 days ago → too old for overlay
    assert "overlay" not in _roles(rows, "AMZN")

def test_source_tag():
    rows = classify_picks(DATA, today="2026-06-05")
    assert all(r.source == "motley_fool" for r in rows)

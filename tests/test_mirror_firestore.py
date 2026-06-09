"""Tests for scripts/mirror_to_firestore.py — the Firestore serving-mirror.

The Firestore client is fully mocked (there is no live Firebase project and no
network call is ever made). `read_tab` is a fake callable returning canned rows
per tab. These tests pin the doc contract shared with the PWA reader:
    tabs/{name} = { rows, updatedAt, rowCount, sourceHash, chunks }
plus the cap, chunk-overflow, hash-diff-skip, per-tab fail-safe, and
inert-without-key behaviours.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# scripts/ is not a package — load the module by path (matches test_daily_plan.py).
_spec = importlib.util.spec_from_file_location(
    "mirror_to_firestore", ROOT / "scripts" / "mirror_to_firestore.py")
mir = importlib.util.module_from_spec(_spec)
sys.modules["mirror_to_firestore"] = mir
_spec.loader.exec_module(mir)


# ---------- fake Firestore ----------

class FakeDocRef:
    """One document. `set()` records the payload; `get()` returns a snapshot."""

    def __init__(self, store: dict, doc_id: str):
        self._store = store
        self._id = doc_id

    def set(self, data: dict):
        self._store[self._id] = dict(data)

    def get(self):
        return FakeSnapshot(self._store.get(self._id))


class FakeSnapshot:
    def __init__(self, data):
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class FakeCollection:
    def __init__(self, store: dict):
        self._store = store

    def document(self, doc_id: str) -> FakeDocRef:
        return FakeDocRef(self._store, doc_id)


class FakeDB:
    """Mock Firestore client. All `tabs` docs live in `self.docs` (id → payload)."""

    def __init__(self, docs: dict | None = None):
        self.docs: dict[str, dict] = dict(docs or {})

    def collection(self, name: str) -> FakeCollection:
        assert name == "tabs", f"unexpected collection {name!r}"
        return FakeCollection(self.docs)


def make_read_tab(table: dict[str, list[dict]]):
    """Build a fake read_tab that returns canned rows, KeyError for unknown tabs."""
    def _read(name: str) -> list[dict]:
        if name not in table:
            raise KeyError(f"no such tab: {name}")
        return table[name]
    return _read


# ---------- pure helpers ----------

def test_cap_keeps_last_n_chronological():
    rows = [{"i": i} for i in range(10)]
    capped = mir._cap_rows(rows, 3)
    assert capped == [{"i": 7}, {"i": 8}, {"i": 9}]


def test_cap_noop_when_under_limit_or_disabled():
    rows = [{"i": i} for i in range(3)]
    assert mir._cap_rows(rows, 10) == rows          # under cap → unchanged
    assert mir._cap_rows(rows, 0) == rows           # cap<=0 → no cap
    assert mir._cap_rows([], 5) == []               # empty safe


def test_source_hash_stable_and_order_independent():
    a = [{"x": 1, "y": 2}]
    b = [{"y": 2, "x": 1}]                          # same data, key order swapped
    assert mir._source_hash(a) == mir._source_hash(b)
    assert mir._source_hash(a) != mir._source_hash([{"x": 1, "y": 3}])


def test_chunk_if_oversize_single_doc_when_small():
    rows = [{"a": 1}, {"a": 2}]
    pieces = mir._chunk_if_oversize("macro", rows)
    assert pieces == [("macro", rows)]              # one base doc, no chunks


# ---------- mirror_tabs behaviour ----------

def test_unchanged_hash_skips_write():
    rows = [{"a": 1}, {"a": 2}]
    h = mir._source_hash(rows)
    db = FakeDB({"macro": {"rows": rows, "sourceHash": h, "rowCount": 2, "chunks": 0}})
    before = json.dumps(db.docs, sort_keys=True)

    res = mir.mirror_tabs(make_read_tab({"macro": rows}), db, tabs=["macro"])

    assert res == {"macro": "unchanged"}
    assert json.dumps(db.docs, sort_keys=True) == before   # doc untouched


def test_changed_hash_writes_contract_shape():
    db = FakeDB()  # empty → no existing hash → write
    rows = [{"a": 1}, {"a": 2}, {"a": 3}]
    res = mir.mirror_tabs(make_read_tab({"macro": rows}), db, tabs=["macro"])

    assert res == {"macro": "written"}
    doc = db.docs["macro"]
    assert doc["rows"] == rows
    assert doc["rowCount"] == 3
    assert doc["chunks"] == 0
    assert doc["sourceHash"] == mir._source_hash(rows)
    assert isinstance(doc["updatedAt"], str) and doc["updatedAt"]
    # exactly the contract keys, nothing extra
    assert set(doc) == {"rows", "updatedAt", "rowCount", "sourceHash", "chunks"}


def test_cap_applied_before_write():
    db = FakeDB()
    rows = [{"i": i} for i in range(500)]
    res = mir.mirror_tabs(make_read_tab({"live_prices": rows}), db,
                          tabs=["live_prices"], cap=400)
    assert res == {"live_prices": "written"}
    doc = db.docs["live_prices"]
    assert doc["rowCount"] == 400
    assert doc["rows"][0] == {"i": 100}            # kept the last 400 (100..499)
    assert doc["rows"][-1] == {"i": 499}


def test_oversize_tab_writes_multiple_chunks(monkeypatch):
    # Shrink the ceiling so a handful of rows forces chunking, deterministically.
    monkeypatch.setattr(mir, "MAX_DOC_BYTES", 200)
    rows = [{"k": f"value-{i:03d}-padpadpadpad"} for i in range(20)]
    db = FakeDB()
    res = mir.mirror_tabs(make_read_tab({"wsr_archive": rows}), db,
                          tabs=["wsr_archive"], cap=0)

    assert res == {"wsr_archive": "written"}
    base = db.docs["wsr_archive"]
    n = base["chunks"]
    assert n >= 1, "expected the tab to be split into base + numbered chunks"
    # numbered chunk docs exist: wsr_archive__1 .. wsr_archive__n
    chunk_ids = [f"wsr_archive__{i}" for i in range(1, n + 1)]
    for cid in chunk_ids:
        assert cid in db.docs, f"missing chunk doc {cid}"
        assert mir._rows_json_size(db.docs[cid]["rows"]) <= mir.MAX_DOC_BYTES
    # base doc also under the ceiling and rowCount = total across base+chunks
    assert mir._rows_json_size(base["rows"]) <= mir.MAX_DOC_BYTES
    assert base["rowCount"] == 20
    # concatenating base + chunks in order reconstructs the (uncapped) rows
    rebuilt = list(base["rows"])
    for cid in chunk_ids:
        rebuilt.extend(db.docs[cid]["rows"])
    assert rebuilt == rows


def test_one_bad_tab_others_still_mirrored():
    db = FakeDB()
    table = {"macro": [{"a": 1}], "options": [{"b": 2}]}  # "missing" absent → raises
    res = mir.mirror_tabs(make_read_tab(table), db,
                          tabs=["macro", "missing", "options"])

    assert res["macro"] == "written"
    assert res["missing"] == "error"
    assert res["options"] == "written"
    assert "macro" in db.docs and "options" in db.docs
    assert "missing" not in db.docs                # nothing written for the bad tab


def test_bad_tab_does_not_delete_last_good_doc():
    # A tab that errors on read must keep its previously-written doc intact.
    prior = {"rows": [{"old": 1}], "sourceHash": "deadbeef", "rowCount": 1, "chunks": 0}
    db = FakeDB({"macro": dict(prior)})
    res = mir.mirror_tabs(make_read_tab({}), db, tabs=["macro"])  # read raises
    assert res == {"macro": "error"}
    assert db.docs["macro"] == prior               # untouched, not deleted


def test_missing_worksheet_is_skip_not_error():
    # A tab absent from the Sheet (gspread raises WorksheetNotFound) is benign:
    # status "missing", NOT "error" — so an optional tab that doesn't exist yet
    # (macro_lean, curated_picks) can't fail the run.
    class WorksheetNotFound(Exception):
        pass

    def read(name):
        if name == "curated_picks":
            raise WorksheetNotFound("curated_picks")
        return [{"a": 1}]

    db = FakeDB()
    res = mir.mirror_tabs(read, db, tabs=["macro", "curated_picks"])
    assert res["macro"] == "written"
    assert res["curated_picks"] == "missing"
    assert "curated_picks" not in db.docs


# ---------- exit codes (main) ----------

def test_main_inert_without_key_exits_zero(monkeypatch, caplog):
    monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_JSON", raising=False)
    # _db() must return None on the inert path and main() exit 0 with no DB use.
    monkeypatch.setattr(mir, "_load_env", lambda: None)
    with caplog.at_level("INFO"):
        assert mir._db() is None
        assert mir.main([]) == 0
    assert any("inert" in r.message.lower() for r in caplog.records)


def test_main_all_ok_exit_zero(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(mir, "_load_env", lambda: None)
    monkeypatch.setattr(mir, "_db", lambda: db)
    monkeypatch.setattr(mir, "_default_read_tab", lambda name: [{"a": 1}])
    monkeypatch.setattr(mir, "PWA_TABS", ["macro", "options"])
    assert mir.main([]) == 0


def test_main_partial_failure_exit_one(monkeypatch):
    db = FakeDB()

    def flaky(name):
        if name == "broken":
            raise RuntimeError("boom")
        return [{"a": 1}]

    monkeypatch.setattr(mir, "_load_env", lambda: None)
    monkeypatch.setattr(mir, "_db", lambda: db)
    monkeypatch.setattr(mir, "_default_read_tab", flaky)
    monkeypatch.setattr(mir, "PWA_TABS", ["macro", "broken"])
    assert mir.main([]) == 1
    assert "macro" in db.docs and "broken" not in db.docs


def test_main_missing_tabs_exit_zero(monkeypatch):
    # 1 written + 1 missing (no real errors) → exit 0, not 1.
    class WorksheetNotFound(Exception):
        pass

    def read(name):
        if name == "curated_picks":
            raise WorksheetNotFound("curated_picks")
        return [{"a": 1}]

    db = FakeDB()
    monkeypatch.setattr(mir, "_load_env", lambda: None)
    monkeypatch.setattr(mir, "_db", lambda: db)
    monkeypatch.setattr(mir, "_default_read_tab", read)
    monkeypatch.setattr(mir, "PWA_TABS", ["macro", "curated_picks"])
    assert mir.main([]) == 0


def test_main_all_failed_exit_two(monkeypatch):
    db = FakeDB()

    def always_bad(name):
        raise RuntimeError("nope")

    monkeypatch.setattr(mir, "_load_env", lambda: None)
    monkeypatch.setattr(mir, "_db", lambda: db)
    monkeypatch.setattr(mir, "_default_read_tab", always_bad)
    monkeypatch.setattr(mir, "PWA_TABS", ["macro", "options"])
    assert mir.main([]) == 2


def test_pwa_tabs_is_the_40_tab_contract():
    assert len(mir.PWA_TABS) == 40
    assert len(set(mir.PWA_TABS)) == 40            # no dupes
    # spot-check both ends + a by-name-only tab
    assert mir.PWA_TABS[0] == "daily_brief_latest"
    assert mir.PWA_TABS[-1] == "curated_picks"
    assert "uoa_alerts" in mir.PWA_TABS
    assert "scan_meta" in mir.PWA_TABS         # freshness heartbeat

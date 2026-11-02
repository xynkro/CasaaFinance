"""The VM job starter: what's due when, on New York time, and retries."""
from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("casaa_dispatch", ROOT / "deploy/vm/casaa_dispatch.py")
cd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cd)

ET = ZoneInfo("America/New_York")


def _at(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp).replace(tzinfo=ET)


def _names(now, fired=frozenset()):
    return [wf for _, wf, _ in cd.due(now, set(fired))]


def test_every_includes_both_ends():
    assert cd.every(30, "09:37", "10:37") == ["09:37", "10:07", "10:37"]


def test_the_plan_and_the_recheck_fire_at_their_clock_times():
    assert "daily-ideas-dm.yml" in _names(_at("2026-11-03T08:45:10"))
    assert "daily-ideas-dm.yml" in _names(_at("2026-11-03T09:47:10"))
    assert "daily-ideas-dm.yml" not in _names(_at("2026-11-03T08:44:59"))


def test_the_dm_is_started_as_a_real_send_not_the_dispatch_default_dry_run():
    (_, _, inputs), = [d for d in cd.due(_at("2026-11-03T08:45:10"), set()) if d[1] == "daily-ideas-dm.yml"]
    assert inputs == {"dry": "false", "force": "false"}


def test_times_are_new_york_clock_in_summer_and_winter():
    winter = _at("2026-11-03T08:45:10")
    summer = _at("2026-07-07T08:45:10")
    assert "daily-ideas-dm.yml" in _names(winter) and "daily-ideas-dm.yml" in _names(summer)
    assert winter.astimezone(ZoneInfo("UTC")).hour == 13 and summer.astimezone(ZoneInfo("UTC")).hour == 12


def test_nothing_fires_at_the_weekend_except_saturdays_flex_statement():
    assert _names(_at("2026-11-07T05:10:10")) == ["ibkr-flex-sync.yml"]   # Saturday
    assert _names(_at("2026-11-08T05:10:10")) == []                         # Sunday
    assert _names(_at("2026-11-02T05:10:10")) == []                         # Monday: Saturday already got Friday's
    assert _names(_at("2026-11-07T08:45:10")) == []


def test_a_missed_start_catches_up_inside_the_window_then_gives_up():
    assert "daily-ideas-dm.yml" in _names(_at("2026-11-03T08:54:00"))
    assert "daily-ideas-dm.yml" not in _names(_at("2026-11-03T08:55:00"))


def test_a_fired_start_does_not_fire_again_and_a_failed_one_retries(tmp_path):
    state = tmp_path / "s" / "state.json"
    calls = []

    def flaky(token, wf, inputs):
        calls.append(wf)
        return 500 if len(calls) == 1 else 204

    now = _at("2026-11-03T09:47:10")
    assert cd.tick(now, "t", send=flaky, state_path=state) >= 1           # first start failed
    first = list(calls)
    cd.tick(_at("2026-11-03T09:48:10"), "t", send=flaky, state_path=state)
    assert "daily-ideas-dm.yml" in calls                                  # retried or fired
    done = len(calls)
    cd.tick(_at("2026-11-03T09:49:10"), "t", send=flaky, state_path=state)
    assert len(calls) == done and first                                   # nothing fired twice


def test_state_from_another_day_or_a_corrupt_file_counts_as_nothing_fired(tmp_path):
    p = tmp_path / "state.json"
    cd.save_fired(p, "2026-11-02", {"x|08:45"})
    assert cd.load_fired(p, "2026-11-02") == {"x|08:45"}
    assert cd.load_fired(p, "2026-11-03") == set()
    p.write_text("not json")
    assert cd.load_fired(p, "2026-11-03") == set()


def test_no_job_runs_on_a_workflow_that_does_not_exist():
    for wf, _, _, _ in cd.JOBS:
        assert (ROOT / ".github/workflows" / wf).exists(), wf

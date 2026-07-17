"""Unit tests for the workout engine."""

from __future__ import annotations

import workout_engine as we


def test_bodyweight_always_available():
    exs = we.available_exercises([])
    assert exs, "bodyweight exercises must always exist"
    assert all(any(e in ("bodyweight",) for e in ex["equip"]) or not ex.get("need_all")
               for ex in exs)


def test_need_all_requires_every_piece():
    names = [e["name"] for e in we.available_exercises(["barbell"])]
    assert "Barbell Row" in names
    assert "Barbell Bench Press" not in names  # needs bench too
    names2 = [e["name"] for e in we.available_exercises(["barbell", "bench"])]
    assert "Barbell Bench Press" in names2


def test_equipment_filtering():
    names = [e["name"] for e in we.available_exercises(["treadmill"])]
    assert "Treadmill Intervals" in names
    assert "Lat Pulldown" not in names


def test_plan_days_range_clamped():
    p = we.generate_plan(["dumbbells"], days=99)
    assert p["days_per_week"] == 6
    p = we.generate_plan(["dumbbells"], days=1)
    assert p["days_per_week"] == 3


def test_plan_structure_all_day_counts():
    eq = ["dumbbells", "bench", "pullup_bar", "cable_machine", "treadmill"]
    for days in (3, 4, 5, 6):
        p = we.generate_plan(eq, days=days, goal="longevity", minutes=45)
        assert len(p["week"]) == days
        assert len(p["rest_days"]) == 7 - days
        for day in p["week"]:
            assert day["exercises"], "every day must have exercises"
            assert day["warmup"] and day["cooldown"]
            assert day["muscles_targeted"]
            for ex in day["exercises"]:
                for field in ("name", "sets", "reps", "rest", "primary_muscles",
                              "how_to", "why_it_matters"):
                    assert ex[field] not in (None, "", []), (day["title"], ex["name"], field)


def test_session_minutes_scale_exercise_count():
    eq = ["dumbbells", "bench", "barbell", "squat_rack", "cable_machine",
          "pullup_bar", "kettlebell", "treadmill"]
    short = we.generate_plan(eq, days=3, minutes=30)
    long = we.generate_plan(eq, days=3, minutes=60)
    assert len(short["week"][0]["exercises"]) <= len(long["week"][0]["exercises"])


def test_goals_change_prescription():
    eq = ["dumbbells", "bench"]
    strength = we.generate_plan(eq, days=3, goal="strength")
    fatloss = we.generate_plan(eq, days=3, goal="fatloss")
    s_ex = strength["week"][0]["exercises"][0]
    f_ex = fatloss["week"][0]["exercises"][0]
    assert s_ex["sets"] == 4 and f_ex["sets"] == 3
    assert strength["goal"] != fatloss["goal"]


def test_unknown_goal_falls_back():
    p = we.generate_plan(["dumbbells"], days=3, goal="get-huge-yesterday")
    assert p["goal"] == "Longevity & health"


def test_deterministic_with_seed():
    eq = ["dumbbells", "bench", "kettlebell"]
    a = we.generate_plan(eq, days=4, seed=42)
    b = we.generate_plan(eq, days=4, seed=42)
    assert a == b


def test_sparse_gym_still_fills_days():
    p = we.generate_plan(["resistance_bands"], days=6, minutes=60)
    for day in p["week"]:
        assert len(day["exercises"]) >= 3

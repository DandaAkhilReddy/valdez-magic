"""Valdez Magic workout engine.

Exercise database keyed by equipment, and a deterministic plan generator:
given available equipment, days/week, goal, and session length, produce a
weekly schedule with sets, reps, rest, targeted muscles, form cues, and
longevity notes.
"""

from __future__ import annotations

import random

# equipment ids the scanner/checklist can produce
EQUIPMENT = {
    "dumbbells": "Dumbbells",
    "barbell": "Barbell + plates",
    "bench": "Flat/adjustable bench",
    "squat_rack": "Squat rack / power cage",
    "pullup_bar": "Pull-up bar",
    "lat_pulldown": "Lat pulldown machine",
    "cable_machine": "Cable machine / crossover",
    "leg_press": "Leg press machine",
    "smith_machine": "Smith machine",
    "kettlebell": "Kettlebells",
    "resistance_bands": "Resistance bands",
    "treadmill": "Treadmill",
    "rowing_machine": "Rowing machine",
    "stationary_bike": "Stationary bike / spin bike",
    "elliptical": "Elliptical",
    "leg_curl": "Leg curl / extension machine",
    "chest_press": "Chest press machine",
    "shoulder_press": "Shoulder press machine",
    "pec_deck": "Pec deck / rear delt fly",
    "bodyweight": "Just my body (always available)",
}

# name, equipment(any-of), primary muscles, secondary, category, cues, longevity note
EXERCISES: list[dict] = [
    # --- push ---
    {"name": "Barbell Bench Press", "equip": ["barbell", "bench"], "need_all": True,
     "primary": ["chest"], "secondary": ["triceps", "shoulders"], "cat": "push",
     "cues": "Feet planted, shoulder blades pinched, bar to mid-chest, press up and slightly back.",
     "why": "Builds pressing strength that protects shoulder function as you age."},
    {"name": "Dumbbell Bench Press", "equip": ["dumbbells", "bench"], "need_all": True,
     "primary": ["chest"], "secondary": ["triceps", "shoulders"], "cat": "push",
     "cues": "Palms slightly inward, lower until elbows just below bench level, press without clanging.",
     "why": "Each arm works alone — fixes strength imbalances early."},
    {"name": "Machine Chest Press", "equip": ["chest_press"],
     "primary": ["chest"], "secondary": ["triceps"], "cat": "push",
     "cues": "Seat set so handles are at mid-chest. Push smooth, 2 seconds out, 3 seconds back.",
     "why": "Very joint-friendly way to keep pressing strength for life."},
    {"name": "Push-ups", "equip": ["bodyweight"],
     "primary": ["chest"], "secondary": ["triceps", "core"], "cat": "push",
     "cues": "Body in one straight line, hands under shoulders, chest to an inch off the floor.",
     "why": "The single most portable upper-body exercise — own it forever."},
    {"name": "Overhead Dumbbell Press", "equip": ["dumbbells"],
     "primary": ["shoulders"], "secondary": ["triceps", "core"], "cat": "push",
     "cues": "Core tight, don't arch the low back, press to lockout overhead.",
     "why": "Overhead reach is one of the first abilities aging takes away — keep it."},
    {"name": "Machine Shoulder Press", "equip": ["shoulder_press"],
     "primary": ["shoulders"], "secondary": ["triceps"], "cat": "push",
     "cues": "Back flat on pad, press without shrugging your shoulders up.",
     "why": "Safe overhead pressing with guided path."},
    {"name": "Lateral Raises", "equip": ["dumbbells"],
     "primary": ["shoulders"], "secondary": [], "cat": "push",
     "cues": "Slight elbow bend, raise to shoulder height, lead with elbows, no swinging.",
     "why": "Wider shoulders + healthier rotator cuff balance."},
    {"name": "Cable Triceps Pushdown", "equip": ["cable_machine"],
     "primary": ["triceps"], "secondary": [], "cat": "push",
     "cues": "Elbows pinned to sides, push to full lockout, control the way up.",
     "why": "Elbow-friendly triceps work — pushing power for daily life."},
    {"name": "Band Triceps Extension", "equip": ["resistance_bands"],
     "primary": ["triceps"], "secondary": [], "cat": "push",
     "cues": "Anchor band high, elbows tucked, extend fully.", "why": "Gentle on elbows, works anywhere."},

    # --- pull ---
    {"name": "Pull-ups / Assisted Pull-ups", "equip": ["pullup_bar"],
     "primary": ["back"], "secondary": ["biceps", "core"], "cat": "pull",
     "cues": "Full hang, pull chest to bar, control down. Use bands/assist if needed.",
     "why": "Relative strength king — grip + back strength predict healthy aging."},
    {"name": "Lat Pulldown", "equip": ["lat_pulldown"],
     "primary": ["back"], "secondary": ["biceps"], "cat": "pull",
     "cues": "Slight lean back, pull bar to upper chest, squeeze shoulder blades down.",
     "why": "Builds the pulling base for your first strict pull-up."},
    {"name": "One-arm Dumbbell Row", "equip": ["dumbbells", "bench"], "need_all": True,
     "primary": ["back"], "secondary": ["biceps"], "cat": "pull",
     "cues": "Flat back, pull dumbbell to hip, don't rotate the torso.",
     "why": "Counters desk posture; strengthens each side independently."},
    {"name": "Barbell Row", "equip": ["barbell"],
     "primary": ["back"], "secondary": ["biceps", "hamstrings"], "cat": "pull",
     "cues": "Hinge to ~45°, flat back, row to lower ribs.", "why": "Posture armor for your spine."},
    {"name": "Seated Cable Row", "equip": ["cable_machine"],
     "primary": ["back"], "secondary": ["biceps"], "cat": "pull",
     "cues": "Chest tall, pull to belly button, resist the stretch forward.",
     "why": "Smooth constant tension — great for joint health."},
    {"name": "Band Pull-aparts", "equip": ["resistance_bands"],
     "primary": ["shoulders", "back"], "secondary": [], "cat": "pull",
     "cues": "Arms straight, pull band to chest, squeeze rear shoulders.",
     "why": "The best 2-minute posture medicine that exists."},
    {"name": "Dumbbell Biceps Curls", "equip": ["dumbbells"],
     "primary": ["biceps"], "secondary": [], "cat": "pull",
     "cues": "Elbows at sides, curl without swinging, full range.",
     "why": "Elbow flexor strength helps carrying — groceries to grandkids."},
    {"name": "Rear Delt Fly (Pec Deck reversed)", "equip": ["pec_deck"],
     "primary": ["shoulders", "back"], "secondary": [], "cat": "pull",
     "cues": "Arms slightly bent, open wide, squeeze the back of your shoulders.",
     "why": "Balances all the pressing/typing your shoulders endure."},

    # --- legs ---
    {"name": "Barbell Back Squat", "equip": ["barbell", "squat_rack"], "need_all": True,
     "primary": ["quads", "glutes"], "secondary": ["core", "hamstrings"], "cat": "legs",
     "cues": "Bar on upper back, sit between your hips, depth to parallel, drive up through mid-foot.",
     "why": "Leg strength is the #1 physical predictor of independence in old age."},
    {"name": "Goblet Squat", "equip": ["dumbbells"],
     "primary": ["quads", "glutes"], "secondary": ["core"], "cat": "legs",
     "cues": "Hold dumbbell at chest, elbows inside knees at the bottom, chest tall.",
     "why": "Teaches perfect squat mechanics with minimal spine load."},
    {"name": "Kettlebell Goblet Squat", "equip": ["kettlebell"],
     "primary": ["quads", "glutes"], "secondary": ["core"], "cat": "legs",
     "cues": "Hold bell by the horns, sit deep, knees track over toes.",
     "why": "Mobility + strength in one movement."},
    {"name": "Leg Press", "equip": ["leg_press"],
     "primary": ["quads", "glutes"], "secondary": ["hamstrings"], "cat": "legs",
     "cues": "Feet shoulder width, lower until knees ~90°, never lock knees hard.",
     "why": "Heavy leg work with back fully supported."},
    {"name": "Romanian Deadlift", "equip": ["barbell"],
     "primary": ["hamstrings", "glutes"], "secondary": ["back"], "cat": "legs",
     "cues": "Soft knees, push hips back, bar close to legs, feel the hamstring stretch, stand tall.",
     "why": "Strong hips + hamstrings = a back that doesn't complain."},
    {"name": "Dumbbell Romanian Deadlift", "equip": ["dumbbells"],
     "primary": ["hamstrings", "glutes"], "secondary": ["back"], "cat": "legs",
     "cues": "Hinge at hips, flat back, dumbbells slide down your thighs.",
     "why": "Hip hinge pattern protects your spine every time you pick something up."},
    {"name": "Walking Lunges", "equip": ["bodyweight"],
     "primary": ["quads", "glutes"], "secondary": ["core"], "cat": "legs",
     "cues": "Long step, back knee kisses the floor, push through front heel.",
     "why": "Single-leg strength + balance — fall-proofing, literally."},
    {"name": "Kettlebell Swing", "equip": ["kettlebell"],
     "primary": ["glutes", "hamstrings"], "secondary": ["core", "cardio"], "cat": "legs",
     "cues": "It's a hip snap, not a squat. Arms are just ropes. Stand tall at the top.",
     "why": "Power + conditioning in one — power is what fades fastest with age."},
    {"name": "Leg Curl Machine", "equip": ["leg_curl"],
     "primary": ["hamstrings"], "secondary": [], "cat": "legs",
     "cues": "Slow curl, pause, 3-second lower.", "why": "Hamstring strength guards your knees and ACL."},
    {"name": "Calf Raises", "equip": ["bodyweight"],
     "primary": ["calves"], "secondary": [], "cat": "legs",
     "cues": "Full stretch at bottom, rise to tip-toes, 2-second squeeze.",
     "why": "Calf strength = ankle resilience and walking power for decades."},
    {"name": "Smith Machine Squat", "equip": ["smith_machine"],
     "primary": ["quads", "glutes"], "secondary": ["core"], "cat": "legs",
     "cues": "Feet slightly forward of the bar, control the descent.",
     "why": "Guided bar path — squat strength with training wheels."},

    # --- core ---
    {"name": "Plank", "equip": ["bodyweight"],
     "primary": ["core"], "secondary": ["shoulders"], "cat": "core",
     "cues": "Elbows under shoulders, squeeze glutes, don't let hips sag. Breathe.",
     "why": "A stiff, strong trunk is the foundation every other lift stands on."},
    {"name": "Dead Bug", "equip": ["bodyweight"],
     "primary": ["core"], "secondary": [], "cat": "core",
     "cues": "Low back pressed to floor, opposite arm/leg extend slowly.",
     "why": "Teaches your core to protect your spine while limbs move — daily-life armor."},
    {"name": "Cable Pallof Press", "equip": ["cable_machine"],
     "primary": ["core"], "secondary": [], "cat": "core",
     "cues": "Press handle straight out, resist the twist, 5-second holds.",
     "why": "Anti-rotation strength prevents the twisting injuries."},
    {"name": "Hanging Knee Raises", "equip": ["pullup_bar"],
     "primary": ["core"], "secondary": ["biceps"], "cat": "core",
     "cues": "No swinging — curl knees to chest, control down.",
     "why": "Grip + core together, gymnast style."},

    # --- cardio ---
    {"name": "Treadmill Intervals", "equip": ["treadmill"],
     "primary": ["cardio"], "secondary": ["quads", "calves"], "cat": "cardio",
     "cues": "1 min brisk / 2 min easy, repeat. Or steady zone-2 where you can talk.",
     "why": "VO2 max is the strongest single predictor of longevity. Non-negotiable."},
    {"name": "Rowing Machine", "equip": ["rowing_machine"],
     "primary": ["cardio"], "secondary": ["back", "quads"], "cat": "cardio",
     "cues": "Legs → hips → arms on the drive; arms → hips → legs on the way back.",
     "why": "Full-body, zero-impact conditioning — friendliest cardio on joints."},
    {"name": "Stationary Bike (Zone 2)", "equip": ["stationary_bike"],
     "primary": ["cardio"], "secondary": ["quads"], "cat": "cardio",
     "cues": "Pace where you can hold a conversation but wouldn't want to sing.",
     "why": "Zone-2 builds the aerobic engine that powers everything else."},
    {"name": "Elliptical Steady State", "equip": ["elliptical"],
     "primary": ["cardio"], "secondary": ["glutes"], "cat": "cardio",
     "cues": "Push AND pull the handles, keep cadence steady.",
     "why": "Joint-sparing cardio you can do daily."},
    {"name": "Jumping Jacks / High Knees", "equip": ["bodyweight"],
     "primary": ["cardio"], "secondary": ["calves"], "cat": "cardio",
     "cues": "Light on the feet, steady rhythm, 45s on / 15s off.",
     "why": "No equipment, heart rate up in 60 seconds."},
]

GOALS = {
    "longevity": {"sets": 3, "reps": "10-12", "rest": "60-90s", "label": "Longevity & health"},
    "strength": {"sets": 4, "reps": "5-8", "rest": "2-3 min", "label": "Strength"},
    "fatloss": {"sets": 3, "reps": "12-15", "rest": "45-60s", "label": "Fat loss"},
}

SPLITS = {
    3: [("Full Body A", None), ("Full Body B", None), ("Full Body C", None)],
    4: [("Upper Body", ["push", "pull"]), ("Lower Body", ["legs", "core"]),
        ("Upper Body", ["push", "pull"]), ("Lower Body + Cardio", ["legs", "cardio"])],
    5: [("Push", ["push"]), ("Pull", ["pull"]), ("Legs", ["legs"]),
        ("Upper Body", ["push", "pull"]), ("Full Body + Cardio", None)],
    6: [("Push", ["push"]), ("Pull", ["pull"]), ("Legs", ["legs"]),
        ("Push", ["push"]), ("Pull", ["pull"]), ("Legs + Cardio", ["legs", "cardio"])],
}

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def available_exercises(equipment: list[str]) -> list[dict]:
    """Exercises doable with the given equipment (bodyweight always included)."""
    eq = set(equipment) | {"bodyweight"}
    out = []
    for ex in EXERCISES:
        if ex.get("need_all"):
            if all(e in eq for e in ex["equip"]):
                out.append(ex)
        elif any(e in eq for e in ex["equip"]):
            out.append(ex)
    return out

def _pick(pool: list[dict], cats: list[str] | None, n: int, used: set[str], rng) -> list[dict]:
    cands = [e for e in pool if (cats is None or e["cat"] in cats)]
    fresh = [e for e in cands if e["name"] not in used]
    rng.shuffle(fresh)
    chosen = fresh[:n]
    if len(chosen) < n:  # allow repeats across the week if the gym is sparse
        extra = [e for e in cands if e not in chosen]
        rng.shuffle(extra)
        chosen += extra[: n - len(chosen)]
    for e in chosen:
        used.add(e["name"])
    return chosen


def generate_plan(equipment: list[str], days: int = 4, goal: str = "longevity",
                  minutes: int = 45, seed: int | None = None) -> dict:
    """Build a weekly plan. Deterministic for the same inputs when seed given."""
    days = max(3, min(6, days))
    goal = goal if goal in GOALS else "longevity"
    g = GOALS[goal]
    rng = random.Random(seed if seed is not None else f"{sorted(equipment)}-{days}-{goal}-{minutes}")
    pool = available_exercises(equipment)
    n_main = max(4, min(7, minutes // 7))  # ~6 exercises for 45 min
    used: set[str] = set()
    week = []
    split = SPLITS[days]
    for i, (title, cats) in enumerate(split):
        main = _pick(pool, cats, n_main - 1, used, rng)
        core = _pick(pool, ["core"], 1, used, rng)
        cardio_needed = cats is None or "cardio" in (cats or [])
        block = main + core
        muscles: dict[str, int] = {}
        for ex in block:
            for m in ex["primary"]:
                muscles[m] = muscles.get(m, 0) + 2
            for m in ex["secondary"]:
                muscles[m] = muscles.get(m, 0) + 1
        week.append({
            "day": DAY_NAMES[i] if days <= 5 else DAY_NAMES[i],
            "title": title,
            "duration_min": minutes,
            "warmup": "5 min easy cardio + arm circles, leg swings, bodyweight squats ×10",
            "exercises": [{
                "name": ex["name"],
                "sets": g["sets"],
                "reps": "8-10 min zone 2" if ex["cat"] == "cardio" else g["reps"],
                "rest": g["rest"],
                "primary_muscles": ex["primary"],
                "secondary_muscles": ex["secondary"],
                "how_to": ex["cues"],
                "why_it_matters": ex["why"],
            } for ex in block],
            "cooldown": "5 min walk + 30s stretch per muscle you trained",
            "muscles_targeted": sorted(muscles, key=muscles.get, reverse=True),
        })
    rest_days = [DAY_NAMES[i] for i in range(days, 7)]
    return {
        "goal": g["label"],
        "days_per_week": days,
        "session_minutes": minutes,
        "equipment_used": [EQUIPMENT.get(e, e) for e in equipment],
        "week": week,
        "rest_days": rest_days,
        "coach_notes": [
            "Progress rule: when you hit the top of the rep range on every set, add a little weight next time.",
            "Never train through sharp pain. Soreness is fine, pain is information.",
            f"Rest days ({', '.join(rest_days) if rest_days else 'built in'}): walk 20-30 min — recovery is where the growth happens.",
            "Protein: aim ~1.6-2 g per kg of body weight daily. Sleep 7-9 hours; it's free performance.",
        ],
    }

from datetime import date


def days_remaining(exam_date: date, today: date) -> int:
    return (exam_date - today).days


def priority_score(difficulty: int, is_weak: bool, exam_date: date, today: date) -> float:
    remaining = days_remaining(exam_date, today)
    urgency = 100 / (remaining + 1)
    weakness_factor = 1.5 if is_weak else 1.0
    return round(difficulty * weakness_factor * urgency, 4)


def build_timetable(subjects, daily_hours: float, today: date):
    scored = []
    for subject in subjects:
        exam_date = subject["exam_date"]
        if isinstance(exam_date, str):
            exam_date = date.fromisoformat(exam_date)
        remaining = days_remaining(exam_date, today)
        if remaining < 0:
            continue
        score = priority_score(subject["difficulty"], bool(subject["is_weak"]), exam_date, today)
        scored.append({
            "subject_id": subject["id"],
            "name": subject["name"],
            "days_remaining": remaining,
            "is_weak": bool(subject["is_weak"]),
            "difficulty": subject["difficulty"],
            "priority_score": score,
        })
    total_score = sum(s["priority_score"] for s in scored)
    if total_score <= 0:
        return []
    for s in scored:
        s["allocated_hours"] = round((s["priority_score"] / total_score) * daily_hours, 2)
    scored.sort(key=lambda s: s["priority_score"], reverse=True)
    return scored


def recommendation_score(base_priority: float, completion_fraction: float) -> float:
    return round(base_priority * (1 - max(0.0, min(1.0, completion_fraction))), 4)


def build_recommendations(subjects_with_progress, today: date, top_n: int = 3):
    ranked = []
    for subject in subjects_with_progress:
        exam_date = subject["exam_date"]
        if isinstance(exam_date, str):
            exam_date = date.fromisoformat(exam_date)
        remaining = days_remaining(exam_date, today)
        if remaining < 0:
            continue
        total = subject["total_topics"] or 0
        done  = subject["completed_topics"] or 0
        frac  = (done / total) if total else 0.0
        if total > 0 and done == total:
            continue
        base  = priority_score(subject["difficulty"], bool(subject["is_weak"]), exam_date, today)
        rscore = recommendation_score(base, frac)
        parts = []
        if remaining <= 1:
            parts.append("exam is imminent")
        elif remaining <= 3:
            parts.append(f"exam in {remaining} days")
        else:
            parts.append(f"{remaining} days to exam")
        if subject["is_weak"]:
            parts.append("weak subject")
        if total == 0:
            parts.append("no topics logged yet")
        else:
            parts.append(f"{round(frac*100)}% complete")
        ranked.append({
            "subject_id": subject["id"],
            "name": subject["name"],
            "days_remaining": remaining,
            "completion_percent": round(frac * 100),
            "recommendation_score": rscore,
            "reason": ", ".join(parts),
        })
    ranked.sort(key=lambda r: r["recommendation_score"], reverse=True)
    return ranked[:top_n]

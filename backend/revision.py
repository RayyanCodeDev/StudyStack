"""Small, deterministic spaced-repetition scheduler; all timestamps are UTC."""

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone

RATINGS = ("Again", "Hard", "Good", "Easy")


def utc_now():
    return datetime.now(timezone.utc)


def parse_due(value):
    try:
        value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def card_id(card):
    """Identity follows the question and answer, rather than their list position."""
    text = json.dumps([str(card.get("front") or "").strip(), str(card.get("back") or "").strip()],
                      ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def flashcards(result):
    """Ignore empty/duplicate cards so a repeated question shares one schedule."""
    seen = set()
    for card in result.get("flashcards", []):
        if not isinstance(card, dict) or not str(card.get("front") or "").strip() or not str(card.get("back") or "").strip():
            continue
        key = card_id(card)
        if key not in seen:
            seen.add(key)
            yield key, card


def clean_progress(progress, cards):
    if not isinstance(progress, dict):
        return {}
    out = {}
    for key, _ in flashcards({"flashcards": cards}):
        state = progress.get(key)
        if not isinstance(state, dict):
            continue
        due = parse_due(state.get("due_at"))
        reviewed = parse_due(state.get("reviewed_at"))
        try:
            interval = float(state.get("interval_days", 0))
            count = int(state.get("reviews", 0))
        except (TypeError, ValueError, OverflowError):
            continue
        if due is None or not math.isfinite(interval) or state.get("rating") not in RATINGS:
            continue
        out[key] = {"due_at": due.isoformat(), "reviewed_at": reviewed.isoformat() if reviewed else None,
                    "interval_days": max(0, min(interval, 365)), "reviews": max(0, min(count, 100000)),
                    "rating": state["rating"]}
    return out


def due_cards(result, now=None):
    now = now or utc_now()
    progress = clean_progress(result.get("review_progress"), result.get("flashcards", []))
    due = []
    for key, card in flashcards(result):
        when = parse_due(progress.get(key, {}).get("due_at"))
        if when is None or when <= now:
            # Previously reviewed, overdue cards come before brand-new cards.
            due.append((when or datetime.max.replace(tzinfo=timezone.utc), key, card))
    return [(key, card) for _, key, card in sorted(due, key=lambda item: item[0])]


def schedule_review(previous, rating, now=None):
    if rating not in RATINGS:
        raise ValueError("Choose Again, Hard, Good or Easy.")
    now = now or utc_now()
    previous = previous or {}
    interval = float(previous.get("interval_days", 0))
    if rating == "Again":
        interval = 10 / (24 * 60)
    elif rating == "Hard":
        interval = max(1, interval * 1.2)
    elif rating == "Good":
        interval = max(1, interval * 2.5)
    else:
        interval = max(4, interval * 3.5)
    interval = min(interval, 365)
    return {"due_at": (now + timedelta(days=interval)).isoformat(), "reviewed_at": now.isoformat(),
            "interval_days": interval, "reviews": min(int(previous.get("reviews", 0)) + 1, 100000),
            "rating": rating}


def apply_review(result, key, rating, now=None):
    if key not in dict(flashcards(result)):
        raise ValueError("That flashcard is no longer in this set.")
    progress = clean_progress(result.get("review_progress"), result.get("flashcards", []))
    progress[key] = schedule_review(progress.get(key), rating, now)
    return {**result, "review_progress": progress}


def interval_label(state):
    days = state["interval_days"]
    if days < 1:
        return f"{max(1, round(days * 24 * 60))} min"
    if days == round(days):
        return f"{round(days)} day{'s' if round(days) != 1 else ''}"
    return f"{days:.1f} days"

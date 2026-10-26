from datetime import datetime, timezone
from backend.auth import db
from backend.revision import apply_review, clean_progress

MAX_SETS = 50   # saved sets per student (keeps the free database plan from filling up)
MAX_CHAT = 60   # messages kept per set


# ---------- cleaning (used for database rows AND uploaded files, so bad data can't crash the app) ----------
def _s(v, n=20000):
    return str(v)[:n] if v is not None else ""


SUBJECT_ALIASES = {
    "math": "Mathematics", "maths": "Mathematics", "mathematics": "Mathematics",
    "physics": "Physics", "chemistry": "Chemistry", "biology": "Biology",
    "cs": "Computer Science", "computer science": "Computer Science",
    "computing": "Computer Science", "computer studies": "Computer Science",
    "english": "English", "english language": "English", "urdu": "Urdu",
    "islamiat": "Islamiat", "islamiyat": "Islamiat", "islamic studies": "Islamiat",
    "pakistan studies": "Pakistan Studies", "pak studies": "Pakistan Studies",
    "history": "History", "geography": "Geography", "science": "Science",
    "general science": "Science", "economics": "Economics",
    "business studies": "Business Studies", "accounting": "Accounting",
}


def normalize_subject(value):
    """Keep equivalent AI subject labels together, including older saved sets."""
    name = " ".join(_s(value, 100).split())
    key = name.casefold()
    if key in ("", "none", "null", "unknown", "n/a", "uncategorized"):
        return "Uncategorized"
    return SUBJECT_ALIASES.get(key, name.title())


def group_sets_by_subject(rows):
    """Sort subject tabs alphabetically while keeping newest-first set order."""
    groups = {}
    for row in rows:
        subject = normalize_subject(row.get("subject"))
        groups.setdefault(subject, []).append(row)
    return dict(sorted(groups.items(), key=lambda item: (item[0] == "Uncategorized", item[0].casefold())))


def search_sets(rows, query):
    """Match every search word across titles, subjects and the actual study text."""
    words = str(query or "").casefold().split()
    if not words:
        return list(rows)
    matches = []
    for row in rows:
        result = row.get("result") or {}
        parts = [row.get("title"), normalize_subject(row.get("subject")),
                 result.get("topic"), result.get("summary"), result.get("detailed_notes"), result.get("raw_text")]
        parts.extend(result.get("key_concepts", []))
        for card in result.get("flashcards", []):
            parts.extend([card.get("front"), card.get("back")])
        haystack = " ".join(str(p or "") for p in parts).casefold()
        if all(word in haystack for word in words):
            matches.append(row)
    return matches


def clean_chat(chat):
    out = []
    if isinstance(chat, list):
        for m in chat[-MAX_CHAT:]:
            if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str):
                out.append({"role": m["role"], "content": m["content"][:6000]})
    return out


def clean_result(r):
    """Return a safe, well-formed result dict, or None if this isn't study material."""
    if not isinstance(r, dict) or not (r.get("topic") or r.get("detailed_notes")):
        return None
    notes = r.get("detailed_notes", "")
    if isinstance(notes, dict):
        notes = "\n".join(f"- {v}" for v in notes.values())
    concepts = r.get("key_concepts")
    cards = r.get("flashcards")
    rels = r.get("relationships")
    result = {
        "subject": normalize_subject(r.get("subject")),
        "topic": _s(r.get("topic"), 200),
        "summary": _s(r.get("summary"), 3000),
        "detailed_notes": _s(notes, 30000),
        "key_concepts": [_s(c, 80) for c in concepts if isinstance(c, (str, int, float))][:12] if isinstance(concepts, list) else [],
        "relationships": [{"from": _s(x.get("from"), 80), "to": _s(x.get("to"), 80)}
                          for x in rels if isinstance(x, dict)][:20] if isinstance(rels, list) else [],
        "raw_text": _s(r.get("raw_text"), 20000),
        "flashcards": [{"front": _s(c.get("front"), 500), "back": _s(c.get("back"), 1500)}
                       for c in cards if isinstance(c, dict)][:30] if isinstance(cards, list) else [],
    }
    result["review_progress"] = clean_progress(r.get("review_progress"), result["flashcards"])
    return result


# ---------- database (every call returns an error message instead of crashing) ----------
def list_sets(include_material=True):
    try:
        fields = "id,title,subject,created_at" + (",result" if include_material else "")
        r = (db().table("study_sets").select(fields)
             .order("created_at", desc=True).limit(MAX_SETS).execute())
        rows = []
        for row in r.data or []:
            rows.append({**row, "result": clean_result(row.get("result")) or {}})
        return rows, None
    except Exception:
        return [], "Couldn't load your library. Please try again."


def save_set(result, chat):
    rows, err = list_sets(include_material=False)
    if err:
        return None, err
    if len(rows) >= MAX_SETS:
        return None, f"Your library is full ({MAX_SETS} sets). Delete an old set to save new ones."
    title = _s(result.get("topic"), 120).strip() or "Untitled"
    subject = normalize_subject(result.get("subject"))
    try:
        r = db().table("study_sets").insert(
            {"title": title, "subject": subject, "result": result, "chat": clean_chat(chat)}
        ).execute()
        return r.data[0]["id"], None
    except Exception:
        return None, "Couldn't save to your library."


def load_set(set_id):
    try:
        r = db().table("study_sets").select("result,chat").eq("id", set_id).limit(1).execute()
    except Exception:
        return None, "Couldn't open that set. Please try again."
    if not r.data:
        return None, "That set no longer exists."
    result = clean_result(r.data[0].get("result"))
    if result is None:
        return None, "That set is damaged and can't be opened."
    return {"result": result, "chat": clean_chat(r.data[0].get("chat"))}, None


def update_chat(set_id, chat):
    try:
        db().table("study_sets").update(
            {"chat": clean_chat(chat), "updated_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", set_id).execute()
    except Exception:
        pass  # a failed chat save should never interrupt studying


def review_saved_card(set_id, key, rating):
    """Save only review progress; leave the student's chat and other sets alone.

    Optimistic concurrency protects another tab's recent reviews/chat updates.
    Existing study_sets JSON stores the schedule, so no SQL migration is needed.
    """
    try:
        client = db()
        response = (client.table("study_sets").select("result,updated_at")
                    .eq("id", set_id).limit(1).execute())
        if not response.data:
            return None, "That set no longer exists. Refresh your library."
        row = response.data[0]
        result = clean_result(row.get("result"))
        if result is None:
            return None, "That set can't be reviewed."
        updated = apply_review(result, key, rating)
        # Preserve any other metadata in the stored result.
        stored_result = {**row["result"], "review_progress": updated["review_progress"]}
        query = (client.table("study_sets").update(
            {"result": stored_result, "updated_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", set_id))
        if row.get("updated_at") is None:
            query = query.is_("updated_at", "null")
        else:
            query = query.eq("updated_at", row["updated_at"])
        saved = query.execute()
        if not saved.data:
            return None, "This set changed in another tab. Refresh your library and try again."
        return updated, None
    except Exception:
        return None, "Couldn't save your revision. Try again; your previous schedule is unchanged."


def delete_set(set_id):
    try:
        db().table("study_sets").delete().eq("id", set_id).execute()
        return None
    except Exception:
        return "Couldn't delete that set. Please try again."


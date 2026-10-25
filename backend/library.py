from datetime import datetime, timezone
from backend.auth import db

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
    return {
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


# ---------- database (every call returns an error message instead of crashing) ----------
def list_sets():
    try:
        r = (db().table("study_sets").select("id,title,subject,created_at")
             .order("created_at", desc=True).limit(MAX_SETS).execute())
        return r.data or [], None
    except Exception:
        return [], "Couldn't load your library. Please try again."


def save_set(result, chat):
    rows, err = list_sets()
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


def delete_set(set_id):
    try:
        db().table("study_sets").delete().eq("id", set_id).execute()
        return None
    except Exception:
        return "Couldn't delete that set. Please try again."


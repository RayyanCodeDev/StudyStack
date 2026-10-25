import re
from backend.auth import db

DAILY_CAP = 50  # must match the limit inside the database function award_points


def normalize_code(raw):
    """Accept 'stk-ab12cd', 'AB12CD' or 'STK AB12CD' and return 'STK-AB12CD', or None if invalid."""
    c = re.sub(r"[^A-Za-z0-9]", "", raw or "").upper()
    if len(c) == 9 and c.startswith("STK"):
        c = c[3:]
    return "STK-" + c if len(c) == 6 else None


def award(kind):
    """Ask the database to award points. Returns the points actually given (0 if capped or on any error)."""
    try:
        return int(db().rpc("award_points", {"p_kind": kind}).execute().data or 0)
    except Exception:
        return 0


def fetch_social():
    """Everything the Progress tab needs, in one dict. Never raises."""
    out = {"progress": None, "friends": [], "board": [], "code": None, "err": None}
    try:
        d = db()
        out["progress"] = d.rpc("my_progress", {}).execute().data
        out["friends"] = d.rpc("list_friends", {}).execute().data or []
        out["board"] = d.rpc("friends_leaderboard", {}).execute().data or []
        r = d.table("profiles").select("friend_code").limit(1).execute()
        out["code"] = r.data[0]["friend_code"] if r.data else None
    except Exception:
        out["err"] = "Couldn't load your progress. Please try again in a moment."
    return out


def send_request(raw):
    """Returns (success, message)."""
    code = normalize_code(raw)
    if not code:
        return False, "Friend codes look like STK-AB12CD. Check the code and try again."
    try:
        status = db().rpc("send_friend_request", {"p_code": code}).execute().data
    except Exception:
        return False, "Couldn't send the request. Please try again."
    messages = {
        "sent": (True, "Request sent! They'll see it in their Progress tab."),
        "accepted": (True, "You're now friends 🎉"),
        "already_friends": (False, "You're already friends with this person."),
        "pending": (False, "You already sent this person a request. Wait for them to accept."),
        "not_found": (False, "No one has that code. Check it and try again."),
        "self": (False, "That's your own code 🙂 Share it with a classmate instead."),
        "limit": (False, "You've reached the limit for friends or pending requests."),
    }
    return messages.get(status, (False, "Something went wrong. Please try again."))


def respond_request(friendship_id, accept):
    """Accept or decline an incoming request. Returns an error message or None."""
    try:
        db().rpc("respond_friend_request", {"p_id": int(friendship_id), "p_accept": bool(accept)}).execute()
        return None
    except Exception:
        return "Couldn't update that request. Please try again."


def remove_friend(friendship_id):
    """Remove a friend or cancel a request you sent. Returns an error message or None."""
    try:
        db().rpc("remove_friend", {"p_id": int(friendship_id)}).execute()
        return None
    except Exception:
        return "Couldn't remove that. Please try again."

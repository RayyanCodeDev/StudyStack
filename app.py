import copy
import io
import json
import random
import re
import textwrap
import time
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image
from pypdf import PdfReader, PdfWriter
from backend.ai_pipeline import analyze_image, analyze_pdf, grade_answer, chat_with_notes
from backend.voice import MAX_AUDIO_MB, evaluate_voice
from backend.auth import EMAIL_RE, auth_configured, sign_in, sign_up, sign_out
from backend.library import (MAX_SETS, clean_chat, clean_result, delete_set, list_sets,
                             load_set, save_set, update_chat, group_sets_by_subject, search_sets, review_saved_card)
from backend.revision import (RATINGS, apply_review, card_id, due_cards, flashcards,
                              interval_label, parse_due, schedule_review)
from backend.offline_flashcards import build_offline_flashcards, offline_filename
from backend.read_aloud import read_aloud, concept_map_text, quiz_reading_text
from backend.social import DAILY_CAP, award as award_points, fetch_social, remove_friend, respond_request, send_request

BASE_DIR = Path(__file__).parent
LOGO_HEADER = BASE_DIR / "studystack_logo_header.png"
LOGO_LOGIN = BASE_DIR / "studystack_logo_login.png"
FAVICON = BASE_DIR / "studystack_favicon.png"


def load_icon():
    try:
        return Image.open(FAVICON)
    except Exception:
        return "📚"


st.set_page_config(page_title="StudyStack", page_icon=load_icon(), layout="wide")

MAX_PDF_MB = 20
MAX_PDF_PAGES = 30  # pages analyzed at once (keeps results good and free-tier usage low)
MAX_RESTORE_MB = 2

DEFAULTS = {
    "analysis_result": None,
    "file_key": None,
    "chat_history": [],
    "mcq": None,             # state of the multiple-choice quiz
    "study_minutes": 25,     # Focus Hub
    "sessions_completed": 2, # Focus Hub
    "focus_timer_active": False, # Focus Hub
    "focus_timer_end": 0,        # Focus Hub
    "focus_timer_mins": 25,      # Focus Hub
    "voice_gen": 0,          # changing this empties the voice recorder
    "user_name": "",
    "name_asked": False,
    "auth_mode": None,       # None = not chosen yet, "user" or "guest"
    "auth_user": None,
    "upload_gen": 0,         # changing this resets the file uploaders
    "current_set_id": None,  # library row the current work is saved in (signed-in users only)
    "lib_cache": None,       # cached library list, None = reload from the database
    "save_note": "",
    "confirm_delete": None,
    "social": None,          # cached progress / friends / leaderboard, None = reload
    "flash": "",             # one-time message shown after a rerun (e.g. "+2 points")
    "friend_msg": None,
    "confirm_remove": None,
    "library_search": "",
    "revision_reveal": None,
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = copy.deepcopy(v)


def clean_name(raw):
    """Keep letters (any language), digits, spaces and a few name symbols; max 30 chars."""
    return re.sub(r"[^\w\s'’.-]", "", raw or "", flags=re.UNICODE).strip()[:30]


def reset_session():
    """Forget everything about the current visitor (used on sign out)."""
    gen = st.session_state.upload_gen + 1
    for k, v in DEFAULTS.items():
        st.session_state[k] = copy.deepcopy(v)
    st.session_state.upload_gen = gen


def show_logo(path, width, fallback):
    """Show a logo image, or a plain text title if the file isn't in the repo."""
    if path.exists():
        st.image(str(path), width=width)
    else:
        st.markdown(fallback)


# ---------- TOP BAR (logo, name, sign in/out, dark mode) ----------
_mode = st.session_state.auth_mode
if _mode is None:
    _, tog_col = st.columns([5, 1.8], vertical_alignment="center")
    with tog_col:
        dark = st.toggle("Dark mode", value=True, key="dark_mode")
else:
    logo_col, _, name_col, btn_col, tog_col = st.columns([3.2, 1.2, 2.4, 1.9, 1.9], vertical_alignment="center")
    with logo_col:
        show_logo(LOGO_HEADER, 250, "## 📚 StudyStack")
    with name_col:
        if _mode == "user":
            st.markdown(f"👤 **{clean_name(st.session_state.auth_user['name'])}**")
        else:
            st.markdown("👤 **Guest**")
    with btn_col:
        if _mode == "user":
            if st.button("Sign out", key="btn_signout"):
                sign_out()
                reset_session()
                st.rerun()
        else:
            if st.button("Sign in", key="btn_signin"):
                reset_session()
                st.rerun()
    with tog_col:
        dark = st.toggle("Dark mode", value=True, key="dark_mode")

THEMES = {
    True: dict(
        TEXT="#f2f5ff", MUTED="#aab4d4", GLASS="rgba(255,255,255,0.07)", GLASS2="rgba(255,255,255,0.10)",
        BORDER="rgba(255,255,255,0.20)", SHADOW="0 10px 40px rgba(0,0,0,0.45)", GLOW="rgba(124,140,255,0.35)",
        BASE="#080b1a", O1="rgba(124,92,255,0.55)", O2="rgba(0,200,255,0.40)", O3="rgba(255,90,140,0.40)",
        INPUT_BG="#1a1c29",
    ),
    False: dict(
        TEXT="#14182b", MUTED="#4a5273", GLASS="rgba(255,255,255,0.55)", GLASS2="rgba(255,255,255,0.75)",
        BORDER="rgba(255,255,255,0.95)", SHADOW="0 10px 40px rgba(70,80,160,0.20)", GLOW="rgba(124,140,255,0.45)",
        BASE="#e9eeff", O1="rgba(150,120,255,0.55)", O2="rgba(80,200,255,0.50)", O3="rgba(255,150,180,0.50)",
        INPUT_BG="#ffffff",
    ),
}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;700;800&display=swap');
:root{--text:__TEXT__;--muted:__MUTED__;--glass:__GLASS__;--glass2:__GLASS2__;--border:__BORDER__;--shadow:__SHADOW__;--glow:__GLOW__;--input-bg:__INPUT_BG__;}
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"]{visibility:hidden;}
header[data-testid="stHeader"]{background:transparent;}

/* Backdrop: colored light orbs give the glass something to blur */
.stApp{
  background:
    radial-gradient(circle at 12% 18%, __O1__ 0, transparent 38%),
    radial-gradient(circle at 88% 8%,  __O2__ 0, transparent 36%),
    radial-gradient(circle at 70% 92%, __O3__ 0, transparent 40%),
    __BASE__;
  background-attachment:fixed;
  font-family:'Plus Jakarta Sans',sans-serif;
}
.stApp h1,.stApp h2,.stApp h3,.stApp h4,.stApp p,.stApp li,.stApp label,.stApp summary,
.stApp [data-testid="stMarkdownContainer"],.stApp [data-testid="stCaptionContainer"]{color:var(--text);font-family:'Plus Jakarta Sans',sans-serif;}
.stApp h1{font-weight:800;letter-spacing:-0.02em;}
[data-testid="stMetric"] *{color:var(--text)!important;}

/* Frosted glass cards (containers created with key="card_*") */
[class*="st-key-card"]{
  background:linear-gradient(145deg,var(--glass2),var(--glass));
  backdrop-filter:blur(22px) saturate(160%);-webkit-backdrop-filter:blur(22px) saturate(160%);
  border:1px solid var(--border)!important;border-radius:24px!important;
  box-shadow:var(--shadow),0 0 0 1px var(--glow),inset 0 1px 0 rgba(255,255,255,0.35);
  padding:1.4rem 1.6rem!important;margin-bottom:1.1rem;
}

/* Pill tabs */
.stTabs [data-baseweb="tab-list"]{gap:8px;padding:6px;background:var(--glass);border:1px solid var(--border);
  border-radius:999px;backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);box-shadow:var(--shadow);width:fit-content;max-width:100%;overflow-x:auto;}
.stTabs [data-baseweb="tab"]{background:transparent;border-radius:999px;padding:8px 18px;height:auto;}
.stTabs [data-baseweb="tab"] p{color:var(--muted);font-weight:600;}
.stTabs [aria-selected="true"]{background:linear-gradient(135deg,#7c5cff,#00c8ff)!important;box-shadow:0 0 22px var(--glow);}
.stTabs [aria-selected="true"] p{color:#fff!important;}
.stTabs [data-baseweb="tab-highlight"],.stTabs [data-baseweb="tab-border"]{display:none;}

/* Expanders, inputs, alerts, uploader */
[data-testid="stExpander"]{background:var(--glass);border:1px solid var(--border)!important;border-radius:16px!important;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);}
[data-testid="stExpander"] summary{font-weight:600;}

/* Fixed Inputs for Mobile (Dark & Light Mode) */
.stTextArea textarea, .stTextInput input, .stNumberInput input, [data-baseweb="input"] input, [data-baseweb="textarea"] textarea {
    background: var(--input-bg) !important;
    color: var(--text) !important;
    -webkit-text-fill-color: var(--text) !important;
    border: 1px solid var(--border) !important;
    border-radius: 14px !important;
    caret-color: var(--text) !important;
}

/* Fix placeholder text visibility */
.stTextArea textarea::placeholder, .stTextInput input::placeholder {
    color: var(--muted) !important;
    -webkit-text-fill-color: var(--muted) !important;
    opacity: 0.7 !important;
}
[data-testid="stFileUploaderDropzone"]{background:var(--glass2);border:1.5px dashed var(--border);border-radius:18px;}
[data-testid="stFileUploaderDropzone"] *{color:var(--text)!important;}
[data-testid="stAlert"]{background:var(--glass2);border:1px solid var(--border);border-radius:16px;backdrop-filter:blur(14px);}
.stButton>button,.stDownloadButton>button,[data-testid="stDownloadButton"]>button,[data-testid="stFormSubmitButton"]>button{background:linear-gradient(135deg,#7c5cff,#00c8ff);color:#fff;border:0;border-radius:999px;padding:.55rem 1.6rem;font-weight:700;box-shadow:0 0 22px var(--glow);white-space:nowrap;}
.stButton>button:hover,.stDownloadButton>button:hover,[data-testid="stDownloadButton"]>button:hover,[data-testid="stFormSubmitButton"]>button:hover{filter:brightness(1.12);color:#fff;}

/* Top bar: keep "Dark mode" on one line */
.st-key-dark_mode *{white-space:nowrap;}

/* Centered logo on the login card */
.st-key-card_login [data-testid="stImage"]{display:flex;justify-content:center;}

/* Forms and chat bubbles */
[data-testid="stForm"]{border:none!important;padding:0!important;background:transparent!important;}
[data-testid="stChatMessage"]{background:var(--glass);border:1px solid var(--border);border-radius:18px;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);}

/* Center the concept map */
[data-testid="stGraphVizChart"]{display:flex;justify-content:center;}
[data-testid="stGraphVizChart"] svg{margin:0 auto;max-width:100%;height:auto;}
</style>
"""
css = CSS
for k, v in THEMES[dark].items():
    css = css.replace(f"__{k}__", v)
st.markdown(css, unsafe_allow_html=True)

# ---------- THE HOOKLINE (Top Most Area) ----------
st.markdown("""
<div style="text-align: center; margin-top: 0.5rem; margin-bottom: 1.5rem;">
    <h1 style="font-family: 'Plus Jakarta Sans', sans-serif; font-size: 2.8rem; font-weight: 800; 
               background: -webkit-linear-gradient(45deg, #7c5cff, #00c8ff); 
               -webkit-background-clip: text; -webkit-text-fill-color: transparent; 
               margin: 0; letter-spacing: -0.03em;">
        Snap it. Stack it. Master it.
    </h1>
</div>
""", unsafe_allow_html=True)
# -----------------------------------------------

def card(name):
    return st.container(border=True, key=f"card_{name}")


def need_upload(tab_name):
    with card(f"empty_{tab_name}"):
        st.info("Upload a screenshot or PDF in the Capture tab first, or open a set from My Library.")


# ---------- LOGIN PAGE ----------
def start_user_session(user):
    st.session_state.auth_mode = "user"
    st.session_state.auth_user = user
    st.session_state.user_name = clean_name(user["name"])
    st.session_state.name_asked = bool(st.session_state.user_name)  # known name = tutor doesn't ask
    st.rerun()


def login_page():
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        with card("login"):
            _l, _c, _r = st.columns([1, 2.4, 1])
            with _c:
                show_logo(LOGO_LOGIN, 240, "## 📚 StudyStack")
            st.caption("Sign in to keep your progress, or try the app as a guest.")

            if not auth_configured():
                st.warning("Accounts aren't set up yet. You can still continue as a guest.")
            else:
                t_in, t_up = st.tabs(["Sign in", "Create account"])

                with t_in:
                    with st.form("signin_form"):
                        email = st.text_input("Email", key="si_email")
                        pw = st.text_input("Password", type="password", key="si_pw")
                        go = st.form_submit_button("Sign in")
                    if go:
                        email = email.strip().lower()
                        if not EMAIL_RE.match(email) or not pw:
                            st.error("Enter your email and password.")
                        else:
                            with st.spinner("Signing in..."):
                                user, err = sign_in(email, pw)
                            if err:
                                st.error(err)
                            else:
                                start_user_session(user)

                with t_up:
                    with st.form("signup_form"):
                        nm = st.text_input("Display name", max_chars=30, key="su_name",
                                           help="Shown to your tutor and your friends. Use a nickname if you like.")
                        email2 = st.text_input("Email", key="su_email")
                        pw2 = st.text_input("Password (at least 8 characters)", type="password", key="su_pw")
                        go2 = st.form_submit_button("Create account")
                    if go2:
                        nm = clean_name(nm)
                        email2 = email2.strip().lower()
                        if not nm:
                            st.error("Please enter a display name.")
                        elif not EMAIL_RE.match(email2):
                            st.error("Please enter a valid email address.")
                        elif len(pw2) < 8:
                            st.error("Your password must be at least 8 characters.")
                        else:
                            with st.spinner("Creating your account..."):
                                user, err = sign_up(email2, pw2, nm)
                            if err:
                                st.error(err)
                            else:
                                start_user_session(user)

            st.divider()
            if st.button("Continue as guest"):
                st.session_state.auth_mode = "guest"
                st.rerun()
            st.caption("Guest mode needs no email or name. Nothing is saved on our side, and guests don't appear on leaderboards.")
            st.caption("🔒 Don't upload IDs, passwords or private chats. Images are sent to AI to be analyzed.")

if st.session_state.auth_mode is None:
    login_page()
    st.stop()

# one-time message left over from the previous run (e.g. points earned just before a rerun)
if st.session_state.flash:
    st.toast(st.session_state.flash)
    st.session_state.flash = ""


# ---------- HELPERS ----------
def get_context(res):
    """Everything the tutor can use: summary, notes and extracted text (capped for safety)."""
    parts = [str(res.get("summary", "")), str(res.get("detailed_notes", "")), str(res.get("raw_text", ""))]
    return "\n\n".join(p for p in parts if p.strip())[:20000]


def fix_latex(s):
    """Repair formula symbols that JSON turned into control characters (tab, backspace...)."""
    s = str(s)
    fixes = {
        "\text": r"\text",
        "\times": r"\times",
        "\theta": r"\theta",
        "\tau": r"\tau",
        "\frac": r"\frac",
        "\beta": r"\beta",
        "\bar": r"\bar",
        "\rho": r"\rho",
        "\rightarrow": r"\rightarrow",
        "\alpha": r"\alpha",
        "\approx": r"\approx",
        "\vec": r"\vec",
    }
    for bad, good in fixes.items():
        s = s.replace(bad, good)
    return s


def pdf_page_count(data):
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            return None
        return len(reader.pages)
    except Exception:
        return None


def pdf_slice(data, start, end):
    """Return a new PDF containing pages start..end (1-based, inclusive)."""
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        reader.decrypt("")
    writer = PdfWriter()
    for i in range(start - 1, end):
        writer.add_page(reader.pages[i])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def award(kind, immediate=False):
    """Give points to a signed-in student. The database enforces the daily caps."""
    if st.session_state.auth_mode != "user":
        return
    pts = award_points(kind)
    st.session_state.social = None  # progress changed, reload it next time
    if pts > 0:
        msg = f"+{pts} points 🔥"
        if immediate:
            st.toast(msg)
        else:
            st.session_state.flash = msg  # shown after the next rerun


def get_social(force=False):
    s = st.session_state.social
    if force or s is None or time.time() - s["t"] > 90:
        s = fetch_social()
        s["t"] = time.time()
        st.session_state.social = s
    return s


def friend_action(fn, *args):
    err = fn(*args)
    if err:
        st.error(err)
    else:
        st.session_state.social = None
        st.session_state.confirm_remove = None
        st.rerun()


def save_result(result, key):
    """Store a fresh analysis, and save it to the library when the visitor is signed in."""
    if "error" in result:
        st.error(f"Analysis failed: {result['error']}")
        return
    clean = clean_result(result)
    if clean is None:
        st.error("The AI reply didn't contain study material. Please try again.")
        return
    st.session_state.analysis_result = clean
    st.session_state.file_key = key
    st.session_state.chat_history = []  # new material = fresh chat (name is kept)
    st.session_state.revision_reveal = None
    st.session_state.mcq = None
    st.session_state.current_set_id = None
    if st.session_state.auth_mode == "user":
        set_id, err = save_set(clean, [])
        if err:
            st.session_state.save_note = "⚠️ " + err
        else:
            st.session_state.current_set_id = set_id
            st.session_state.lib_cache = None
            st.session_state.save_note = "✅ Saved to your library."
        award("analyze", immediate=True)
    else:
        st.session_state.save_note = "Guest mode: nothing is saved. Use the 📚 My Library tab to download this set."


def show_done():
    st.success("Analysis complete. Open the other tabs.")
    note = st.session_state.save_note
    if note:
        (st.warning if note.startswith("⚠️") else st.caption)(note)


def persist_chat():
    sid = st.session_state.current_set_id
    if st.session_state.auth_mode == "user" and sid:
        update_chat(sid, st.session_state.chat_history)


def open_saved(set_id):
    data, err = load_set(set_id)
    if err:
        st.error(err)
        return
    st.session_state.analysis_result = data["result"]
    st.session_state.chat_history = data["chat"]
    st.session_state.revision_reveal = None
    st.session_state.mcq = None
    st.session_state.current_set_id = set_id
    st.session_state.file_key = ("saved", set_id)
    st.session_state.upload_gen += 1  # clears the uploader so an old file can't overwrite this set
    st.session_state.save_note = ""
    st.rerun()


def render_revision(result, set_id=None, namespace="current"):
    """Review one card at a time, revealing its answer before choosing a rating."""
    scope_key = f"speech_revision_{namespace}"
    with st.container(key=scope_key):
        
        # --- RESTORED NOTES & TXT DOWNLOAD ---
        st.write(f"**Subject:** {result.get('subject')} | **Topic:** {result.get('topic')}")
        notes = fix_latex(result.get("detailed_notes") or "No notes generated.")
        with st.expander("📖 Detailed study notes", expanded=True):
            read_aloud(notes, key=f"tts_notes_{namespace}", scope=scope_key)
            st.markdown(notes)
        st.download_button("⬇️ Download notes as TXT", notes, file_name="study_notes.txt", key=f"dl_notes_{namespace}")
        st.write("---")
        # -------------------------------------

        all_cards = list(flashcards(result))
        if not all_cards:
            st.info("No flashcards in this set yet.")
            return
        st.download_button("⬇️ Download offline flashcards", build_offline_flashcards(result),
                           file_name=offline_filename(result.get("topic")), mime="text/html",
                           key=f"offline_flashcards_{namespace}",
                           help="Open the downloaded HTML file in a browser without internet. Offline progress stays on your device.")
        now = datetime.now(timezone.utc)
        due = due_cards(result, now)
        reviewed = len(result.get("review_progress", {}))
        st.caption(f"{len(due)} due · {reviewed} of {len(all_cards)} cards reviewed")
        if st.session_state.auth_mode == "guest":
            st.caption("Guest progress lasts for this session. Download your set from My Library to keep its revision schedule.")
        elif not set_id:
            st.caption("This set isn't saved. Download it from My Library to keep its revision schedule.")
        identity = set_id or card_id({"front": result.get("topic"), "back": str(all_cards)})
        scope = f"{namespace}_{identity}"
        view = st.radio("Flashcards to show", ["Due for revision", "All flashcards"],
                        horizontal=True, key=f"revision_view_{scope}")
        available = due if view == "Due for revision" else all_cards
        if not available:
            st.success("You're caught up! No cards are due right now.")
            dates = [parse_due(state.get("due_at")) for state in result.get("review_progress", {}).values()]
            dates = [date for date in dates if date and date > now]
            if dates:
                minutes = max(1, round((min(dates) - now).total_seconds() / 60))
                wait = f"{minutes} min" if minutes < 60 else (f"{minutes / 60:.1f} hours" if minutes < 1440 else f"{minutes / 1440:.1f} days")
                st.caption(f"Your next card is due in about {wait}. You can still browse All flashcards.")
            return
        choices = dict(available)
        key = st.selectbox("Choose a flashcard", list(choices),
                           format_func=lambda value: choices[value]["front"], key=f"revision_card_{scope}")
        current = choices[key]
        previous = result.get("review_progress", {}).get(key)
        reveal_token = (scope, key, (previous or {}).get("reviewed_at"))
        st.markdown(f"**{current['front']}**")
        if st.button("Show answer", key=f"reveal_{scope}_{key}"):
            st.session_state.revision_reveal = reveal_token
        spoken_card = current["front"]
        if st.session_state.revision_reveal == reveal_token:
            spoken_card += "\nAnswer: " + current["back"]
        read_aloud(spoken_card, key=f"tts_revision_{scope}", scope=scope_key)
        if st.session_state.revision_reveal != reveal_token:
            st.caption("Try answering first, then reveal the answer and rate how well you remembered it.")
            return
        st.markdown(fix_latex(current["back"]))
        st.caption("How well did you remember? The time on each button is your next review interval.")
        for column, rating in zip(st.columns(4), RATINGS):
            next_state = schedule_review(previous, rating, now)
            if column.button(f"{rating} · {interval_label(next_state)}", key=f"rate_{scope}_{key}_{rating}"):
                if st.session_state.auth_mode == "user" and set_id:
                    updated, err = review_saved_card(set_id, key, rating)
                    if err:
                        st.error(err)
                        return
                    st.session_state.lib_cache = None
                else:
                    updated = apply_review(result, key, rating)
                if set_id == st.session_state.current_set_id:
                    st.session_state.analysis_result = updated
                st.session_state.revision_reveal = None
                st.session_state.flash = f"Review recorded. Next review in {interval_label(updated['review_progress'][key])}."
                st.rerun()

def build_mcq(flashcards):
    cards = [c for c in flashcards if str(c.get("front") or "").strip() and str(c.get("back") or "").strip()]
    backs = sorted({str(c["back"]).strip() for c in cards})
    questions = []
    for c in cards:
        correct = str(c["back"]).strip()
        others = [b for b in backs if b != correct]
        random.shuffle(others)
        options = [correct] + others[:3]
        if len(options) < 2:
            continue
        random.shuffle(options)
        questions.append({"q": str(c["front"]).strip(), "options": options, "answer": correct})
    random.shuffle(questions)
    return questions


def mcq_quiz(flashcards):
    if st.session_state.mcq is None:
        st.session_state.mcq = {
            "qs": build_mcq(flashcards),
            "i": 0,
            "score": 0,
            "checked": False,
            "correct": False,
            "awarded": False,
            "run": random.randint(0, 10**9),
        }
    m = st.session_state.mcq
    qs = m["qs"]
    if len(qs) < 1:
        st.info("Not enough flashcards to build a multiple-choice quiz from this material.")
        return
    if m["i"] >= len(qs):
        st.success(f"🎉 Finished! Your score: {m['score']}/{len(qs)}")
        if not m["awarded"]:
            m["awarded"] = True
            if len(qs) >= 3:
                award("quiz", immediate=True)
        if st.button("🔄 Restart quiz", key="mcq_restart"):
            st.session_state.mcq = None
            st.rerun()
        return
    q = qs[m["i"]]
    st.progress(m["i"] / len(qs))
    st.caption(f"Question {m['i'] + 1} of {len(qs)} | Score: {m['score']}")
    st.subheader(q["q"])
    pick = st.radio("Choose one:", q["options"], index=None, key=f"mcq_pick_{m['run']}_{m['i']}", disabled=m["checked"])
    read_aloud(quiz_reading_text(q, m["checked"], m["correct"]),
               key=f"tts_mcq_{m['run']}_{m['i']}", scope="card_quiz")
    if not m["checked"]:
        if st.button("Check answer", key="mcq_check"):
            if pick is None:
                st.warning("Pick an answer first.")
            else:
                m["checked"] = True
                m["correct"] = (pick == q["answer"])
                if m["correct"]:
                    m["score"] += 1
                st.rerun()
    else:
        if m["correct"]:
            st.success("✅ Correct!")
        else:
            st.error(f"❌ Not quite. The correct answer is: {q['answer']}")
        label = "Next question ➡️" if m["i"] + 1 < len(qs) else "See results 🏁"
        if st.button(label, key="mcq_next"):
            m["i"] += 1
            m["checked"] = False
            st.rerun()


def build_dot(topic, concepts, links):
    esc = lambda s: str(s).replace('"', "'").replace("\\", "")
    wrap = lambda s, w=16: "\\n".join(textwrap.wrap(esc(s), w)) or " "

    lines = [
        "graph G {",
        '  graph [bgcolor="transparent", overlap=false, splines=true, ranksep=1.6, root="topic", pad=0.3];',
        '  node  [shape=ellipse, style=filled, penwidth=0, fontname="Helvetica-Bold", fontsize=13, fontcolor="#0b1020", margin="0.18,0.10"];',
        '  edge  [color="#8da2c0", penwidth=1.3];',
        f'  topic [label="{wrap(topic, 18)}", fillcolor="#ff8a8a", fontsize=17, margin="0.3,0.2"];',
    ]
    ids = {}
    for i, c in enumerate(concepts):
        ids[str(c).strip().lower()] = f"c{i}"
        lines.append(f'  c{i} [label="{wrap(c)}", fillcolor="#7ee8dc"];')
        lines.append(f"  topic -- c{i};")
    for link in links:
        a = ids.get(str(link.get("from", "")).strip().lower())
        b = ids.get(str(link.get("to", "")).strip().lower())
        if a and b and a != b:
            lines.append(f'  {a} -- {b} [style=dashed, color="#b79cff"];')
    lines.append("}")
    return "\n".join(lines)


# ---------- PAGE ----------
st.caption("Turn screenshots and PDFs into notes, flashcards, a concept map, an AI tutor and a focus hub.")

tab_home, tab_cap, tab_lib, tab_prog, tab_graph, tab_chat, tab_focus, tab_quiz = st.tabs(
    ["🏠 Home", "📸 Capture", "📚 My Library", "🏆 Progress", "🕸️ Knowledge Graph",
     "💬 AI Tutor", "⏱️ Focus Hub", "🧠 Metacognition Quiz"]
)

# --- HOME ---
with tab_home:
    with card("home"):
        st.header("Welcome to StudyStack")
        st.write("Upload a screenshot or a PDF of a lecture, syllabus or chat. StudyStack extracts the text, writes notes, "
                 "makes flashcards, draws a concept map, grades your explanations, tutors you by text or voice, "
                 "and tracks your daily study focus time.")
        if st.session_state.auth_mode == "guest":
            st.info("You're in guest mode, so nothing is saved on our side. Use **Sign in** (top right) to create an account, "
                    "keep your streak and compete with friends.")

# --- CAPTURE ---
with tab_cap:
    with card("upload"):
        st.header("📸 Capture")
        uploaded = st.file_uploader("Upload a screenshot (PNG, JPG) or a PDF", type=["png", "jpg", "jpeg", "pdf"],
                                    key=f"uploader_{st.session_state.upload_gen}")

        if uploaded is not None:
            is_pdf = uploaded.name.lower().endswith(".pdf")

            if not is_pdf:
                # Screenshots are analyzed automatically, once per new file
                st.image(uploaded, caption="Uploaded screenshot", width=400)
                key = ("img", uploaded.name, uploaded.size)
                if st.session_state.file_key != key:
                    with st.spinner("Extracting knowledge and generating study materials..."):
                        result = analyze_image(uploaded)
                    save_result(result, key)
                if st.session_state.file_key == key:
                    show_done()

            else:
                data = uploaded.getvalue()
                if uploaded.size > MAX_PDF_MB * 1024 * 1024:
                    st.error(f"This PDF is larger than {MAX_PDF_MB} MB. Try a smaller file or split it first.")
                else:
                    total = pdf_page_count(data)
                    if not total:
                        st.error("Couldn't read this PDF. It may be password-protected or damaged.")
                    else:
                        st.write(f"📄 **{uploaded.name}** · {total} page{'s' if total != 1 else ''}")
                        fid = f"{uploaded.name}_{uploaded.size}"
                        c1, c2, _ = st.columns([1, 1, 3])
                        start = int(c1.number_input("From page", min_value=1, max_value=total, value=1, step=1, key=f"from_{fid}"))
                        end = int(c2.number_input("To page", min_value=1, max_value=total,
                                                  value=min(total, MAX_PDF_PAGES), step=1, key=f"to_{fid}"))
                        count = end - start + 1
                        key = ("pdf", uploaded.name, uploaded.size, start, end)

                        if end < start:
                            st.error("'To page' must be the same as or after 'From page'.")
                        elif count > MAX_PDF_PAGES:
                            st.warning(f"Please pick at most {MAX_PDF_PAGES} pages at a time (you picked {count}). "
                                       "You can analyze the next chapter afterwards.")
                        else:
                            st.caption(f"{count} page{'s' if count != 1 else ''} selected.")
                            if st.button("Analyze pages"):
                                with st.spinner("Reading your PDF and generating study materials..."):
                                    result = analyze_pdf(pdf_slice(data, start, end))
                                save_result(result, key)
                            if st.session_state.file_key == key:
                                show_done()

# --- MY LIBRARY ---
with tab_lib:
    res = st.session_state.analysis_result
    with card("library"):
        st.header("📚 My Library")

        if st.session_state.auth_mode == "user":
            if st.session_state.lib_cache is None:
                rows, err = list_sets()
                st.session_state.lib_cache = {"rows": rows, "err": err}
            lib = st.session_state.lib_cache

            if lib["err"]:
                st.error(lib["err"])
                if st.button("Try again"):
                    st.session_state.lib_cache = None
                    st.rerun()
            elif not lib["rows"]:
                st.info("Nothing saved yet. Analyze a screenshot or PDF and it will appear here automatically.")
            else:
                st.caption(f"{len(lib['rows'])} of {MAX_SETS} sets saved. To study a set, press Open, then use the other tabs.")
                query = st.text_input("Search your library", key="library_search",
                                      placeholder="Search titles, subjects or words inside your notes")
                matched = search_sets(lib["rows"], query)
                matched_ids = {row["id"] for row in matched}
                if query.strip():
                    st.caption(f"{len(matched)} of {len(lib['rows'])} sets match your search.")
                if not matched:
                    st.info("No matching resources. Try another word or clear your search.")

                with st.expander("🔁 Due for revision", expanded=True):
                    review_sets = [row for row in matched if list(flashcards(row.get("result") or {}))]
                    due_count = sum(len(due_cards(row["result"])) for row in review_sets)
                    st.write(f"**{due_count} flashcards due** in {'matching sets' if query.strip() else 'your library'}.")
                    st.caption("Again repeats sooner; Hard, Good and Easy gradually increase the gap between reviews.")
                    if review_sets:
                        by_id = {row["id"]: row for row in review_sets}
                        selected = st.selectbox("Study set to revise", list(by_id), key="library_revision_set",
                                                format_func=lambda value: f"{by_id[value]['title']} · {len(due_cards(by_id[value]['result']))} due")
                        active = by_id[selected]
                        render_revision(active["result"], active["id"], namespace="library")
                    else:
                        st.caption("Save a set with flashcards to start revising.")
                    if st.button("Refresh library & due cards", key="refresh_library"):
                        st.session_state.lib_cache = None
                        st.rerun()

                st.caption("Your notes are automatically organized by the subject identified by AI.")
                subject_groups = group_sets_by_subject(lib["rows"])
                subject_tabs = st.tabs(list(subject_groups))
                for subject_tab, subject_rows in zip(subject_tabs, subject_groups.values()):
                    with subject_tab:
                        subject_rows = [row for row in subject_rows if row["id"] in matched_ids]
                        if not subject_rows:
                            st.info("No resources in this subject match your search.")
                        for row in subject_rows:
                            c1, c2, c3, c4 = st.columns([5, 2, 1.3, 1.3])
                            c1.markdown(f"**{row['title']}**")
                            c2.caption(str(row["created_at"])[:10])
                            if c3.button("Open", key=f"open_{row['id']}"):
                                open_saved(row["id"])
                            if c4.button("Delete", key=f"del_{row['id']}"):
                                st.session_state.confirm_delete = row["id"]
                                st.rerun()

                            if st.session_state.confirm_delete == row["id"]:
                                st.warning(f"Delete “{row['title']}”? This can't be undone.")
                                y, n, _ = st.columns([1.3, 1, 4])
                                if y.button("Yes, delete", key=f"yes_{row['id']}"):
                                    err = delete_set(row["id"])
                                    if err:
                                        st.error(err)
                                    else:
                                        if st.session_state.current_set_id == row["id"]:
                                            st.session_state.current_set_id = None
                                        st.session_state.confirm_delete = None
                                        st.session_state.lib_cache = None
                                        st.rerun()
                                if n.button("Cancel", key=f"no_{row['id']}"):
                                    st.session_state.confirm_delete = None
                                    st.rerun()
        else:
            st.write("As a guest, nothing is stored on our side. Download your study set to keep it, and upload it here later to continue.")

        if res is not None:
            st.divider()
            st.write(f"Currently open: **{res.get('topic') or 'Untitled'}**")
            payload = json.dumps({"app": "studystack", "version": 1, "result": res,
                                  "chat": st.session_state.chat_history}, ensure_ascii=False)
            st.download_button("⬇️ Download this set", payload, file_name="studystack_set.json",
                               mime="application/json", key="dl_set")

        if st.session_state.auth_mode == "guest":
            st.divider()
            st.subheader("Restore a saved set")
            f = st.file_uploader("Upload a StudyStack set (.json)", type=["json"], key=f"restore_{st.session_state.upload_gen}")
            if f is not None:
                if f.size > MAX_RESTORE_MB * 1024 * 1024:
                    st.error(f"That file is too large (max {MAX_RESTORE_MB} MB).")
                else:
                    try:
                        payload_in = json.loads(f.getvalue().decode("utf-8"))
                    except Exception:
                        payload_in = None
                    restored = clean_result(payload_in.get("result")) if isinstance(payload_in, dict) else None
                    if restored is None:
                        st.error("This doesn't look like a StudyStack set.")
                    elif st.button("Load this set"):
                        st.session_state.analysis_result = restored
                        st.session_state.chat_history = clean_chat(payload_in.get("chat"))
                        st.session_state.revision_reveal = None
                        st.session_state.mcq = None
                        st.session_state.current_set_id = None
                        st.session_state.file_key = ("file", f.name, f.size)
                        st.session_state.upload_gen += 1
                        st.session_state.save_note = ""
                        st.rerun()

# --- PROGRESS ---
with tab_prog:
    if st.session_state.auth_mode != "user":
        with card("prog_guest"):
            st.header("🏆 Progress")
            st.info("Sign in to track your streak and compete with friends. Guests aren't ranked.")
    else:
        soc = get_social()
        prog = soc["progress"]

        with card("progress"):
            st.header("🏆 Your progress")
            if soc["err"] or not prog:
                st.error(soc["err"] or "No progress data yet.")
            else:
                streak = int(prog.get("streak", 0))
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("🔥 Streak", f"{streak} day{'s' if streak != 1 else ''}")
                m2.metric("Today", f"{prog.get('today', 0)} / {DAILY_CAP}")
                m3.metric("This week", prog.get("week", 0))
                m4.metric("Total", prog.get("total", 0))
                days = prog.get("last7") or []
                if days:
                    df = pd.DataFrame({"Day": [d["day"] for d in days], "Points": [d["points"] for d in days]})
                    st.bar_chart(df, x="Day", y="Points")
                st.caption("Earn points: +10 for a new set, +2 per tutor question, +5 per finished quiz or quiz answer "
                           f"(30+ characters). Maximum {DAILY_CAP} a day. Study a little every day to grow your streak.")
            if st.button("Refresh", key="refresh_social"):
                get_social(force=True)
                st.rerun()

        with card("friends"):
            st.header("👥 Friends")
            st.caption("Friends only see your display name and your weekly points. Never your email.")

            if soc["code"]:
                st.write("Your friend code. Share it with classmates:")
                st.code(soc["code"], language=None)

            with st.form("add_friend", clear_on_submit=True):
                code_in = st.text_input("Add a friend with their code", placeholder="STK-AB12CD")
                add = st.form_submit_button("Send request")
            if add:
                st.session_state.friend_msg = send_request(code_in)
                st.session_state.social = None
                st.rerun()
            fm = st.session_state.friend_msg
            if fm:
                (st.success if fm[0] else st.warning)(fm[1])
                st.session_state.friend_msg = None

            friends = soc["friends"]
            incoming = [x for x in friends if x["status"] == "pending" and x["direction"] == "incoming"]
            outgoing = [x for x in friends if x["status"] == "pending" and x["direction"] == "outgoing"]
            accepted = [x for x in friends if x["status"] == "accepted"]

            if incoming:
                st.subheader("Requests for you")
                for x in incoming:
                    c1, c2, c3 = st.columns([4, 1.3, 1.3])
                    c1.markdown(f"**{clean_name(x['name']) or 'Student'}** wants to be friends")
                    if c2.button("Accept", key=f"acc_{x['id']}"):
                        friend_action(respond_request, x["id"], True)
                    if c3.button("Decline", key=f"dec_{x['id']}"):
                        friend_action(respond_request, x["id"], False)

            if outgoing:
                st.subheader("Waiting for a reply")
                for x in outgoing:
                    c1, c2 = st.columns([5, 1.6])
                    c1.markdown(f"⏳ **{clean_name(x['name']) or 'Student'}**")
                    if c2.button("Cancel", key=f"can_{x['id']}"):
                        friend_action(remove_friend, x["id"])

            if accepted:
                st.subheader("Your friends")
                for x in accepted:
                    nm = clean_name(x["name"]) or "Student"
                    c1, c2 = st.columns([5, 1.6])
                    c1.markdown(f"🧑‍🎓 **{nm}**")
                    if c2.button("Remove", key=f"rm_{x['id']}"):
                        st.session_state.confirm_remove = x["id"]
                        st.rerun()
                    if st.session_state.confirm_remove == x["id"]:
                        st.warning(f"Remove {nm} from your friends?")
                        y, n, _ = st.columns([1.5, 1, 4])
                        if y.button("Yes, remove", key=f"rmy_{x['id']}"):
                            friend_action(remove_friend, x["id"])
                        if n.button("Cancel", key=f"rmn_{x['id']}"):
                            st.session_state.confirm_remove = None
                            st.rerun()
            elif not incoming and not outgoing:
                st.info("No friends yet. Share your code, or enter a classmate's code above.")

        with card("board"):
            st.header("🏅 Weekly leaderboard")
            st.caption("You and your friends only. Resets every Monday.")
            board = soc["board"]
            if len(board) <= 1:
                st.info("Add friends to start competing. Once they accept, you'll all appear here.")
            medals = ["🥇", "🥈", "🥉"]
            for i, row in enumerate(board):
                icon = medals[i] if i < 3 else f"{i + 1}."
                who = clean_name(row.get("name")) or "Student"
                if row.get("me"):
                    who += " (you)"
                c1, c2 = st.columns([5, 1.6])
                c1.markdown(f"**{icon} {who}**")
                c2.markdown(f"**{row.get('points', 0)}** pts")

# --- KNOWLEDGE GRAPH ---
with tab_graph:
    res = st.session_state.analysis_result
    if res is None:
        need_upload("graph")
    else:
        with card("graph"):
            st.header("Concept map")
            topic_name = str(res.get("topic", "")).strip().lower()
            concepts, seen = [], set()
            for c in res.get("key_concepts", []):
                name_c = str(c or "").strip()
                low = name_c.lower()
                if name_c and low != topic_name and low not in seen:
                    seen.add(low)
                    concepts.append(name_c)
            if concepts:
                dot = build_dot(res.get("topic", "Topic"), concepts, res.get("relationships", []))
                try:
                    st.graphviz_chart(dot, engine="twopi", use_container_width=True)
                except TypeError:  # older Streamlit without the engine argument
                    st.graphviz_chart(dot, use_container_width=True)
                st.caption("Solid lines connect the topic to its concepts. Dashed lines show how concepts relate.")
                map_words = concept_map_text(res.get("topic", "Topic"), concepts, res.get("relationships", []))
                read_aloud(map_words, key="tts_mindmap", scope="card_graph")
                with st.expander("Read the concept map in words"):
                    st.text(map_words)
            else:
                st.info("No key concepts were found in this material.")

        with card("flash"):
            st.header("Study notes & Flashcards")
            render_revision(res, st.session_state.current_set_id)

# --- AI TUTOR & VOICE ---
with tab_chat:
    res = st.session_state.analysis_result
    if res is None:
        need_upload("chat")
    else:
        context = get_context(res)
        name = st.session_state.user_name
        topic = res.get("topic", "your notes")

        with card("chat"):
            st.header("AI Tutor & Voice Hub")
            st.caption("StudyStack is an AI and can make mistakes. Double-check important facts, especially before exams.")
            # Step 1: ask the student's name (skipped for signed-in users, who already have one)
            if not st.session_state.name_asked:
                with st.chat_message("assistant"):
                    st.markdown("Hi! I'm your StudyStack tutor 👋 What should I call you?")
                with st.form("name_form", clear_on_submit=True):
                    n = st.text_input("Your name", max_chars=30, placeholder="e.g. Ayesha")
                    c1, c2, _ = st.columns([1, 1, 4])
                    go = c1.form_submit_button("Continue")
                    skip = c2.form_submit_button("Skip")
                if go:
                    cleaned = clean_name(n)
                    if cleaned:
                        st.session_state.user_name = cleaned
                        st.session_state.name_asked = True
                        st.rerun()
                    else:
                        st.warning("Type a name, or press Skip.")
                if skip:
                    st.session_state.user_name = ""
                    st.session_state.name_asked = True
                    st.rerun()

            # Step 2: voice + text chat
            else:
                st.write("Ask by text, or record your voice to ask a question or explain a concept out loud.")

                audio = st.audio_input("🎙️ Record a voice question or Feynman explanation",
                                       key=f"voice_{st.session_state.voice_gen}")
                if audio is not None:
                    st.audio(audio)
                    if st.button("🚀 Process voice message", key="voice_go"):
                        if audio.size > MAX_AUDIO_MB * 1024 * 1024:
                            st.error(f"That recording is too long (max {MAX_AUDIO_MB} MB). Try a shorter one.")
                        else:
                            with st.spinner("Listening and evaluating your audio..."):
                                reply = evaluate_voice(audio.getvalue(), context, name)
                            if reply.startswith("⚠️"):
                                st.warning(reply)
                            else:
                                st.session_state.chat_history.append({"role": "user", "content": "🎙️ *[Spoken voice message]*"})
                                st.session_state.chat_history.append({"role": "assistant", "content": reply})
                                persist_chat()
                                award("tutor")
                                st.session_state.voice_gen += 1  # empties the recorder
                                st.rerun()

                st.markdown("---")
                if not st.session_state.chat_history:
                    hello = f"Nice to meet you, {name}! " if name else "Hi there! "
                    with st.chat_message("assistant"):
                        st.markdown(f"{hello}Ask me anything about **{topic}**, or try: \"Explain this like I'm 5\".")
                for m in st.session_state.chat_history:
                    with st.chat_message(m["role"]):
                        st.markdown(m["content"])

                with st.form("chat_form", clear_on_submit=True):
                    q = st.text_input("Ask about the material", placeholder="Type your question and press Enter")
                    sent = st.form_submit_button("Ask")

                if sent:
                    if q.strip():
                        with st.spinner("Thinking..."):
                            reply = chat_with_notes(q, context, st.session_state.chat_history, name)
                        if reply.startswith("⚠️"):
                            st.warning(reply)  # errors are shown but not saved in the chat
                        else:
                            st.session_state.chat_history.append({"role": "user", "content": q})
                            st.session_state.chat_history.append({"role": "assistant", "content": reply})
                            persist_chat()
                            if len(q.strip()) >= 5:
                                award("tutor")
                            st.rerun()
                    else:
                        st.warning("Type a question first.")

                b1, b2, _ = st.columns([1, 1, 4])
                if st.session_state.chat_history and b1.button("Clear chat", key="clear_chat"):
                    st.session_state.chat_history = []
                    persist_chat()
                    st.rerun()
                if b2.button("Change name"):
                    st.session_state.name_asked = False
                    st.rerun()

# --- FOCUS HUB ---
with tab_focus:
    with card("focus_hub_tab"):
        st.header("⏱️ Focus & Pomodoro Hub")
        
        if st.session_state.focus_timer_active:
            # --- RUNNING TIMER STATE ---
            st.write("Stay locked in. Do not close this tab.")
            timer_placeholder = st.empty()
            
            # Real Python Timer Loop (Blocks cheating)
            while time.time() < st.session_state.focus_timer_end:
                remaining = int(st.session_state.focus_timer_end - time.time())
                if remaining < 0:
                    remaining = 0
                mins, secs = divmod(remaining, 60)
                
                timer_placeholder.markdown(f"""
                <div style="background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.15); border-radius: 20px; padding: 40px; text-align: center; font-family: 'Plus Jakarta Sans', sans-serif; color: white;">
                    <div style="font-size: 5rem; font-weight: 800; margin-bottom: 10px;">{mins:02d}:{secs:02d}</div>
                    <p style="color: #aab4d4;">Focusing...</p>
                </div>
                """, unsafe_allow_html=True)
                time.sleep(1)
            
            # When loop finishes
            mins_added = st.session_state.focus_timer_mins
            st.session_state.study_minutes += mins_added
            st.session_state.sessions_completed += 1
            st.session_state.focus_timer_active = False
            
            st.balloons()
            st.success(f"🎉 Session complete! +{mins_added} minutes added to your focus time.")
            time.sleep(2)
            st.rerun()
            
        else:
            # --- SETUP STATE ---
            st.write("Stay locked in. Choose your study mode, track your focus time, and build your daily study streak.")
            
            col1, col2 = st.columns(2)
            with col1:
                session_type = st.selectbox("Select Study Mode", ["Deep Work Pomodoro (25m)", "Shallow Work (30m)", "Revision (10m)"],
                                            key="focus_hub_study_mode")
            with col2:
                st.metric("Total Focus Time Today", f"{st.session_state.study_minutes} mins", delta="+15 mins vs yesterday")

            st.markdown("---")
            
            selected_minutes = 25 if session_type == "Deep Work Pomodoro (25m)" else (30 if session_type == "Shallow Work (30m)" else 10)
            
            st.write(f"Ready to focus for **{selected_minutes} minutes**?")
            st.caption("⚠️ *Warning: You must stay on this tab for the entire duration. If you switch tabs or refresh, the session will reset.*")
            
            if st.button("🚀 Start Focus Session"):
                st.session_state.focus_timer_active = True
                st.session_state.focus_timer_end = time.time() + (selected_minutes * 60)
                st.session_state.focus_timer_mins = selected_minutes
                st.rerun()

            st.markdown("---")
            st.subheader("📊 Study Analytics")
            st.write(f"**Completed Sessions Today:** {st.session_state.sessions_completed}")

            progress_val = min(st.session_state.study_minutes / 120.0, 1.0)
            st.write("Daily Goal Progress (Target: 120 mins):")
            st.progress(progress_val)

            if st.session_state.study_minutes >= 120:
                st.success("🎉 Daily study goal reached! Amazing work.")
            else:
                st.caption(f"Keep going! {max(0, 120 - st.session_state.study_minutes)} mins left to hit your daily goal.")

# --- METACOGNITION QUIZ ---
with tab_quiz:
    res = st.session_state.analysis_result
    if res is None:
        need_upload("quiz")
    else:
        topic = res.get("topic", "the topic")
        with card("quiz"):
            st.header("🧠 Metacognition Quiz")
            mode = st.radio("Quiz mode", ["Multiple choice", "Feynman (explain it)"], horizontal=True, key="quiz_mode")
            if mode == "Multiple choice":
                mcq_quiz(res.get("flashcards", []))
            else:
                st.write(f"Explain **{topic}** in your own words and get graded.")
                answer = st.text_area("Your explanation", key="feynman_answer")
                
                # --- COPY BUTTON FEATURE ---
                components.html(
                    """
                    <style>
                    body { margin: 0; padding: 0; overflow: hidden; background-color: transparent; }
                    .copy-btn {
                        background: rgba(255, 255, 255, 0.05);
                        border: 1px solid rgba(255, 255, 255, 0.15);
                        color: #f2f5ff;
                        border-radius: 999px;
                        padding: 8px 16px;
                        font-size: 14px;
                        font-weight: 600;
                        cursor: pointer;
                        font-family: 'Plus Jakarta Sans', sans-serif;
                        transition: 0.3s;
                        width: 100%;
                        text-align: center;
                    }
                    .copy-btn:hover {
                        background: rgba(255, 255, 255, 0.15);
                    }
                    </style>
                    <button class="copy-btn" onclick="copyText()">📋 Copy Explanation</button>
                    <script>
                    function copyText() {
                        const textareas = window.parent.document.querySelectorAll('textarea');
                        if (textareas.length > 0) {
                            const target = textareas[textareas.length - 1]; // grabs the latest textarea
                            if (target && target.value) {
                                navigator.clipboard.writeText(target.value).then(() => {
                                    alert("✅ Copied to clipboard!");
                                });
                            } else {
                                alert("⚠️ Your explanation is empty.");
                            }
                        }
                    }
                    </script>
                    """,
                    height=45
                )
                # ---------------------------

                prompt_text = f"Explain {topic} in your own words."
                if answer.strip():
                    prompt_text += "\nYour explanation: " + answer
                read_aloud(prompt_text, key="tts_feynman", scope="card_quiz")
                if st.session_state.auth_mode == "user":
                    st.caption("Answers of 30+ characters earn points.")
                if st.button("Grade my answer", key="feynman_grade"):
                    if answer.strip():
                        with st.spinner("Grading..."):
                            feedback = grade_answer(topic, answer)
                        with st.container(key="speech_quiz_feedback"):
                            st.write(feedback)
                            read_aloud(feedback, key="tts_feynman_feedback", scope="speech_quiz_feedback")
                        if not feedback.startswith("⚠️") and len(answer.strip()) >= 30:
                            award("quiz", immediate=True)
                    else:
                        st.warning("Type an explanation first.")

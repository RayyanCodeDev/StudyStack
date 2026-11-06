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
from backend.ai_pipeline import analyze_image, analyze_pdf, grade_answer, chat_with_notes, think_first_reply, make_distractors
from backend.voice import MAX_AUDIO_MB, evaluate_voice
from backend.auth import EMAIL_RE, auth_configured, sign_in, sign_up, sign_out
from backend.library import (MAX_SETS, clean_chat, clean_result, delete_set, list_sets,
                             load_set, save_set, update_chat, group_sets_by_subject, search_sets, review_saved_card)
from backend.revision import (RATINGS, apply_review, card_id, due_cards, flashcards,
                              interval_label, parse_due, schedule_review)
from backend.offline_flashcards import build_offline_flashcards, offline_filename
from backend.read_aloud import read_aloud, concept_map_text, quiz_reading_text
from backend.sources import make_image_source, make_pdf_source, save_source, load_source, source_bytes
from backend.social import DAILY_CAP, award as award_points, fetch_social, remove_friend, respond_request, send_request

BASE_DIR = Path(__file__).parent
LOGO_HEADER = BASE_DIR / "studystack_logo_header.png"
LOGO_LOGIN = BASE_DIR / "studystack_logo_login.png"
FAVICON = BASE_DIR / "studystack_favicon.png"

# --- UNIVERSAL MULTI-SECTOR PUBLIC STUDY VAULTS (Nursery/KG to FCPS & PhD) ---
GLOBAL_MULTI_SECTOR_LIBRARY = [
    {
        "title": "Oxford & Cambridge Early Years: Nursery, KG & Prep Phonics & Numbers",
        "sector": "Juniors / Early Years (Nursery, KG, Prep)",
        "subject": "Early Learning & Phonics",
        "sources_count": 15,
        "summary": "Interactive early childhood learning resources featuring Jolly Phonics, Oxford Reading Tree stories, basic number recognition, shapes, and motor skills practice.",
        "key_concepts": ["Alphabet Sounds (Phonics)", "Counting 1-100", "Basic Shapes & Colors", "Story Comprehension", "Handwriting Tracing"],
        "flashcards": [
            {"front": "What sound does the letter 'S' make in phonics?", "back": "The snake sound: /s/ /s/ sun."},
            {"front": "How many sides does a triangle have?", "back": "Three sides."}
        ],
        "mcq": [{"q": "Which shape is round like a ball?", "options": ["Circle", "Square", "Triangle", "Rectangle"], "answer": "Circle"}]
    },
    {
        "title": "Matriculation Physics (Class 9-10 Sindh & Federal Board)",
        "sector": "Matriculation (SSC)",
        "subject": "Physics",
        "sources_count": 25,
        "summary": "Board exam notes covering Physical Quantities, Kinematics, Dynamics, Turning Effect of Forces, Gravitation, and Work & Energy.",
        "key_concepts": ["Scalar & Vector", "Newton's Laws", "Momentum", "Atmospheric Pressure", "Kinetic Energy"],
        "flashcards": [
            {"front": "State Newton's Second Law of Motion.", "back": "F = ma. The acceleration of an object as produced by a net force is directly proportional to the magnitude of the net force."},
            {"front": "What is the formula for gravitational potential energy?", "back": "PE = mgh"}
        ],
        "mcq": [{"q": "What is the value of gravitational acceleration g on Earth?", "options": ["9.8 m/s²", "10 m/s²", "8.9 m/s²", "9.1 m/s²"], "answer": "9.8 m/s²"}]
    },
    {
        "title": "Intermediate (F.Sc Part 1 & 2) Board Physics & Chemistry Master Notes",
        "sector": "Intermediate / Board Students (HSSC)",
        "subject": "Pre-Engineering & Pre-Medical Sciences",
        "sources_count": 42,
        "summary": "Sindh and Federal Board curriculum notes covering Electrostatics, Current Electricity, Atomic Spectra, Chemical Bonding, and Organic Reaction Mechanisms.",
        "key_concepts": ["Coulomb's Law", "Gauss's Law", "Hybridization of Orbitals", "Benzene Reactions", "Thermodynamics"],
        "flashcards": [
            {"front": "State Gauss's Law in electrostatics.", "back": "The total electric flux through any closed surface is equal to 1/ε₀ times the total charge enclosed by that surface."},
            {"front": "What is the hybridization of carbon atoms in ethene (C2H4)?", "back": "sp² hybridization"}
        ],
        "mcq": [{"q": "Which of the following is a strong electrolyte?", "options": ["NaCl solution", "Glucose solution", "Acetic acid", "Ethanol"], "answer": "NaCl solution"}]
    },
    {
        "title": "CAIE O-Level Physics (5054) Master Syllabus Vault",
        "sector": "O-Level / IGCSE",
        "subject": "Physics",
        "sources_count": 52,
        "summary": "Comprehensive O-Level Physics guide covering General Physics, Thermal Physics, Waves, Electromagnetism, and Atomic Physics.",
        "key_concepts": ["Kinematics", "Electromagnetic Induction", "Lenz's Law", "Radioactivity", "Refraction"],
        "flashcards": [
            {"front": "What does Faraday's Law state?", "back": "The magnitude of induced EMF is directly proportional to the rate of change of magnetic flux linkage."}
        ],
        "mcq": [{"q": "What is the SI unit of electrical resistance?", "options": ["Ohm (Ω)", "Volt (V)", "Ampere (A)", "Watt (W)"], "answer": "Ohm (Ω)"}]
    },
    {
        "title": "CAIE O-Level Chemistry (5070) Complete Notes & Past Papers",
        "sector": "O-Level / IGCSE",
        "subject": "Chemistry",
        "sources_count": 45,
        "summary": "Full compilation of Mole Concept, Reaction Rates, Electrolysis, Organic Chemistry reactions, and Qualitative Analysis.",
        "key_concepts": ["Mole Calculations", "Electrolysis", "Exothermic/Endothermic", "Alkanes & Alkenes"],
        "flashcards": [
            {"front": "Define Avogadro's Constant.", "back": "6.02 × 10^23 particles in one mole of any substance."}
        ],
        "mcq": [{"q": "Which gas turns limewater milky?", "options": ["Carbon Dioxide", "Oxygen", "Hydrogen", "Ammonia"], "answer": "Carbon Dioxide"}]
    },
    {
        "title": "CAIE A-Level Pure Mathematics (9709) Calculus & Algebra",
        "sector": "A-Level",
        "subject": "Mathematics",
        "sources_count": 40,
        "summary": "Advanced differentiation, integration, series expansion, logarithms, and coordinate geometry for Paper 1 and Paper 3.",
        "key_concepts": ["Chain Rule", "Integration by Parts", "Binomial Expansion", "Parametric Equations"],
        "flashcards": [
            {"front": "What is the derivative of ln(x)?", "back": "1 / x"},
            {"front": "What is the integral of e^(ax)?", "back": "(1/a) * e^(ax) + C"}
        ],
        "mcq": [{"q": "What is the derivative of sin(x)?", "options": ["cos(x)", "-cos(x)", "sin(x)", "-sin(x)"], "answer": "cos(x)"}]
    },
    {
        "title": "MBBS / Pre-Med Human Anatomy & Systems Physiology",
        "sector": "MBBS / Medical",
        "subject": "Medical Science",
        "sources_count": 65,
        "summary": "Detailed medical study set covering cardiovascular hemodynamics, neuroanatomy, renal physiology, and histology basics.",
        "key_concepts": ["Action Potential", "Cardiac Cycle", "Nephron Filtration", "Autonomic Nervous System"],
        "flashcards": [
            {"front": "What is the primary pacemaker of the heart?", "back": "Sinoatrial (SA) node"},
            {"front": "Where does blood go after leaving the right ventricle?", "back": "Pulmonary artery to the lungs"}
        ],
        "mcq": [{"q": "Which blood cells are responsible for oxygen transport?", "options": ["Erythrocytes (RBCs)", "Leukocytes (WBCs)", "Platelets", "Plasma proteins"], "answer": "Erythrocytes (RBCs)"}]
    },
    {
        "title": "FCPS Part 1 & Part 2 Clinical Medicine & Surgery Residency Vault",
        "sector": "FCPS / Postgraduate Medical",
        "subject": "Advanced Medicine & Surgery",
        "sources_count": 85,
        "summary": "Specialized postgraduate medical reference covering CPSP exam guidelines, internal medicine protocols, surgical critical care, pathophysiology, and diagnostic algorithms.",
        "key_concepts": ["Advanced Life Support (ACLS)", "Sepsis Management", "Endocrinology Disorders", "Pre-operative Risk Assessment"],
        "flashcards": [
            {"front": "What is the first-line pharmacological treatment for acute anaphylactic shock?", "back": "Intramuscular Epinephrine (Adrenaline) 0.5 mg (1:1000)."},
            {"front": "What triad characterizes Wernicke's encephalopathy?", "back": "Ophthalmoplegia, ataxia, and confusion."}
        ],
        "mcq": [{"q": "What is the most common cause of community-acquired pneumonia?", "options": ["Streptococcus pneumoniae", "Mycoplasma pneumoniae", "Legionella pneumophila", "Haemophilus influenzae"], "answer": "Streptococcus pneumoniae"}]
    },
    {
        "title": "Business Studies & Principles of Accounting (IGCSE / O-Level & BBA)",
        "sector": "Business Studies & Economics",
        "subject": "Business",
        "sources_count": 35,
        "summary": "Double-entry bookkeeping, financial statements, marketing mix (4Ps), break-even analysis, and human resource management.",
        "key_concepts": ["Balance Sheet", "Break-Even Point", "Market Segmentation", "Cash Flow Forecast"],
        "flashcards": [
            {"front": "What is the accounting equation?", "back": "Assets = Capital + Liabilities"},
            {"front": "What are the 4 Ps of Marketing?", "back": "Product, Price, Place, Promotion"}
        ],
        "mcq": [{"q": "Which of the following is a current asset?", "options": ["Inventory", "Bank Loan", "Machinery", "Land"], "answer": "Inventory"}]
    },
    {
        "title": "University Computer Science: Data Structures & Algorithms",
        "sector": "University & Engineering",
        "subject": "Computer Science",
        "sources_count": 50,
        "summary": "Advanced computer science reference covering Big-O notation, sorting algorithms, hash tables, binary search trees, and graph traversal.",
        "key_concepts": ["Time Complexity", "Depth-First Search", "Binary Search", "Dynamic Programming", "Hash Collisions"],
        "flashcards": [
            {"front": "What is the worst-case time complexity of Merge Sort?", "back": "O(n log n)"},
            {"front": "What data structure uses LIFO (Last In, First Out)?", "back": "Stack"}
        ],
        "mcq": [{"q": "Which data structure is best suited for implementing a breadth-first search?", "options": ["Queue", "Stack", "Array", "Tree"], "answer": "Queue"}]
    },
    {
        "title": "Master's Degree (MSc / MS) Advanced Artificial Intelligence & Machine Learning",
        "sector": "Master's / Postgraduate",
        "subject": "Computer Science & AI",
        "sources_count": 75,
        "summary": "Postgraduate reference covering Deep Neural Networks, Transformer Architectures, Reinforcement Learning, and Bayesian Statistics.",
        "key_concepts": ["Attention Mechanism", "Gradient Descent", "Markov Decision Processes", "Overfitting & Regularization"],
        "flashcards": [
            {"front": "What is the core innovation of the Transformer architecture?", "back": "Self-attention mechanisms replacing recurrent layers for parallel processing."},
            {"front": "Define Overfitting.", "back": "When a model learns the training data too well, capturing noise and failing to generalize on unseen data."}
        ],
        "mcq": [{"q": "Which activation function helps mitigate vanishing gradients in deep networks?", "options": ["ReLU", "Sigmoid", "Tanh", "Step function"], "answer": "ReLU"}]
    },
    {
        "title": "PhD / Doctoral Level Quantum Information Science & Theoretical Physics",
        "sector": "PhD / Doctorate",
        "subject": "Theoretical Physics",
        "sources_count": 90,
        "summary": "Advanced doctoral research notes on Quantum Entanglement, Density Matrix Formalism, Quantum Error Correction, and EPR Paradox.",
        "key_concepts": ["Qubit Superposition", "Bell States", "Quantum Teleportation", "decoherence", "Density Operator"],
        "flashcards": [
            {"front": "What does a Bell state represent?", "back": "Maximally entangled quantum states of two qubits."},
            {"front": "What is Quantum Decoherence?", "back": "The loss of quantum coherence causing a quantum system to behave like a classical system due to environment interaction."}
        ],
        "mcq": [{"q": "Which theorem states that an arbitrary unknown quantum state cannot be cloned?", "options": ["No-cloning theorem", "Bell's theorem", "Ehrenfest's theorem", "Bloch theorem"], "answer": "No-cloning theorem"}]
    },
    {
        "title": "Professional Certifications: ACCA & CFA Level 1 Financial Reporting",
        "sector": "Professional & Certifications",
        "subject": "Finance & Accounting",
        "sources_count": 45,
        "summary": "Corporate finance valuation metrics, IFRS standards, cash flow statements, portfolio management, and quantitative methods.",
        "key_concepts": ["Net Present Value (NPV)", "Capital Asset Pricing Model (CAPM)", "IFRS 15 Revenue", "EBITDA"],
        "flashcards": [
            {"front": "What does CAPM calculate?", "back": "Expected return of an asset based on its systematic risk (beta) and expected market return."},
            {"front": "What is EBITDA?", "back": "Earnings Before Interest, Taxes, Depreciation, and Amortization."}
        ],
        "mcq": [{"q": "Which financial statement reports a company's financial position at a specific point in time?", "options": ["Balance Sheet", "Income Statement", "Cash Flow Statement", "Statement of Changes in Equity"], "answer": "Balance Sheet"}]
    },
    {
        "title": "Law & Jurisprudence (LLB / LLM): Constitutional & Contract Law",
        "sector": "Law & Jurisprudence",
        "subject": "Legal Studies",
        "sources_count": 55,
        "summary": "Precedent analysis, offer and acceptance doctrine, consideration, tort law negligence, and constitutional rights frameworks.",
        "key_concepts": ["Elements of a Contract", "Duty of Care", "Judicial Review", "Breach of Contract Remedies"],
        "flashcards": [
            {"front": "What are the core elements of a binding contract?", "back": "Offer, acceptance, consideration, intention to create legal relations, and capacity."},
            {"front": "What case established the modern tort law 'neighbor principle'?", "back": "Donoghue v Stevenson [1932]"}
        ],
        "mcq": [{"q": "What standard of proof is required in criminal law cases?", "options": ["Beyond a reasonable doubt", "Preponderance of the evidence", "Clear and convincing evidence", "Balance of probabilities"], "answer": "Beyond a reasonable doubt"}]
    }
]

# --- Lightweight JSON Functions ---
def export_lightweight_json(result_data):
    compressed_payload = {
        "version": "1.0",
        "topic": result_data.get("topic", "General Study Set"),
        "subject": result_data.get("subject", "General"),
        "summary": result_data.get("summary", ""),
        "detailed_notes": result_data.get("detailed_notes", ""),
        "key_concepts": result_data.get("key_concepts", []),
        "flashcards": result_data.get("flashcards", []),
        "quiz": result_data.get("mcq", [])
    }
    return json.dumps(compressed_payload, indent=2, ensure_ascii=False)

def import_lightweight_json(uploaded_file):
    try:
        content = uploaded_file.read().decode("utf-8")
        data = json.loads(content)
        if "topic" not in data or "flashcards" not in data:
            return None, "Invalid file format: Missing StudyStack schema keys."
        return data, None
    except Exception as e:
        return None, f"Failed to parse JSON file: {str(e)}"

def load_icon():
    try:
        return Image.open(FAVICON)
    except Exception:
        return "📚"

st.set_page_config(page_title="StudyStack", page_icon=load_icon(), layout="wide")

MAX_PDF_MB = 20
MAX_PDF_PAGES = 30
MAX_RESTORE_MB = 2

DEFAULTS = {
    "analysis_result": None,
    "file_key": None,
    "source": None,
    "chat_history": [],
    "mcq": None,
    "study_minutes": 0,
    "sessions_completed": 0,
    "focus_timer_state": "idle",
    "focus_timer_end": 0,
    "focus_timer_remaining": 0,
    "focus_timer_mins": 25,
    "voice_gen": 0,
    "user_name": "",
    "name_asked": False,
    "auth_mode": None,
    "auth_user": None,
    "upload_gen": 0,
    "current_set_id": None,
    "lib_cache": None,
    "save_note": "",
    "confirm_delete": None,
    "social": None,
    "flash": "",
    "friend_msg": None,
    "confirm_remove": None,
    "revision_reveal": None,
      "quiz_log": {},
    "tf": None,
    "tf_log": [],
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = copy.deepcopy(v)

def clean_name(raw):
    return re.sub(r"[^\w\s'’.-]", "", raw or "", flags=re.UNICODE).strip()[:30]

def reset_session():
    gen = st.session_state.upload_gen + 1
    for k, v in DEFAULTS.items():
        st.session_state[k] = copy.deepcopy(v)
    st.session_state.upload_gen = gen

def show_logo(path, width, fallback):
    if path.exists():
        st.image(str(path), width=width)
    else:
        st.markdown(fallback)

# ---------- TOP BAR ----------
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
        display_name = st.session_state.user_name
        if not display_name and _mode == "user" and st.session_state.auth_user:
            display_name = clean_name(st.session_state.auth_user['name'])
        if display_name:
            st.markdown(f"👤 **{display_name}**")
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

[class*="st-key-card"]{
  background:linear-gradient(145deg,var(--glass2),var(--glass));
  backdrop-filter:blur(22px) saturate(160%);-webkit-backdrop-filter:blur(22px) saturate(160%);
  border:1px solid var(--border)!important;border-radius:24px!important;
  box-shadow:var(--shadow),0 0 0 1px var(--glow),inset 0 1px 0 rgba(255,255,255,0.35);
  padding:1.4rem 1.6rem!important;margin-bottom:1.1rem;
}

.stTabs [data-baseweb="tab-list"]{gap:8px;padding:6px;background:var(--glass);border:1px solid var(--border);
  border-radius:999px;backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);box-shadow:var(--shadow);width:fit-content;max-width:100%;overflow-x:auto;}
.stTabs [data-baseweb="tab"]{background:transparent;border-radius:999px;padding:8px 18px;height:auto;}
.stTabs [data-baseweb="tab"] p{color:var(--muted);font-weight:600;}
.stTabs [aria-selected="true"]{background:linear-gradient(135deg,#7c5cff,#00c8ff)!important;box-shadow:0 0 22px var(--glow);}
.stTabs [aria-selected="true"] p{color:#fff!important;}
.stTabs [data-baseweb="tab-highlight"],.stTabs [data-baseweb="tab-border"]{display:none;}

[data-testid="stExpander"]{background:var(--glass);border:1px solid var(--border)!important;border-radius:16px!important;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);}
[data-testid="stExpander"] summary{font-weight:600;}

.stTextArea textarea, .stTextInput input, .stNumberInput input, [data-baseweb="input"] input, [data-baseweb="textarea"] textarea {
    background: var(--input-bg) !important;
    color: var(--text) !important;
    -webkit-text-fill-color: var(--text) !important;
    border: 1px solid var(--border) !important;
    border-radius: 14px !important;
    caret-color: var(--text) !important;
}

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

.st-key-dark_mode *{white-space:nowrap;}
.st-key-card_login [data-testid="stImage"]{display:flex;justify-content:center;}

[data-testid="stForm"]{border:none!important;padding:0!important;background:transparent!important;}
[data-testid="stChatMessage"]{background:var(--glass);border:1px solid var(--border);border-radius:18px;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);}

[data-testid="stGraphVizChart"]{display:flex;justify-content:center;}
[data-testid="stGraphVizChart"] svg{margin:0 auto;max-width:100%;height:auto;}
</style>
"""
css = CSS
for k, v in THEMES[dark].items():
    css = css.replace(f"__{k}__", v)
st.markdown(css, unsafe_allow_html=True)

st.markdown("""
<div style="text-align: center; margin-top: 0.5rem; margin-bottom: 1.5rem;">
    <h1 style="font-family: 'Plus Jakarta Sans', sans-serif; font-size: 2.5rem; font-weight: 800; 
               background: -webkit-linear-gradient(45deg, #7c5cff, #00c8ff); 
               -webkit-background-clip: text; -webkit-text-fill-color: transparent; 
               margin: 0; letter-spacing: -0.03em;">
        Empowering independent learning. Snap it. Stack it. Master it.
    </h1>
</div>
""", unsafe_allow_html=True)

def card(name):
    return st.container(border=True, key=f"card_{name}")

def need_upload(tab_name):
    with card(f"empty_{tab_name}"):
        st.info("Upload a screenshot or PDF in the Capture tab first, or open a set from My Library.")

def start_user_session(user):
    st.session_state.auth_mode = "user"
    st.session_state.auth_user = user
    st.session_state.user_name = clean_name(user["name"])
    st.session_state.name_asked = bool(st.session_state.user_name)
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

if st.session_state.flash:
    st.toast(st.session_state.flash)
    st.session_state.flash = ""

def get_context(res):
    parts = [str(res.get("summary", "")), str(res.get("detailed_notes", "")), str(res.get("raw_text", ""))]
    return "\n\n".join(p for p in parts if p.strip())[:20000]

def fix_latex(s):
    s = str(s)
    fixes = {
        "\text": r"\text", "\times": r"\times", "\theta": r"\theta", "\tau": r"\tau", "\frac": r"\frac",
        "\beta": r"\beta", "\bar": r"\bar", "\rho": r"\rho", "\rightarrow": r"\rightarrow", "\alpha": r"\alpha",
        "\approx": r"\approx", "\vec": r"\vec",
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
    if st.session_state.auth_mode != "user":
        return
    pts = award_points(kind)
    st.session_state.social = None
    if pts > 0:
        msg = f"+{pts} points 🔥"
        if immediate:
            st.toast(msg)
        else:
            st.session_state.flash = msg

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

def save_result(result, key, source=None):
    if "error" in result:
        st.error(f"Analysis failed: {result['error']}")
        return
    clean = clean_result(result)
    if clean is None:
        st.error("The AI reply didn't contain study material. Please try again.")
        return
    st.session_state.analysis_result = clean
    st.session_state.file_key = key
    st.session_state.source = source
    st.session_state.chat_history = []
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
            if source:
                if save_source(set_id, source):
                    st.session_state.save_note += " (The original file couldn't be stored.)"
        award("analyze", immediate=True)
    else:
        st.session_state.save_note = "Guest mode: nothing is saved. Use the 📚 My Library tab to download this set."

def show_done():
    st.success("Analysis complete. Open the other tabs.")
    note = st.session_state.save_note
    if note:
        (st.warning if note.startswith("⚠️") else st.caption)(note)

def show_source(src):
    if not src:
        return
    raw = source_bytes(src)
    if src.get("kind") == "image":
        if raw:
            st.image(raw, caption=src.get("name") or "Uploaded screenshot", width=400)
        else:
            st.caption("The original screenshot isn't available for this set.")
    else:
        pages = f" · pages {src['page_range']}" if src.get("page_range") else ""
        st.write(f"📄 **{src.get('name') or 'PDF'}**{pages}")
        if raw:
            st.download_button("⬇️ Download the PDF pages", raw, file_name=src.get("name") or "study.pdf",
                               mime="application/pdf", key="dl_source_pdf")
        else:
            st.caption("This PDF was too large to store, so only its name and page range are kept.")

def persist_chat():
    sid = st.session_state.current_set_id
    if st.session_state.auth_mode == "user" and sid:
        update_chat(sid, st.session_state.chat_history)

def open_saved(set_id, title=""):
    data, err = load_set(set_id)
    if err:
        st.error(err)
        return
    st.session_state.analysis_result = data["result"]
    st.session_state.chat_history = data["chat"]
    st.session_state.source = load_source(set_id)
    st.session_state.revision_reveal = None
    st.session_state.mcq = None
    st.session_state.current_set_id = set_id
    st.session_state.file_key = ("saved", set_id)
    st.session_state.upload_gen += 1
    st.session_state.save_note = ""
    st.session_state.flash = f"Opened “{title}”. Check the other tabs." if title else "Set opened. Check the other tabs."
    st.rerun()

def render_revision(result, set_id=None, namespace="current"):
    scope_key = f"speech_revision_{namespace}"
    with st.container(key=scope_key):
        st.write(f"**Subject:** {result.get('subject')} | **Topic:** {result.get('topic')}")
        notes = fix_latex(result.get("detailed_notes") or "No notes generated.")
        with st.expander("📖 Detailed study notes", expanded=True):
            read_aloud(notes, key=f"tts_notes_{namespace}", scope=scope_key)
            st.markdown(notes)
        st.download_button("⬇️ Download notes as TXT", notes, file_name="study_notes.txt", key=f"dl_notes_{namespace}")
        st.write("---")
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

# ---------- Metacognition Engine helpers ----------
CONF_LEVELS = ["Sure", "Unsure", "Guess"]
MASTERY_COLORS = {"green": "#2ecc71", "amber": "#f5a623", "red": "#e74c3c", "grey": "#8a93b2"}
MASTERY_LABELS = {"green": "strong", "amber": "shaky", "red": "weak", "grey": "not tested yet"}
HINT_LABELS = {1: "💬 Nudge", 2: "💡 Clue", 3: "🪜 Worked step", 4: "✅ Full answer"}

def tkey(topic):
    return str(topic or "").strip()

def concept_for_text(text, concepts):
    """Match a flashcard to the key concept whose words appear most in it."""
    t = str(text).lower()
    best, best_score = None, 0.0
    for c in concepts or []:
        words = [w for w in re.findall(r"\w+", str(c).lower()) if len(w) > 3]
        if not words:
            continue
        score = sum(1 for w in words if w in t) / len(words)
        if score > best_score:
            best, best_score = str(c).strip(), score
    return best if best_score >= 0.5 else None

def mastery_status(topic, concept):
    """green / amber / red / grey for one concept, from this session's quiz log."""
    concept = str(concept).strip()
    entries = [e for e in st.session_state.quiz_log.get(tkey(topic), []) if e.get("concept") == concept]
    if not entries:
        return "grey"
    acc = sum(1 for e in entries if e["ok"]) / len(entries)
    level = 2 if acc >= 0.8 else (1 if acc >= 0.5 else 0)
    if any(e["conf"] == "Sure" and not e["ok"] for e in entries):
        level = max(0, level - 1)   # a confident mistake pulls the colour down
    return ["red", "amber", "green"][level]

def confident_mistakes(topic):
    """Questions whose latest answer was 'Sure' but wrong."""
    last = {}
    for e in st.session_state.quiz_log.get(tkey(topic), []):
        last[e["q"]] = e
    return {q for q, e in last.items() if e["conf"] == "Sure" and not e["ok"]}

def calibration_rows(log):
    rows = []
    for level in CONF_LEVELS:
        items = [e for e in log if e["conf"] == level]
        if items:
            right = sum(1 for e in items if e["ok"])
            rows.append({"You said": level, "Questions": len(items), "Right": right,
                         "Accuracy": f"{round(100 * right / len(items))}%"})
    return rows

def show_calibration(log):
    if not log:
        return
    st.subheader("🎯 Know What You Know")
    sure = [e for e in log if e["conf"] == "Sure"]
    if sure:
        right = sum(1 for e in sure if e["ok"])
        pct = round(100 * right / len(sure))
        st.markdown(f"When you said **Sure**, you were right **{pct}%** of the time ({right} of {len(sure)}).")
        if pct >= 85:
            st.success("Your confidence matches your knowledge. Well calibrated!")
        elif pct >= 60:
            st.warning("Some of your “Sure” answers were wrong. Double-check the ones you feel certain about.")
        else:
            st.error("You were often confident and wrong. Those topics need a second look.")
    else:
        st.caption("You never picked “Sure” this round.")
    st.table(pd.DataFrame(calibration_rows(log)))
    bad = [e for e in sure if not e["ok"]]
    if bad:
        st.markdown("**Confident mistakes** (they come back first next time):")
        for e in bad:
            st.markdown(f"- {e['q']} → correct answer: **{e['answer']}**")

def reliance_meter():
    log = st.session_state.tf_log
    if not log:
        return
    n = len(log)
    tried = sum(1 for e in log if e["tried"])
    per_q = [min(1.0 if e["tried"] else 0.5, (4 - e["level"]) / 3) for e in log]
    independence = round(100 * sum(per_q) / n)
    avg_level = sum(e["level"] for e in log) / n
    st.markdown("**🧭 AI Reliance Meter**")
    st.progress(independence / 100, text=f"Independence: {independence}%")
    st.caption(f"You tried first on {tried} of {n} question(s). Average help level: {avg_level:.1f} of 4 "
               "(1 = nudge, 4 = full answer).")

def think_first_ui(context, name, lang):
    tf = st.session_state.tf
    if tf is None:
        with st.form("tf_q", clear_on_submit=True):
            q = st.text_input("What do you want to understand or solve?", placeholder="Type your question")
            go = st.form_submit_button("Start")
        if go and q.strip():
            st.session_state.tf = {"q": q.strip(), "attempt": None, "level": 0, "tried": False}
            st.rerun()
        reliance_meter()
        return

    st.markdown(f"**Your question:** {tf['q']}")

    if tf["attempt"] is None:
        st.info("🧠 Your turn first! Write what you think, even if you're unsure. The tutor builds on your attempt.")
        with st.form("tf_attempt", clear_on_submit=True):
            a = st.text_area("My attempt", height=100)
            c1, c2, _ = st.columns([1.3, 1.5, 3])
            sub = c1.form_submit_button("Submit attempt")
            skip = c2.form_submit_button("I don't know yet")
        if sub and not a.strip():
            st.warning("Write something first, or press “I don't know yet”.")
        elif sub or skip:
            tried = bool(sub)
            attempt = a.strip() if tried else "(The student has no idea yet.)"
            with st.spinner("Thinking..."):
                reply = think_first_reply(tf["q"], attempt, 1, context, st.session_state.chat_history, name, lang)
            tf["attempt"], tf["level"], tf["tried"] = attempt, 1, tried
            st.session_state.tf_log.append({"tried": tried, "level": 1})
            shown = attempt if tried else "*(no idea yet)*"
            st.session_state.chat_history += [
                {"role": "user", "content": f"**Question:** {tf['q']}\n\n**My attempt:** {shown}"},
                {"role": "assistant", "content": f"{HINT_LABELS[1]}\n\n{reply}"},
            ]
            persist_chat()
            award("tutor")
            st.rerun()
        reliance_meter()
        return

    level = tf["level"]
    n_log = len(st.session_state.tf_log)
    st.caption(f"Help so far: {HINT_LABELS[level]} (level {level} of 4)")
    c1, c2, _ = st.columns([2.4, 1.6, 2])
    if level < 4 and c1.button(f"Need more help → {HINT_LABELS[level + 1]}", key=f"tf_more_{n_log}_{level}"):
        new = level + 1
        with st.spinner("Thinking..."):
            reply = think_first_reply(tf["q"], tf["attempt"], new, context, st.session_state.chat_history, name, lang)
        tf["level"] = new
        st.session_state.tf_log[-1]["level"] = new
        st.session_state.chat_history += [
            {"role": "user", "content": "*(asked for more help)*"},
            {"role": "assistant", "content": f"{HINT_LABELS[new]}\n\n{reply}"},
        ]
        persist_chat()
        st.rerun()
    if c2.button("➕ New question", key=f"tf_new_{n_log}_{level}"):
        st.session_state.tf = None
        st.rerun()
    reliance_meter()

def get_distractors(cards):
    """One AI call per set: wrong answers in the same form as the right one. Cached for the session."""
    cache = st.session_state.setdefault("distractor_cache", {})
    key = str(hash(tuple((str(c["front"]), str(c["back"])) for c in cards)))
    if key in cache:
        return cache[key]
    with st.spinner("Writing fair answer choices..."):
        found = make_distractors(cards)
    if found:
        cache[key] = found
    return found

def build_mcq(flashcards):
    cards = [c for c in flashcards if str(c.get("front") or "").strip() and str(c.get("back") or "").strip()]
    backs = sorted({str(c["back"]).strip() for c in cards})
    distractors = get_distractors(cards) if cards else {}
    questions = []
    for idx, c in enumerate(cards):
        correct = str(c["back"]).strip()
        wrong = []
        for w in distractors.get(idx, []):
            w = str(w).strip()
            if w and w.lower() != correct.lower() and w not in wrong:
                wrong.append(w)
        if len(wrong) < 3:
            # fallback: other cards' answers, preferring ones of similar length
            others = [b for b in backs if b != correct and b not in wrong]
            others.sort(key=lambda b: abs(len(b) - len(correct)))
            pool = others[:6]
            random.shuffle(pool)
            wrong += pool[: 3 - len(wrong)]
        options = [correct] + wrong[:3]
        if len(options) < 2:
            continue
        random.shuffle(options)
        questions.append({"q": str(c["front"]).strip(), "options": options, "answer": correct})
    random.shuffle(questions)
    return questions

def mcq_quiz(flashcards, concepts, topic):
    topic = tkey(topic)
    if st.session_state.mcq is None:
        qs = build_mcq(flashcards)
        for item in qs:
            item["concept"] = concept_for_text(item["q"] + " " + item["answer"], concepts)
        redo = confident_mistakes(topic)
        qs.sort(key=lambda item: 0 if item["q"] in redo else 1)   # confident mistakes come first
        st.session_state.mcq = {
            "qs": qs,
            "i": 0,
            "score": 0,
            "checked": False,
            "correct": False,
            "awarded": False,
            "run": random.randint(0, 10**9),
            "log": [],
            "redo": sum(1 for item in qs if item["q"] in redo),
        }
    m = st.session_state.mcq
    qs = m["qs"]
    if len(qs) < 1:
        st.info("Not enough flashcards to build a multiple-choice quiz from this material.")
        return
    if m["i"] >= len(qs):
        st.success(f"🎉 Finished! Your score: {m['score']}/{len(qs)}")
        show_calibration(m["log"])
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
    if m["i"] < m["redo"]:
        st.caption("🔁 You were Sure but wrong on this one before, so it's back early.")

    st.subheader(q["q"])
    pick = st.radio("Choose one:", q["options"], index=None, key=f"mcq_pick_{m['run']}_{m['i']}", disabled=m["checked"])
    conf = st.radio("How sure are you?", CONF_LEVELS, index=None, horizontal=True,
                    key=f"mcq_conf_{m['run']}_{m['i']}", disabled=m["checked"])
    read_aloud(quiz_reading_text(q, m["checked"], m["correct"]),
               key=f"tts_mcq_{m['run']}_{m['i']}", scope="card_quiz")
    if not m["checked"]:
        if st.button("Check answer", key="mcq_check"):
            if pick is None:
                st.warning("Pick an answer first.")
            elif conf is None:
                st.warning("Say how sure you are first: Sure, Unsure or Guess.")
            else:
                m["checked"] = True
                m["correct"] = (pick == q["answer"])
                if m["correct"]:
                    m["score"] += 1
                entry = {"q": q["q"], "answer": q["answer"], "concept": q.get("concept"),
                         "conf": conf, "ok": m["correct"]}
                m["log"].append(entry)
                st.session_state.quiz_log.setdefault(topic, []).append(entry)
                st.rerun()
    else:
        if m["correct"]:
            st.success("✅ Correct!")
        else:
            st.error(f"❌ Not quite. The correct answer is: {q['answer']}")
            if conf == "Sure":
                st.warning("⚠️ That was a confident mistake. It will come back sooner.")
        label = "Next question ➡️" if m["i"] + 1 < len(qs) else "See results 🏁"
        if st.button(label, key="mcq_next"):
            m["i"] += 1
            m["checked"] = False
            st.rerun()

st.caption("Turn screenshots and PDFs into notes, flashcards, a concept map, an AI tutor and a focus hub.")

# --- ALL TABS (Original tabs + Explore Library) ---
tab_home, tab_cap, tab_lib, tab_explore, tab_prog, tab_graph, tab_chat, tab_focus, tab_quiz = st.tabs(
    ["🏠 Home", "📸 Capture", "📚 My Library", "🌍 Explore Library", "🏆 Progress", "🕸️ Knowledge Graph",
     "💬 AI Tutor", "⏱️ Focus Hub", "🧠 Metacognition Quiz"]
)

# --- HOME ---
with tab_home:
    with card("home"):
        st.header("Welcome to StudyStack")
        st.write("Upload a screenshot or a PDF of a lecture, syllabus or chat. StudyStack extracts the text, writes notes, "
                 "makes flashcards, draws a concept map, grades your explanations, tutors you by text or voice, "
                 "and tracks your daily study focus time.")
        
        st.markdown("---")
        st.link_button(
            "🎥 Watch the Quick Tutorial", 
            "https://youtu.be/yfezlcTELHQ", 
            use_container_width=True
        )
        st.caption("New here? Watch a quick silent walkthrough of how to use StudyStack.")
        st.markdown("---")

        if st.session_state.auth_mode == "guest":
            st.info("You're in guest mode, so nothing is saved on our side. Use **Sign in** (top right) to create an account, "
                    "keep your streak and compete with friends.")

# --- CAPTURE ---
with tab_cap:
    with card("upload"):
        st.header("📸 Capture")

        uploaded_files = st.file_uploader("Upload screenshots or PDFs",
                                          type=["png", "jpg", "jpeg", "pdf"],
                                          accept_multiple_files=True,
                                          key=f"uploader_{st.session_state.upload_gen}")

        if uploaded_files:
            valid_files = []
            pdf_selections = {}
            estimated_pages = 0
            has_error = False

            for f in uploaded_files:
                if f.name.lower().endswith(".pdf"):
                    data = f.getvalue()
                    pages = pdf_page_count(data) or 1
                    if f.size > MAX_PDF_MB * 1024 * 1024:
                        st.error(f"❌ {f.name} is larger than {MAX_PDF_MB} MB. Skipping.")
                        has_error = True
                    else:
                        fid = f"{f.name}_{f.size}"
                        if pages > 1:
                            c1, c2, _ = st.columns([1, 1, 3])
                            start = int(c1.number_input(f"From page ({f.name})", min_value=1, max_value=pages, value=1, step=1, key=f"from_{fid}"))
                            end = int(c2.number_input(f"To page ({f.name})", min_value=1, max_value=pages,
                                                      value=min(pages, MAX_PDF_PAGES), step=1, key=f"to_{fid}"))
                            
                            if end < start:
                                st.error(f"'To page' must be after 'From page' for {f.name}.")
                                has_error = True
                            elif (end - start + 1) > MAX_PDF_PAGES:
                                st.warning(f"Please pick at most {MAX_PDF_PAGES} pages for {f.name}.")
                                has_error = True
                            else:
                                pdf_selections[fid] = (start, end)
                                estimated_pages += (end - start + 1)
                                valid_files.append((f, data, pages))
                        else:
                            pdf_selections[fid] = (1, 1)
                            estimated_pages += 1
                            valid_files.append((f, data, pages))
                else:
                    estimated_pages += 1
                    valid_files.append((f, f.getvalue(), 1))

            if valid_files and not has_error:
                est_seconds = estimated_pages * 2
                est_min = est_seconds // 60
                est_sec = est_seconds % 60
                time_str = f"{est_min} mins {est_sec} secs" if est_min > 0 else f"{est_sec} seconds"

                st.info(f"📚 **{len(valid_files)} file(s) ready.** Estimated analysis time for **{estimated_pages} pages**: **{time_str}**. Grab a coffee! ☕")

                if st.button("🚀 Start Analysis"):
                    progress_bar = st.progress(0, text="Initializing AI...")
                    file_count = len(valid_files)

                    for idx, (f, data, pages) in enumerate(valid_files):
                        progress_val = int((idx / file_count) * 100)
                        progress_bar.progress(progress_val, text=f"Analyzing {f.name} ({idx+1}/{file_count})...")

                        if f.name.lower().endswith(".pdf"):
                            fid = f"{f.name}_{f.size}"
                            start, end = pdf_selections[fid]
                            sliced = pdf_slice(data, start, end)
                            result = analyze_pdf(sliced)
                            save_result(result, ("pdf", f.name, f.size, start, end), source=make_pdf_source(f.name, start, end, sliced))
                        else:
                            result = analyze_image(f)
                            save_result(result, ("img", f.name, f.size), source=make_image_source(f))

                    progress_bar.progress(100, text="Analysis Complete!")
                    st.success("🎉 All selected pages have been analyzed!")
                    time.sleep(1)
                    st.session_state.upload_gen += 1
                    st.rerun()

        elif st.session_state.source:
            st.caption("📎 Original upload for the open set:")
            show_source(st.session_state.source)

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
                st.info("Nothing saved yet. Analyze a screenshot or PDF and it will appear here.")
            else:
                query = st.text_input("Search your library", key="library_search", placeholder="Search saved titles or notes")
                matched = search_sets(lib["rows"], query)
                st.caption(f"Showing {len(matched)} of {len(lib['rows'])} sets.")
                
                if not matched:
                    st.info("No matching resources.")
                else:
                    subject_groups = group_sets_by_subject(matched)
                    subject_tabs = st.tabs(list(subject_groups.keys()))
                    
                    for subject_tab, subject_rows in zip(subject_tabs, subject_groups.values()):
                        with subject_tab:
                            if not subject_rows:
                                st.info("No resources in this subject.")
                            else:
                                cols = st.columns(3)
                                for i, row in enumerate(subject_rows):
                                    with cols[i % 3]:
                                        with st.container(border=True):
                                            st.subheader(row['title'])
                                            st.caption(f"📅 {str(row['created_at'])[:10]}")
                                            st.caption(f"📚 {row.get('subject', 'General')}")
                                            
                                            c1, c2 = st.columns(2)
                                            if c1.button("Open", key=f"open_{row['id']}", use_container_width=True):
                                                open_saved(row["id"], row["title"])
                                            if c2.button("Delete", key=f"del_{row['id']}", use_container_width=True):
                                                st.session_state.confirm_delete = row["id"]
                                                st.rerun()

                                            if st.session_state.confirm_delete == row["id"]:
                                                st.warning(f"Delete “{row['title']}”?")
                                                y, n = st.columns(2)
                                                if y.button("Yes", key=f"yes_{row['id']}"):
                                                    delete_set(row["id"])
                                                    st.session_state.confirm_delete = None
                                                    st.session_state.lib_cache = None
                                                    st.rerun()
                                                if n.button("No", key=f"no_{row['id']}"):
                                                    st.session_state.confirm_delete = None
                                                    st.rerun()
        else:
            st.write("As a guest, nothing is stored on our side. Download your study set to keep it.")

        st.divider()
        st.subheader("💾 Storage & Offline Vault")
        c1, c2 = st.columns(2)
        with c1:
            if res is not None:
                json_data = export_lightweight_json(res)
                safe_filename = f"{res.get('topic', 'studyset').replace(' ', '_')}_vault.json"
                st.download_button("⬇️ Export Vault (JSON)", data=json_data, file_name=safe_filename, mime="application/json")
            else:
                st.caption("Open a set to export.")
        with c2:
            uploaded_vault = st.file_uploader("📂 Load Saved Vault", type=["json"], key="json_vault_loader")
            if uploaded_vault is not None:
                if st.button("🚀 Load This Vault", key="load_vault_btn"):
                    loaded_data, err = import_lightweight_json(uploaded_vault)
                    if err:
                        st.error(err)
                    else:
                        st.session_state.analysis_result = loaded_data
                        st.success(f"Loaded: {loaded_data.get('topic')}")
                        time.sleep(1)
                        st.rerun()

# --- EXPLORE LIBRARY (Multi-Sector Public Study Hub from Nursery to FCPS & PhD) ---
with tab_explore:
    with card("explore_lib"):
        st.header("🌍 Explore Multi-Sector Library")
        st.caption("Browse sample study sets spanning Nursery/KG Juniors, Matriculation, Intermediate Boards, O/A Levels, MBBS, FCPS, Undergraduate, Master's, PhD, Professional Certifications, and Law.")
        
        sector_filter = st.selectbox(
            "Filter by Educational Sector", 
            [
                "All Sectors", 
                "Juniors / Early Years (Nursery, KG, Prep)",
                "Matriculation (SSC)", 
                "Intermediate / Board Students (HSSC)",
                "O-Level / IGCSE", 
                "A-Level", 
                "MBBS / Medical", 
                "FCPS / Postgraduate Medical",
                "Business Studies & Economics", 
                "University & Engineering",
                "Master's / Postgraduate",
                "PhD / Doctorate",
                "Professional & Certifications",
                "Law & Jurisprudence"
            ]
        )
        explore_query = st.text_input("🔍 Search subjects, courses, or keywords...", key="explore_search").lower()
        
        filtered_vaults = GLOBAL_MULTI_SECTOR_LIBRARY
        if sector_filter != "All Sectors":
            filtered_vaults = [v for v in filtered_vaults if v["sector"] == sector_filter]
        if explore_query:
            filtered_vaults = [
                v for v in filtered_vaults 
                if explore_query in v["title"].lower() 
                or explore_query in v["subject"].lower() 
                or explore_query in v["sector"].lower()
                or any(explore_query in c.lower() for c in v["key_concepts"])
            ]
            
        st.markdown(f"**Showing {len(filtered_vaults)} public study vaults:**")
        
        cols = st.columns(2)
        for idx, vault in enumerate(filtered_vaults):
            with cols[idx % 2]:
                with st.container(border=True):
                    st.markdown(f"### 📘 {vault['title']}")
                    st.caption(f"🏫 **Sector:** {vault['sector']} · 🏷️ **Subject:** {vault['subject']} · 🧪 **Sample set**")
                    st.write(vault["summary"])
                    if st.button(f"🚀 Load into StudyStack Workspace", key=f"load_global_vault_{idx}"):
                        st.session_state.analysis_result = vault
                        st.session_state.chat_history = []
                        st.session_state.mcq = None
                        st.success(f"Loaded '{vault['title']}'! Check the Knowledge Graph, AI Tutor, or Quiz tabs.")
                        time.sleep(1)
                        st.rerun()

# --- PROGRESS ---
with tab_prog:
    if st.session_state.auth_mode != "user":
        with card("prog_guest"):
            st.header("🏆 Progress")
            st.info("Sign in to track your streak and compete with friends.")
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
            if st.button("Refresh", key="refresh_social"):
                get_social(force=True)
                st.rerun()

        with card("friends"):
            st.header("👥 Friends")
            if soc["code"]:
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

            if accepted:
                st.subheader("Your friends")
                for x in accepted:
                    nm = clean_name(x["name"]) or "Student"
                    c1, c2 = st.columns([5, 1.6])
                    c1.markdown(f"🧑‍🎓 **{nm}**")
                    if c2.button("Remove", key=f"rm_{x['id']}"):
                        st.session_state.confirm_remove = x["id"]
                        st.rerun()

        with card("board"):
            st.header("🏅 Weekly leaderboard")
            board = soc["board"]
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
            topic_name = str(res.get("topic", "")).strip()
            concepts, seen = [], set()
            for c in res.get("key_concepts", []):
                name_c = str(c or "").strip()
                if name_c and name_c.lower() != topic_name.lower():
                    seen.add(name_c.lower())
                    concepts.append(name_c)
            
            if concepts:
                from pyvis.network import Network
                import streamlit.components.v1 as components
                graph_bg = "#0e1117" if dark else "#ffffff"
                graph_font = "#ffffff" if dark else "#000000"
                net = Network(height="500px", width="100%", bgcolor=graph_bg, font_color=graph_font)
                net.add_node(topic_name, label=topic_name, color="#7c5cff", size=35, title=topic_name)
                
                for i, concept in enumerate(concepts):
                    concept_id = f"c_{i}"
                    status = mastery_status(topic_name, concept)
                    net.add_node(concept_id, label=concept, color=MASTERY_COLORS[status], size=25,
                                 title=f"{concept}: {MASTERY_LABELS[status]}")
                    net.add_edge(topic_name, concept_id, color="#aab4d4")

                net.set_options("""
                var options = {
                  "physics": {
                    "forceAtlas2Based": {
                      "gravitationalConstant": -100,
                      "centralGravity": 0.01,
                      "springLength": 100,
                      "springConstant": 0.08
                    },
                    "maxVelocity": 50,
                    "solver": "forceAtlas2Based",
                    "timestep": 0.35,
                    "stabilization": {"iterations": 150}
                  }
                }
                """)
                try:
                    path = "temp_graph.html"
                    net.save_graph(path)
                    with open(path, 'r', encoding='utf-8') as f:
                        html_data = f.read()
                    fit_js = """
<script>
(function () {
  function fitIt() {
    try {
      network.setSize("100%", "500px");
      network.redraw();
      network.fit({animation: false});
    } catch (e) {}
  }
  var tries = 0;
  var timer = setInterval(function () {
    var c = document.getElementById("mynetwork");
    if (c && c.offsetWidth > 0 && c.offsetHeight > 0) {
      fitIt();
      tries++;
      if (tries > 3) { clearInterval(timer); }
    }
  }, 400);
  window.addEventListener("resize", fitIt);
})();
</script>
"""
                    html_data = html_data.replace("</body>", fit_js + "</body>")
                    components.html(html_data, height=520)
                except Exception as e:
                    st.error(f"Could not generate graph: {e}")
                  
                st.caption("🟢 Strong · 🟠 Shaky · 🔴 Weak or a confident mistake · ⚪ Not tested yet. "
                           "Colours come from your quiz answers and how sure you were.")
                map_words = concept_map_text(res.get("topic", "Topic"), concepts, res.get("relationships", []))
                read_aloud(map_words, key="tts_mindmap", scope="card_graph")
                with st.expander("Read the concept map in words"):
                    st.text(map_words)
            else:
                st.info("No key concepts were found.")

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
            if not st.session_state.name_asked:
                with st.chat_message("assistant"):
                    st.markdown("Hi! I'm your StudyStack tutor 👋 What should I call you?")
                with st.form("name_form", clear_on_submit=True):
                    n = st.text_input("Your name", max_chars=30, placeholder="e.g. Asim")
                    c1, c2, _ = st.columns([1, 1, 4])
                    go = c1.form_submit_button("Continue")
                    skip = c2.form_submit_button("Skip")
                if go:
                    cleaned = clean_name(n)
                    if cleaned:
                        st.session_state.user_name = cleaned
                        st.session_state.name_asked = True
                        st.rerun()
                if skip:
                    st.session_state.name_asked = True
                    st.rerun()
            else:
                audio = st.audio_input("🎙️ Record a voice question", key=f"voice_{st.session_state.voice_gen}")
                if audio is not None:
                    st.audio(audio)
                    if st.button("🚀 Process voice message", key="voice_go"):
                        if audio.size > MAX_AUDIO_MB * 1024 * 1024:
                            st.error("Recording too large.")
                        else:
                            with st.spinner("Listening..."):
                                reply = evaluate_voice(audio.getvalue(), context, name)
                            st.session_state.chat_history.append({"role": "user", "content": "🎙️ *[Voice message]*"})
                            st.session_state.chat_history.append({"role": "assistant", "content": reply})
                            persist_chat()
                            award("tutor")
                            st.session_state.voice_gen += 1
                            st.rerun()

                history_box = st.container()
                lang = st.selectbox("Tutor language", ["Auto", "English", "Roman Urdu", "Urdu"], key="tutor_lang")
                think_first = st.toggle("🧠 Think-First mode: try it yourself before the tutor explains",
                                        value=True, key="think_first")
                if think_first:
                    think_first_ui(context, name, lang)
                else:
                    with st.form("chat_form", clear_on_submit=True):
                        q = st.text_input("Ask about the material", placeholder="Type your question")
                        sent = st.form_submit_button("Ask")

                    if sent and q.strip():
                        with st.spinner("Thinking..."):
                            reply = chat_with_notes(q, context, st.session_state.chat_history, name, lang)
                        st.session_state.chat_history.append({"role": "user", "content": q})
                        st.session_state.chat_history.append({"role": "assistant", "content": reply})
                        try:
                            persist_chat()
                            if len(q.strip()) >= 5:
                                award("tutor")
                        except Exception as e:
                            st.warning(f"Reply shown, but saving failed: {e}")

                with history_box:
                # --- SCROLLABLE CHAT HISTORY ---
                with st.container(height=450):
                    for m in st.session_state.chat_history:
                        with st.chat_message(m["role"]):
                            st.markdown(m["content"])
                # -------------------------------
# --- FOCUS HUB ---
with tab_focus:
    with card("focus_hub_tab"):
        st.header("⏱️ Focus & Pomodoro Hub")
        if "focus_timer_state" not in st.session_state:
            st.session_state.focus_timer_state = "idle"
        if "focus_timer_end" not in st.session_state:
            st.session_state.focus_timer_end = 0

        if st.session_state.focus_timer_state == "idle":
            col1, col2 = st.columns(2)
            with col1:
                session_type = st.selectbox("Select Study Mode", ["Deep Work Pomodoro (25m)", "Shallow Work (30m)", "Revision (10m)"])
            with col2:
                st.metric("Total Focus Time", f"{st.session_state.study_minutes} mins")
            selected_minutes = 25 if session_type == "Deep Work Pomodoro (25m)" else (30 if session_type == "Shallow Work (30m)" else 10)
            if st.button("🚀 Start Focus Session"):
                st.session_state.focus_timer_state = "running"
                st.session_state.focus_timer_end = time.time() + (selected_minutes * 60)
                st.session_state.focus_timer_mins = selected_minutes
                st.rerun()
        elif st.session_state.focus_timer_state == "running":
            remaining = int(st.session_state.focus_timer_end - time.time())
            if remaining <= 0:
                st.session_state.study_minutes += st.session_state.focus_timer_mins
                st.session_state.sessions_completed += 1
                st.session_state.focus_timer_state = "idle"
                st.balloons()
                st.success("🎉 Session complete!")
                time.sleep(2)
                st.rerun()
            else:
                mins, secs = divmod(remaining, 60)
                st.markdown(f"### ⏳ {mins:02d}:{secs:02d} remaining")
                if st.button("🛑 Stop & Reset"):
                    st.session_state.focus_timer_state = "idle"
                    st.rerun()

# --- METACOGNITION QUIZ ---
with tab_quiz:
    res = st.session_state.analysis_result
    if res is None:
        need_upload("quiz")
    else:
        topic = res.get("topic", "the topic")
        with card("quiz"):
            st.header("🧠 Metacognition Quiz")
            mode = st.radio("Quiz mode", ["Multiple choice", "Feynman (explain it)"], horizontal=True)
            if mode == "Multiple choice":
                mcq_quiz(res.get("flashcards", []), res.get("key_concepts", []), topic)
            else:
                st.write(f"Explain **{topic}** in your own words.")
                answer = st.text_area("Your explanation", key="feynman_answer")
                if st.button("Grade my answer", key="feynman_grade"):
                    if answer.strip():
                        with st.spinner("Grading..."):
                            feedback = grade_answer(topic, answer)
                        st.write(feedback)
                        if len(answer.strip()) >= 30:
                            award("quiz", immediate=True)
                    else:
                        st.warning("Type an explanation first.")
                      
      
      

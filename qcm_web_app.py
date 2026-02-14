import streamlit as st
import pandas as pd
import csv
import io
import os
import time
from collections import Counter
import webbrowser
import pdfkit
import random
import datetime
from datetime import timedelta
import logging
import re
import sqlite3
import json
import shutil
import hashlib
from contextlib import contextmanager
from streamlit_option_menu import option_menu
import markdown
import tempfile

# --- ADVANCED LIBS ---
import PyPDF2

# --- LOGGING CONFIGURATION ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('qcm_app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- OCR & DOCUMENT PARSING (optional imports) ---
try:
    import pytesseract
    from PIL import Image
    import pdf2image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    logger.warning("OCR non disponible. Installez: pip install pytesseract Pillow pdf2image")

try:
    from docx import Document
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False
    logger.warning("Support DOCX non disponible. Installez: pip install python-docx")

def extract_text_from_pdf(file_bytes, use_ocr=False):
    """Extraie le texte d'un fichier PDF (avec option OCR pour PDFs scannés)."""
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        
        # Si le texte est vide ou trop court, essayer l'OCR
        if use_ocr and OCR_AVAILABLE and len(text.strip()) < 50:
            logger.info("Texte extrait trop court, tentative OCR...")
            return extract_text_with_ocr(file_bytes)
        
        return text.strip() if text.strip() else "[PDF vide ou scanné - Activez l'OCR]"
    except Exception as e:
        logger.error(f"Erreur extraction PDF: {e}")
        return f"Erreur d'extraction : {e}"

def extract_text_with_ocr(file_bytes):
    """Applique l'OCR sur un PDF scanné."""
    if not OCR_AVAILABLE:
        return "[OCR non disponible - Installez pytesseract et pdf2image]"
    
    try:
        # Convertir PDF en images
        images = pdf2image.convert_from_bytes(file_bytes)
        text = ""
        for i, img in enumerate(images):
            logger.info(f"OCR page {i+1}/{len(images)}...")
            text += pytesseract.image_to_string(img, lang='fra') + "\n"
        return text.strip()
    except Exception as e:
        logger.error(f"Erreur OCR: {e}")
        return f"Erreur OCR : {e}"

def extract_text_from_docx(file_bytes):
    """Extraie le texte d'un fichier Word (.docx)."""
    if not DOCX_AVAILABLE:
        return "[Support DOCX non disponible - Installez python-docx]"
    
    try:
        doc = Document(io.BytesIO(file_bytes))
        text = "\n".join([para.text for para in doc.paragraphs if para.text.strip()])
        return text.strip()
    except Exception as e:
        logger.error(f"Erreur extraction DOCX: {e}")
        return f"Erreur d'extraction DOCX : {e}"

def validate_file_upload(uploaded_file, allowed_types=["pdf"], max_size_mb=10):
    """Vérifie le type et la taille d'un fichier uploadé."""
    if uploaded_file is None:
        return True, ""
    
    # Check size
    if uploaded_file.size > max_size_mb * 1024 * 1024:
        return False, f"Fichier trop lourd (> {max_size_mb} MB)."
    
    # Check extension/type
    ext = uploaded_file.name.split('.')[-1].lower()
    if ext not in allowed_types:
        return False, f"Format non supporté ({ext}). Attendus : {', '.join(allowed_types)}."
    
    return True, ""

def validate_csv_data(csv_text, q_type):
    """Analyse le CSV et retourne une liste d'erreurs/avertissements."""
    errors = []
    warnings = []
    f = io.StringIO(csv_text.strip())
    reader = csv.reader(f, delimiter='|')
    
    # Check header and identify columns
    header = next(reader, None)
    if not header:
        return ["Le fichier est vide."], []
    
    ans_col_idx = -1
    if header:
        for j, col in enumerate(header):
            if col.strip().upper() in ["RÉPONSE", "REPONSE", "ANSWER"]:
                ans_col_idx = j
                break

    for i, row in enumerate(reader, 1):
        if not any(row): continue # Skip empty lines
        if str(row[0]).strip().lower() in ["question", "titre"]: continue
        
        if q_type == "QCM Classique":
            if len(row) < 7:
                errors.append(f"Ligne {i} : Colonnes insuffisantes ({len(row)}/7 minimum).")
                continue
            
            # Identify Answer Column
            ans_idx = ans_col_idx
            if ans_idx == -1 or ans_idx >= len(row):
                # Robust fallback: Search from right to left
                ans_pattern = re.compile(r'^[A-Z]([;, ]{0,2}[A-Z])*$')
                search_limit = min(len(row) - 1, 11)
                for j in range(search_limit, 1, -1):
                    val = row[j].strip().upper()
                    if val and len(val) <= 15 and ans_pattern.match(val):
                        ans_idx = j
                        break
                if ans_idx == -1: ans_idx = max(1, len(row) - 2)
            
            raw_ans = row[ans_idx].strip().upper()
            if raw_ans in ["RÉPONSE", "REPONSE", "ANSWER"]: continue
            
            opts = [o.strip() for o in row[1:ans_idx] if o.strip()]
            num_opts = len(opts)
            lets = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[:num_opts]
            
            # PREFIX-BASED EXTRACTION: Take letters until first dirty char
            ans_clean = ""
            for char in raw_ans:
                if char in lets: ans_clean += char
                elif char in [';', ',', ' ', ':', '.', '/', '?']: continue
                else: break # Stop at first non-answer character
            
            if not ans_clean:
                errors.append(f"Ligne {i} : Réponse '{raw_ans[:10]}' invalide pour {num_opts} options.")
        
        elif q_type in ["Questions / Réponses", "Glossaire (Concept | Définition)"]:
            if len(row) < 2:
                errors.append(f"Ligne {i} : Format attendu 'A|B', trouvé seulement {len(row)} colonnes.")
        
        elif q_type == "Synthèse (Markdown)":
            # Pas de validation CSV pour le Markdown
            pass
    
    return errors, warnings

# Configuration de la page
st.set_page_config(page_title="QCM Master Pro v4", layout="wide", page_icon="🎯")

# --- CUSTOM CSS: BLANK EXAM THEME (ROBUST CARD) ---
st.markdown("""
<style>
    /* App Background */
    [data-testid="stAppViewContainer"] { background-color: #f4f6f9; }
    
    /* Professional Header/Nav */
    header { background-color: transparent !important; }
    .stDeployButton { display:none; }

    /* Paper Effect: Targets the entire main area */
    .main .block-container {
        background-color: #ffffff;
        padding: 3rem 5rem !important;
        border-radius: 2px;
        box-shadow: 0 10px 25px rgba(0,0,0,0.05);
        max-width: 1000px !important;
        margin: 2rem auto !important;
        border: 1px solid #e0e0e0;
    }
    
    /* Typography - Professional Georgia Serif */
    h1, h2, h3, h4, h5 { font-family: 'Georgia', serif; color: #1a1a1a; }
    .stMarkdown p, .stMarkdown li, .stCheckbox [data-testid="stMarkdownContainer"] p { 
        font-family: 'Georgia', serif; 
        font-size: 1.1rem; 
        line-height: 1.6; 
        color: #1a1a1a; 
    }
    
    /* Global Info/Success/Warning font */
    div[data-testid="stNotification"] p { font-family: 'Georgia', serif; }
    
    /* Condense Widgets for Zero-Scroll */
    [data-testid="stCheckbox"] { margin-bottom: -14px; }
    .stCheckbox [data-testid="stMarkdownContainer"] p { font-size: 1rem !important; }
    .stButton > button { border-radius: 2px; font-weight: 500; height: auto; padding-top: 5px; padding-bottom: 5px; }
    .stProgress { margin-bottom: 0.5rem; }
    
    /* Compact Sidebar */
    [data-testid="stSidebar"] { background-color: #ffffff; }
</style>
""", unsafe_allow_html=True)

# --- INITIALISATION STATE ---
if 'quiz_started' not in st.session_state:
    st.session_state.quiz_started = False
if 'user_answers' not in st.session_state:
    st.session_state.user_answers = {}
if 'start_time' not in st.session_state:
    st.session_state.start_time = None
if 'score_submitted' not in st.session_state:
    st.session_state.score_submitted = False
if 'identity' not in st.session_state:
    st.session_state.identity = {"nom": "", "prenom": "", "id": "", "email": "", "verified": False}
if 'cheat_warnings' not in st.session_state:
    st.session_state.cheat_warnings = 0
if 'last_csv_data' not in st.session_state:
    st.session_state.last_csv_data = ""
if 'shuffled_questions' not in st.session_state:
    st.session_state.shuffled_questions = []
if 'current_q_idx' not in st.session_state:
    st.session_state.current_q_idx = 0
if 'validated_current' not in st.session_state:
    st.session_state.validated_current = False
if 'history' not in st.session_state:
    st.session_state.history = []
if 'verification_code' not in st.session_state:
    st.session_state.verification_code = None
if 'confirm_exit' not in st.session_state:
    st.session_state.confirm_exit = False
if 'current_course_name' not in st.session_state:
    st.session_state.current_course_name = "Quiz Manuel"
if 'auto_load_csv' not in st.session_state:
    st.session_state.auto_load_csv = None
if 'view_content' not in st.session_state:
    st.session_state.view_content = {"name": "", "content": "", "type": ""}
if 'current_page' not in st.session_state:
    st.session_state.current_page = "📄 PDF Transformer"

# --- MAIN NAVIGATION (NAVBAR) ---
pages_config = {
    "📄 PDF Transformer": {"icon": "file-earmark-pdf"},
    "📄 PDF Merger": {"icon": "file-earmark-zip"},
    "✍️ Créateur": {"icon": "pencil-square"},
    "🔍 Explorer": {"icon": "search"},
    "📚 Résumés": {"icon": "book"},
    "⚡ Quiz Interactif": {"icon": "lightning"},
    "⭐ Mes Favoris": {"icon": "star"},
    "📊 Historique": {"icon": "clock-history"},
    "💡 Guide IA": {"icon": "robot"},
    "⚙️ Gestion BD": {"icon": "gear"}
}

# If in visualizer mode, add it temporarily
current_pages = list(pages_config.keys())
if st.session_state.get("current_page") == "👁️ Visualiseur":
    current_pages.append("👁️ Visualiseur")

# Optimized Horizontal Navbar at the top
selected = option_menu(
    menu_title=None,
    options=current_pages,
    icons=[pages_config.get(p, {"icon": "eye"})["icon"] for p in current_pages],
    menu_icon="cast",
    default_index=current_pages.index(st.session_state.current_page) if st.session_state.current_page in current_pages else 0,
    orientation="horizontal",
    key="main_navbar", # Stable key for performance
    styles={
        "container": {"padding": "0!important", "background-color": "#fafafa"},
        "icon": {"color": "#27ae60", "font-size": "14px"}, 
        "nav-link": {"font-size": "12px", "text-align": "left", "margin": "0px", "--hover-color": "#eee"},
        "nav-link-selected": {"background-color": "#27ae60"},
    }
)

# Immediate state sync
if selected != st.session_state.current_page:
    st.session_state.current_page = selected
    st.rerun()

# --- DATABASE LOGIC (SQLite) ---
DB_NAME = "qcm_master.db"

@contextmanager
def db_context():
    conn = sqlite3.connect(DB_NAME)
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """Initialise les tables SQLite."""
    with db_context() as conn:
        c = conn.cursor()
        # Table des utilisateurs
        c.execute('''CREATE TABLE IF NOT EXISTS users 
                     (email TEXT PRIMARY KEY, nom TEXT, prenom TEXT, user_id TEXT)''')
        # Table de l'historique des scores
        c.execute('''CREATE TABLE IF NOT EXISTS history 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, course TEXT, score INTEGER, total INTEGER, date TEXT)''')
        # Table des modules éducatifs
        c.execute('''CREATE TABLE IF NOT EXISTS educational_modules 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, category TEXT, type TEXT, content TEXT, created_at TEXT)''')
        # Table de progression
        c.execute('''CREATE TABLE IF NOT EXISTS quiz_progress 
                     (email TEXT, module_name TEXT, current_idx INTEGER, answers TEXT, last_updated TEXT, 
                      PRIMARY KEY(email, module_name))''')
        # Table des favoris
        c.execute('''CREATE TABLE IF NOT EXISTS favorites 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, module_name TEXT, question_text TEXT, 
                      options TEXT, answer TEXT, explanation TEXT, created_at TEXT)''')
        conn.commit()

def validate_input(text, max_length=10000, allow_html=False):
    """Valide et nettoie les entrées utilisateur."""
    if not text or not isinstance(text, str):
        return ""
    text = text[:max_length]
    if not allow_html:
        text = re.sub(r'<[^>]+>', '', text)
    return text.strip()

def db_save_user(email, nom, prenom, user_id):
    """Sauvegarde un utilisateur."""
    email = email.lower()
    with db_context() as conn:
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO users (email, nom, prenom, user_id) VALUES (?, ?, ?, ?)",
                 (email, nom, prenom, user_id))
        conn.commit()

def db_save_score(email, course, score, total):
    """Sauvegarde un score."""
    email = email.lower()
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    with db_context() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO history (email, course, score, total, date) VALUES (?, ?, ?, ?, ?)",
                 (email, course, score, total, date_str))
        conn.commit()

def db_get_best_score(email, course):
    """Récupère le meilleur score."""
    email = email.lower()
    with db_context() as conn:
        c = conn.cursor()
        c.execute("SELECT score, total FROM history WHERE email = ? AND course = ? ORDER BY score DESC LIMIT 1",
                 (email, course))
        res = c.fetchone()
        if res:
            return f"{res[0]} / {res[1]}"
    return "N/A"

def db_save_progress(email, module_name, current_idx, answers):
    """Sauvegarde la progression."""
    email = email.lower()
    ans_json = json.dumps(answers)
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    with db_context() as conn:
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO quiz_progress (email, module_name, current_idx, answers, last_updated) VALUES (?, ?, ?, ?, ?)",
                 (email, module_name, current_idx, ans_json, date_str))
        conn.commit()

def db_load_progress(email, module_name):
    """Charge la progression."""
    email = email.lower()
    with db_context() as conn:
        c = conn.cursor()
        c.execute("SELECT current_idx, answers FROM quiz_progress WHERE email = ? AND module_name = ?",
                 (email, module_name))
        res = c.fetchone()
        if res:
            return {"idx": res[0], "answers": json.loads(res[1])}
    return None

def db_clear_progress(email, module_name):
    """Supprime la progression."""
    email = email.lower()
    with db_context() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM quiz_progress WHERE email = ? AND module_name = ?", (email, module_name))
        conn.commit()

def db_save_module(name, category, m_type, content):
    """Sauvegarde le module dans SQLite."""
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    with db_context() as conn:
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO educational_modules (name, category, type, content, created_at) VALUES (?, ?, ?, ?, ?)",
                 (name, category, m_type, content, date_str))
        conn.commit()

def db_get_modules(m_type=None, search="", limit=None, offset=0):
    """Récupère les modules depuis SQL."""
    query = "SELECT id, name, category, type, content, created_at FROM educational_modules WHERE 1=1"
    params = []
    if m_type:
        query += " AND type = ?"
        params.append(m_type)
    if search:
        query += " AND (name LIKE ? OR category LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    
    query += " ORDER BY created_at DESC"
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    if offset:
        query += " OFFSET ?"
        params.append(offset)
        
    with db_context() as conn:
        c = conn.cursor()
        c.execute(query, params)
        return c.fetchall()

def db_count_modules(m_type=None, search=""):
    """Compte les modules."""
    query = "SELECT COUNT(*) FROM educational_modules WHERE 1=1"
    params = []
    if m_type:
        query += " AND type = ?"
        params.append(m_type)
    if search:
        query += " AND (name LIKE ? OR category LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
        
    with db_context() as conn:
        c = conn.cursor()
        c.execute(query, params)
        return c.fetchone()[0]

def db_delete_module(m_id):
    """Supprime un module."""
    with db_context() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM educational_modules WHERE id = ?", (m_id,))
        conn.commit()

def db_get_history(email):
    """Récupère l'historique."""
    with db_context() as conn:
        query = "SELECT date as Date, course as Examen, (score || ' / ' || total) as Score FROM history WHERE email = ? ORDER BY date DESC"
        return pd.read_sql_query(query, conn, params=(email.lower(),))

def db_export_all_user_data(email):
    """Exporte history et progress."""
    email = email.lower()
    with db_context() as conn:
        history = pd.read_sql_query("SELECT * FROM history WHERE email = ?", conn, params=(email,)).to_dict('records')
        progress = pd.read_sql_query("SELECT * FROM quiz_progress WHERE email = ?", conn, params=(email,)).to_dict('records')
    return {"history": history, "progress": progress}

def db_toggle_favorite(email, module_name, q_text, opts, ans, expl):
    """Ajoute ou supprime une question des favoris."""
    email = email.lower()
    opts_json = json.dumps(opts)
    with db_context() as conn:
        c = conn.cursor()
        # Vérifier si elle existe déjà
        c.execute("SELECT id FROM favorites WHERE email = ? AND question_text = ?", (email, q_text))
        res = c.fetchone()
        if res:
            c.execute("DELETE FROM favorites WHERE id = ?", (res[0],))
            status = "removed"
        else:
            date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            c.execute("INSERT INTO favorites (email, module_name, question_text, options, answer, explanation, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (email, module_name, q_text, opts_json, ans, expl, date_str))
            status = "added"
        conn.commit()
        return status

def db_get_favorites(email):
    """Récupère tous les favoris d'un utilisateur."""
    email = email.lower()
    with db_context() as conn:
        c = conn.cursor()
        c.execute("SELECT module_name, question_text, options, answer, explanation FROM favorites WHERE email = ? ORDER BY created_at DESC", (email,))
        rows = c.fetchall()
        favs = []
        for r in rows:
            favs.append({
                "module": r[0],
                "text": r[1],
                "opts": json.loads(r[2]),
                "ans": r[3],
                "expl": r[4]
            })
        return favs

def db_export_to_excel():
    """Génère un fichier Excel contenant toute la base de données."""
    output = io.BytesIO()
    with db_context() as conn:
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            pd.read_sql_query("SELECT * FROM users", conn).to_excel(writer, sheet_name='Utilisateurs', index=False)
            pd.read_sql_query("SELECT * FROM educational_modules", conn).to_excel(writer, sheet_name='Modules', index=False)
            pd.read_sql_query("SELECT * FROM history", conn).to_excel(writer, sheet_name='Historique', index=False)
            pd.read_sql_query("SELECT * FROM quiz_progress", conn).to_excel(writer, sheet_name='Progressions', index=False)
            pd.read_sql_query("SELECT * FROM favorites", conn).to_excel(writer, sheet_name='Favoris', index=False)
    return output.getvalue()

def get_user_recommendations(email, limit=3):
    """Recommandations simples."""
    all_qcms = db_get_modules(m_type="QCM")
    return [(m[1], "Nouveau module", m[2]) for m in all_qcms[:limit]]

# Initialize DB on load
init_db()

# --- FONCTIONS UTILES ---
def convert_html_to_pdf(source_html, zoom=1.0, options=None):
    """Convertit le HTML en PDF bytes via pdfkit. Supporte le zoom et les options personnalisées."""
    try:
        if options is None:
            options = {
                'page-size': 'A4',
                'margin-top': '1.5cm',
                'margin-right': '1.5cm',
                'margin-bottom': '1.5cm',
                'margin-left': '1.5cm',
                'encoding': "UTF-8",
                'zoom': str(zoom),
                'no-outline': None,
                'quiet': ''
            }
        
        # Tentative de trouver wkhtmltopdf
        path_wkhtmltopdf = r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe'
        if not os.path.exists(path_wkhtmltopdf):
            path_wkhtmltopdf = shutil.which("wkhtmltopdf")
        
        if path_wkhtmltopdf:
            config = pdfkit.configuration(wkhtmltopdf=path_wkhtmltopdf)
            return pdfkit.from_string(source_html, False, configuration=config, options=options)
        else:
            return pdfkit.from_string(source_html, False, options=options)
    except Exception as e:
        logger.error(f"Erreur PDF : {e}")
        st.warning(f"⚠️ PDF impossible : {e}. Assurez-vous que wkhtmltopdf est installé.")
        return None

def generate_diploma(name, score, total, course_title):
    """Génère un PDF de diplôme pour les scores > 80%"""
    date_str = datetime.datetime.now().strftime("%d/%m/%Y")
    html_diploma = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: 'Arial', sans-serif; text-align: center; border: 10px double #2c3e50; padding: 50px; color: #2c3e50; }}
            .title {{ font-size: 48pt; font-weight: bold; margin-bottom: 20px; }}
            .subtitle {{ font-size: 24pt; margin-bottom: 50px; }}
            .content {{ font-size: 18pt; margin-bottom: 40px; }}
            .name {{ font-size: 30pt; font-weight: bold; text-decoration: underline; margin: 20px 0; }}
            .footer {{ margin-top: 100px; font-size: 14pt; font-style: italic; }}
            .stamp {{ position: absolute; bottom: 50px; right: 50px; border: 3px solid #e74c3c; color: #e74c3c; padding: 10px; font-weight: bold; transform: rotate(-15deg); }}
        </style>
    </head>
    <body>
        <div class="title">CERTIFICAT DE RÉUSSITE</div>
        <div class="subtitle">QCM Master Pro</div>
        <div class="content">Décerné à :</div>
        <div class="name">{name}</div>
        <div class="content">
            Pour avoir complété avec succès l'examen :<br/>
            <strong>{course_title}</strong><br/>
            avec un score impressionnant de <strong>{score} / {total}</strong> ({(score/total*100):.1f}%).
        </div>
        <div class="footer">Délivré le {date_str}</div>
        <div class="stamp">VALIDÉ</div>
    </body>
    </html>
    """
    return convert_html_to_pdf(html_diploma)

def open_local_html(content, title, m_type):
    """Génère un fichier HTML temporaire et l'ouvre dans le navigateur local."""
    try:
        html_str = generate_export_html(content, title, m_type)
        with tempfile.NamedTemporaryFile('w', delete=False, suffix='.html', encoding='utf-8') as f:
            f.write(html_str)
            tmp_path = f.name
        webbrowser.open(f"file://{os.path.abspath(tmp_path)}")
        return True
    except Exception as e:
        logger.error(f"Erreur preview HTML: {e}")
        return False

def generate_answer_sheet(num_questions):
    """Génère une feuille de cochage propre sur 3 colonnes"""
    def make_table(q_range):
        rows = ""
        for i in q_range:
            rows += f"""<tr><td style='font-weight:bold; width:30px;'>{i}</td>""" + "".join([f"<td style='width:30px; border:1px solid #000;'></td>" for _ in range(6)]) + "</tr>"
        return f"""
        <table style="width:100%; border-collapse: collapse; text-align:center; font-size:9pt; margin-bottom:20px;">
            <thead><tr><th>N°</th><th>A</th><th>B</th><th>C</th><th>D</th><th>E</th><th>F</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>"""

    # Split into 3 chunks
    q_per_col = (num_questions + 2) // 3
    c1 = range(1, min(num_questions + 1, q_per_col + 1))
    c2 = range(q_per_col + 1, min(num_questions + 1, 2 * q_per_col + 1))
    c3 = range(2 * q_per_col + 1, num_questions + 1)

    return f"""
    <div style="page-break-before: always; margin-top:30px;">
        <h2 style="text-align:center;">FEUILLE DE RÉPONSES (À COCHER)</h2>
        <div style="display:flex; justify-content: space-between; gap: 20px;">
            <div style="flex:1;">{make_table(c1)}</div>
            <div style="flex:1;">{make_table(c2) if c2 else ""}</div>
            <div style="flex:1;">{make_table(c3) if c3 else ""}</div>
        </div>
        <p style="font-size:8pt; text-align:center; margin-top:10px;">Cochez la case correspondante à votre réponse.</p>
    </div>"""

def generate_certificate_html(user_name, course_name, score, total):
    """Génère un HTML élégant pour le certificat de réussite."""
    from datetime import datetime
    date_str = datetime.now().strftime("%d %B %Y")
    percentage = round((score / total) * 100)
    
    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Pinyon+Script&family=Montserrat:wght@400;700&display=swap');
            body {{
                background-color: #f0f0f0;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
            }}
            .certificate {{
                background-color: white;
                padding: 50px;
                width: 800px;
                height: 550px;
                border: 15px solid #d4af37;
                position: relative;
                box-shadow: 0 0 20px rgba(0,0,0,0.2);
                text-align: center;
                font-family: 'Montserrat', sans-serif;
            }}
            .certificate:before {{
                content: '';
                position: absolute;
                top: 10px; left: 10px; right: 10px; bottom: 10px;
                border: 2px solid #d4af37;
            }}
            .header {{
                font-size: 50px;
                color: #d4af37;
                font-family: 'Pinyon Script', cursive;
                margin-bottom: 20px;
            }}
            .sub-header {{
                font-size: 18px;
                text-transform: uppercase;
                letter-spacing: 5px;
                margin-bottom: 40px;
            }}
            .user-name {{
                font-size: 40px;
                border-bottom: 2px solid #333;
                display: inline-block;
                padding: 0 50px;
                margin-bottom: 20px;
            }}
            .course-name {{
                font-size: 24px;
                font-weight: bold;
                color: #2c3e50;
                margin: 20px 0;
            }}
            .score {{
                font-size: 20px;
                margin-bottom: 40px;
            }}
            .footer {{
                display: flex;
                justify-content: space-between;
                margin-top: 50px;
                padding: 0 50px;
                font-size: 14px;
            }}
            .signature {{
                border-top: 1px solid #333;
                width: 200px;
                padding-top: 5px;
            }}
            .medal {{
                position: absolute;
                bottom: 30px;
                left: 50%;
                transform: translateX(-50%);
                width: 80px;
            }}
        </style>
    </head>
    <body>
        <div class="certificate">
            <div class="header">Certificat de Réussite</div>
            <div class="sub-header">PROJET QCM MASTER PRO</div>
            <p>Ce certificat est fièrement décerné à</p>
            <div class="user_name">{user_name}</div>
            <p>pour avoir complété avec succès l'examen</p>
            <div class="course-name">{course_name}</div>
            <div class="score">Score obtenu : <strong>{score} / {total}</strong> ({percentage}%)</div>
            <div class="footer">
                <div>Délivré le : {date_str}</div>
                <div class="signature">La Direction QCM Master</div>
            </div>
            <img src="https://cdn-icons-png.flaticon.com/512/179/179249.png" class="medal" alt="Médaille">
        </div>
    </body>
    </html>
    """
    return html

def generate_html_content(csv_text, title, use_columns, add_qr=True, mode="Examen", shuffle_q=False, shuffle_o=False, q_type="QCM Classique", add_sheet=True, open_all=False):
    col_css = "column-count: 3; -webkit-column-count: 3; -moz-column-count: 3; column-gap: 30px;" if use_columns else ""
    # Only show QR for QCM mode as it links to a correction sheet
    qr_code_html = ""
    if add_qr and q_type == "QCM Classique":
        qr_code_html = f'<div style="text-align:right;"><img src="https://api.qrserver.com/v1/create-qr-code/?size=100x100&data=https://qcmwebapppy-bfxlibcaaelehxbv6qjyif.streamlit.app/#correction" alt="QR Correction" style="width:80px;"/> <br/><small>Scan pour correction</small></div>'
    
    html_content = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
    body {{ font-family: 'Georgia', serif; line-height: 1.4; color: #000; padding: 20px; }}
    h1 {{ text-align: center; border-bottom: 2px solid #000; padding-bottom: 5px; }}
    .questions-wrapper {{ {col_css} margin-top: 15px; width: 100%; }}
    .question-block {{ margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px dashed #ccc; break-inside: avoid; page-break-inside: avoid; }}
    .question-text {{ font-weight: bold; font-size: 10pt; }}
    .options {{ list-style: none; padding: 0; margin: 0; font-size: 9pt; }}
    .options li {{ margin-bottom: 2px; }}
    .options li::before {{ content: attr(data-letter) ". "; font-weight: bold; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 9pt; }}
    th, td {{ border: 1px solid #000; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background-color: #eee; }}
    .col-concept {{ width: 20%; font-weight: bold; }}
    .col-def {{ width: 80%; }}
    details {{ cursor: pointer; margin-top: 5px; font-size: 9pt; }}
    details summary {{ list-style: none; font-weight: bold; color: #3498db; }}
    details summary::-webkit-details-marker {{ display: none; }}
    .qa-answer {{ padding: 10px; background: #f9f9f9; border-left: 3px solid #3498db; margin-top: 5px; }}
    @media print {{ .no-print {{ display: none; }} }}
</style>
</head>
<body>
    {qr_code_html}
    <h1>{title}</h1>
    <div class="questions-wrapper">
"""
    
    import random
    f = io.StringIO(csv_text)
    reader = csv.reader(f, delimiter='|')
    header = next(reader, None)
    
    ans_col_idx = -1
    if header:
        for j, col in enumerate(header):
            if col.strip().upper() in ["RÉPONSE", "REPONSE", "ANSWER"]:
                ans_col_idx = j
                break
    
    raw_questions = []
    if q_type in ["Questions / Réponses", "Glossaire (Concept | Définition)"]:
        for row in reader:
            if len(row) < 2: continue
            raw_questions.append({
                'text': row[0].strip(),
                'ans': row[1].strip(),
                'type': 'QA' if q_type == "Questions / Réponses" else 'GLOSSARY'
            })
    else:
        for row in reader:
            if not row or not any(row): continue
            if str(row[0]).strip().lower() in ["question", "titre"]: continue
            if len(row) < 7: continue
            q_text = row[0].strip()
            
            # Identify Answer Column
            ans_idx = ans_col_idx
            if ans_idx == -1 or ans_idx >= len(row):
                ans_pattern = re.compile(r'^[A-Z]([;, ]{0,2}[A-Z])*$')
                search_limit = min(len(row) - 1, 11)
                for j in range(search_limit, 1, -1):
                    val = row[j].strip().upper()
                    if val and len(val) <= 15 and ans_pattern.match(val):
                        ans_idx = j
                        break
                if ans_idx == -1: ans_idx = max(1, len(row) - 2)
            
            opts_text = [o.strip() for o in row[1:ans_idx] if o.strip()]
            raw_ans_val = row[ans_idx].strip().upper()
            expl = "|".join(row[ans_idx+1:])
            
            lets = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z'][:len(opts_text)]
            
            # Robust answer extraction
            ans_clean = ""
            for char in raw_ans_val:
                if char in lets: ans_clean += char
                elif char in [';', ',', ' ', ':', '.', '/', '?']: continue
                else: break
            
            correct_indices = [lets.index(l) for l in ans_clean if l in lets]
            
            raw_questions.append({
                'text': q_text,
                'opts_data': [{'text': o, 'is_correct': (i in correct_indices)} for i, o in enumerate(opts_text)],
                'expl': expl,
                'type': 'QCM'
            })

    if shuffle_q:
        random.shuffle(raw_questions)

    questions_html = ""
    answers_rows = ""
    glossary_table = ""
    
    if q_type == "Glossaire (Concept | Définition)":
        glossary_table = "<table><thead><tr><th>Concept</th><th>Définition</th></tr></thead><tbody>"
        for q in raw_questions:
            glossary_table += f"<tr><td class='col-concept'>{q['text']}</td><td class='col-def'>{q['ans']}</td></tr>"
        glossary_table += "</tbody></table>"
        questions_html = glossary_table
    else:
        for q_idx, q in enumerate(raw_questions):
            q_num = q_idx + 1
            if q.get('type') == 'QA':
                questions_html += f"""
                <div class="question-block">
                    <div class="question-text">{q_num}. {q['text']}</div>
                    <details {"open" if open_all else ""}>
                        <summary>▶ Réponse</summary>
                        <div class="qa-answer">{q['ans']}</div>
                    </details>
                </div>"""
                answers_rows += f"<tr><td>{q_num}</td><td colspan='2' style='font-weight:bold;'>{q['ans']}</td></tr>"
            else:
                opts_list = q['opts_data']
                if shuffle_o: random.shuffle(opts_list)
                final_lets = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z'][:len(opts_list)]
                new_ans_letters = "".join([final_lets[i] for i, opt in enumerate(opts_list) if opt['is_correct']])
                
                questions_html += f'<div class="question-block"><div class="question-text">{q_num}. {q["text"]}</div><ul class="options">'
                for i, opt in enumerate(opts_list):
                    questions_html += f'<li data-letter="{final_lets[i]}">{opt["text"]}</li>'
                questions_html += "</ul>"
                
                if mode == "Révision":
                    questions_html += f'<div style="margin-top: 5px; padding: 8px; background: #f0fdf4; border: 1px solid #27ae60; border-radius: 4px; font-size: 9pt;">'
                    questions_html += f'<strong>Réponse : {new_ans_letters}</strong><br/>'
                    questions_html += f'<em>💡 {q["expl"]}</em>'
                    questions_html += '</div>'
                questions_html += "</div>"
                answers_rows += f"<tr><td>{q_num}</td><td style='font-weight:bold;'>{new_ans_letters}</td><td>{q['expl']}</td></tr>"

    # Only show correction footer for QCM mode
    if mode == "Examen" and q_type == "QCM Classique":
        sheet_html = generate_answer_sheet(len(raw_questions)) if add_sheet else ""
        footer = f"""
        </div>
        {sheet_html}
        <div style="page-break-before: always;" id="correction">
            <h2>Correction</h2>
            <table><thead><tr><th>N°</th><th>Réponse</th><th>Explication</th></tr></thead><tbody>{answers_rows}</tbody></table>
        </div>
    </body></html>"""
    else:
        footer = "</div></body></html>"
    
    return html_content + questions_html + footer

# --- TEMPLATES HTML SPÉCIFIQUES PAR TYPE ---

def generate_qa_html(content, title):
    """Génère un HTML propre pour les Questions / Réponses (Style Classique, Font Georgia)."""
    f = io.StringIO(content)
    reader = csv.reader(f, delimiter='|')
    next(reader, None)
    
    items_html = ""
    for i, row in enumerate(reader, 1):
        if len(row) < 2: continue
        q, a = row[0].strip(), row[1].strip()
        items_html += f"""
        <div class="qa-card">
            <div class="qa-question">❓ Q{i}. {q}</div>
            <details>
                <summary>▶ Afficher la réponse</summary>
                <div class="qa-answer">{a}</div>
            </details>
        </div>"""
    
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8"><title>{title}</title>
<style>
    body {{ font-family: 'Georgia', serif; max-width: 900px; margin: auto; padding: 30px; color: #1e293b; background: #f8fafc; }}
    h1 {{ text-align: center; color: #1e40af; border-bottom: 3px solid #3b82f6; padding-bottom: 10px; }}
    .qa-card {{ background: white; border-radius: 10px; padding: 18px; margin-bottom: 16px; box-shadow: 0 2px 6px rgba(0,0,0,0.06); border-left: 4px solid #3b82f6; }}
    .qa-question {{ font-weight: 700; font-size: 1.05em; color: #1e293b; }}
    details {{ margin-top: 8px; }}
    details summary {{ cursor: pointer; font-weight: 600; color: #3b82f6; list-style: none; }}
    details summary::-webkit-details-marker {{ display: none; }}
    .qa-answer {{ padding: 12px; background: #eff6ff; border-radius: 6px; margin-top: 6px; line-height: 1.6; }}
    @media print {{ body {{ background: white; }} .qa-card {{ box-shadow: none; border: 1px solid #ddd; }} }}
</style>
</head>
<body>
    <h1>❓ {title}</h1>
    {items_html}
</body></html>"""

def generate_def_html(content, title):
    """Génère un HTML propre pour les Définitions / Glossaire (Style Classique, Font Georgia)."""
    f = io.StringIO(content)
    reader = csv.reader(f, delimiter='|')
    next(reader, None)
    
    rows_html = ""
    for i, row in enumerate(reader, 1):
        if len(row) < 2: continue
        concept, definition = row[0].strip(), row[1].strip()
        rows_html += f"""<tr><td class="concept">{concept}</td><td class="definition">{definition}</td></tr>"""
    
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8"><title>{title}</title>
<style>
    body {{ font-family: 'Georgia', serif; max-width: 960px; margin: auto; padding: 30px; color: #1e293b; background: #f8fafc; }}
    h1 {{ text-align: center; color: #7c3aed; border-bottom: 3px solid #8b5cf6; padding-bottom: 10px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 20px; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
    th {{ background: #7c3aed; color: white; padding: 14px; text-align: left; font-size: 1em; }}
    td {{ padding: 12px 14px; border-bottom: 1px solid #f1f5f9; vertical-align: top; }}
    tr:hover {{ background: #faf5ff; }}
    .concept {{ font-weight: 700; width: 25%; color: #6d28d9; font-size: 1em; }}
    .definition {{ line-height: 1.6; color: #334155; }}
    @media print {{ body {{ background: white; }} table {{ box-shadow: none; border: 1px solid #ddd; }} }}
</style>
</head>
<body>
    <h1>📜 {title}</h1>
    <table>
        <thead><tr><th>Concept</th><th>Définition</th></tr></thead>
        <tbody>{rows_html}</tbody>
    </table>
</body></html>"""

def generate_sum_html(content, title):
    """Génère un HTML professionnel pour les synthèses/résumés Markdown avec support complet."""
    # Conversion Markdown complète avec extensions
    # 'extra' supporte les tableaux, listes complexes, etc.
    # 'toc' génère une table des matières automatique s'il y a [TOC] ou via anchor ids
    html_body = markdown.markdown(content, extensions=['extra', 'toc', 'sane_lists'])
    
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
    :root {{
        --h1-color: #1e3a8a;
        --h2-color: #2563eb;
        --h3-color: #059669;
        --text-color: #1f2937;
        --bg-color: #ffffff;
        --code-bg: #f3f4f6;
        --border-color: #e5e7eb;
    }}

    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    @page {{ size: A4; margin: 1.5cm; }}
    
    body {{ 
        font-family: 'Georgia', 'Times New Roman', serif; 
        font-size: 11pt; 
        line-height: 1.6; 
        color: var(--text-color); 
        background: var(--bg-color);
        max-width: 850px;
        margin: 0 auto;
        padding: 50px 40px;
    }}

    /* TOC Styling */
    .toc {{
        background: #f8fafc;
        padding: 20px;
        border-radius: 8px;
        margin-bottom: 40px;
        border: 1px solid var(--border-color);
    }}
    .toc ul {{ list-style: none; padding-left: 0; }}
    .toc li {{ margin-bottom: 5px; }}
    .toc a {{ text-decoration: none; color: var(--h2-color); font-weight: 500; }}
    .toc a:hover {{ text-decoration: underline; }}
    
    h1 {{ 
        text-align: center; 
        color: var(--h1-color); 
        font-size: 2.2em; 
        margin-bottom: 20px;
        font-weight: 800;
        border-bottom: 4px solid var(--h1-color);
        padding-bottom: 15px;
        text-transform: uppercase;
    }}
    
    h2 {{
        color: var(--h2-color);
        font-size: 1.6em;
        margin-top: 40px;
        margin-bottom: 15px;
        border-bottom: 2px solid var(--border-color);
        padding-bottom: 8px;
        font-weight: 700;
    }}
    
    h3 {{
        color: var(--h3-color);
        font-size: 1.3em;
        margin-top: 30px;
        margin-bottom: 12px;
        font-weight: 600;
    }}
    
    p {{ margin-bottom: 16px; text-align: justify; }}
    
    /* Lists */
    ul, ol {{ margin: 15px 0 15px 30px; }}
    li {{ margin-bottom: 8px; }}
    
    /* Tables */
    table {{ 
        width: 100%; 
        border-collapse: collapse; 
        margin: 25px 0; 
        font-size: 10pt;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }}
    th {{ 
        background-color: #f9fafb; 
        color: var(--h1-color); 
        padding: 12px; 
        border: 1px solid var(--border-color);
        text-align: left;
    }}
    td {{ 
        padding: 10px 12px; 
        border: 1px solid var(--border-color); 
    }}
    tr:nth-child(even) {{ background-color: #fdfdfd; }}
    
    /* Code blocks */
    code {{
        background: var(--code-bg);
        padding: 2px 6px;
        border-radius: 4px;
        font-family: 'Cascadia Code', 'Fira Code', 'Courier New', monospace;
        font-size: 0.9em;
        color: #d946ef;
    }}
    
    pre {{
        background: #1e293b;
        color: #e2e8f0;
        padding: 20px;
        border-radius: 8px;
        margin: 20px 0;
        overflow-x: auto;
        font-family: 'Cascadia Code', 'Fira Code', monospace;
        font-size: 9.5pt;
        line-height: 1.5;
    }}
    
    pre code {{
        background: none;
        padding: 0;
        color: inherit;
        font-size: inherit;
    }}
    
    /* Horizontal Rule */
    hr {{
        border: 0;
        height: 1px;
        background-image: linear-gradient(to right, rgba(0, 0, 0, 0), rgba(0, 0, 0, 0.75), rgba(0, 0, 0, 0));
        margin: 40px 0;
    }}

    blockquote {{
        border-left: 5px solid var(--h3-color);
        background: #f0fdf4;
        padding: 15px 25px;
        margin: 20px 0;
        font-style: italic;
        color: #065f46;
        border-radius: 0 8px 8px 0;
    }}

    a {{ color: var(--h2-color); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

    /* Print adjustments */
    @media print {{
        body {{ padding: 0; max-width: 100%; }}
        .toc {{ display: none; }}
        h2, h3 {{ page-break-after: avoid; }}
        pre, table {{ page-break-inside: avoid; }}
    }}
</style>
</head>
<body>
    <h1>{title}</h1>
    <div class="toc no-print">
        <strong>📌 Sommaire</strong>
        {markdown.markdown('[TOC]', extensions=['toc'])}
    </div>
    <div class="content">
        {html_body}
    </div>
</body>
</html>"""

    return html

def generate_js_quiz_html(content, title, timer_seconds=0):
    """Génère un QCM interactif Standalone avec JS, Stockage Local et Scoring Partiel."""
    questions = parse_csv(content)
    import json
    q_json = json.dumps(questions, ensure_ascii=False)
    
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - Quiz Interactif</title>
    <style>
        :root {{
            --primary: #2563eb;
            --success: #059669;
            --danger: #dc2626;
            --bg: #f8fafc;
            --card-bg: #ffffff;
            --text: #1e293b;
            --border: #e2e8f0;
        }}
        body {{
            font-family: 'Georgia', serif;
            background-color: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 0;
            line-height: 1.6;
        }}
        header {{
            background: var(--card-bg);
            padding: 0.8rem 1.5rem;
            border-bottom: 2px solid var(--border);
            position: sticky;
            top: 0;
            z-index: 100;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .header-left {{ display: flex; flex-direction: column; gap: 4px; }}
        .header-right {{ display: flex; align-items: center; gap: 20px; }}
        
        .container {{
            max-width: 800px;
            margin: 1.5rem auto;
            padding: 0 1rem;
        }}
        h1 {{ font-size: 1.3rem; margin: 0; color: var(--primary); }}
        .score-box {{ font-weight: bold; font-size: 1.15rem; color: var(--success); }}
        .timer-box {{ font-weight: bold; font-size: 1.15rem; color: var(--danger); min-width: 80px; }}
        
        .card {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1.5rem;
            margin-bottom: 1.2rem;
            box-shadow: none; /* No shadow as requested */
        }}
        .question-text {{ font-size: 1.2rem; font-weight: bold; margin-bottom: 1rem; }}
        .options {{ display: flex; flex-direction: column; gap: 0.5rem; }}
        .option {{
            display: flex;
            align-items: center;
            gap: 1rem;
            padding: 0.8rem;
            border: 1px solid var(--border);
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .option:hover {{ background-color: #f1f5f9; }}
        .option.selected {{ border-color: var(--primary); background-color: #eff6ff; }}
        .option input {{ transform: scale(1.1); }}
        
        .btn {{
            display: inline-block;
            background: var(--primary);
            color: white;
            padding: 0.6rem 1.2rem;
            border-radius: 4px;
            border: none;
            font-size: 0.95rem;
            font-weight: bold;
            cursor: pointer;
            margin-top: 1.2rem;
        }}
        .btn-reset {{ background: #94a3b8; margin-top: 0; margin-left: 10px; padding: 0.4rem 0.8rem; }}
        .btn:disabled {{ opacity: 0.5; cursor: not-allowed; }}
        
        .feedback {{
            margin-top: 1.2rem;
            padding: 1rem;
            border-radius: 6px;
            display: none;
        }}
        .feedback.correct {{ background: #d1fae5; color: #065f46; border-left: 4px solid var(--success); }}
        .feedback.incorrect {{ background: #fee2e2; color: #991b1b; border-left: 4px solid var(--danger); }}
        
        .correct-opt {{ background-color: #d1fae5 !important; border-color: var(--success) !important; }}
        .incorrect-opt {{ background-color: #fee2e2 !important; border-color: var(--danger) !important; }}
        
        .explanation {{ font-style: italic; margin-top: 0.5rem; font-size: 0.9rem; }}
        
        .progress-bar-container {{
            width: 100%;
            height: 6px;
            background: var(--border);
            border-radius: 3px;
            overflow: hidden;
        }}
        .progress-bar {{
            height: 100%;
            background: var(--success);
            width: 0%;
            transition: width 0.3s;
        }}
    </style>
</head>
<body>
    <header>
        <div class="header-left">
            <h1>{title}</h1>
            <div class="progress-bar-container"><div id="progress" class="progress-bar"></div></div>
        </div>
        <div class="header-right">
            {f'<div class="timer-box" id="timer">--:--</div>' if timer_seconds > 0 else ''}
            <div class="score-box">Score: <span id="current-score">0.0</span> / <span id="total-q">0</span></div>
            <button class="btn btn-reset" onclick="resetProgress()">🔄 Reset</button>
        </div>
    </header>

    <div class="container" id="quiz-container"></div>

    <script>
        const questions = {q_json};
        const title = "{title}";
        const hasTimer = {str(timer_seconds > 0).lower()};
        const storageKey = "qcm_js_progress_" + btoa(unescape(encodeURIComponent(title)));
        
        let state = {{
            score: 0,
            answered: {{}},
            timeLeft: {timer_seconds}
        }};

        // Load progress
        const saved = localStorage.getItem(storageKey);
        if (saved) {{
            state = JSON.parse(saved);
        }}

        const container = document.getElementById('quiz-container');
        document.getElementById('total-q').textContent = questions.length;

        function updateGlobalUI() {{
            const answeredCount = Object.keys(state.answered).length;
            document.getElementById('progress').style.width = (answeredCount / questions.length * 100) + '%';
            document.getElementById('current-score').textContent = state.score.toFixed(1);
        }}

        function renderQuiz() {{
            container.innerHTML = '';
            questions.forEach((q, idx) => {{
                const card = document.createElement('div');
                card.className = 'card';
                card.id = 'q-' + idx;
                
                const isAnswered = state.answered[idx] !== undefined;
                const userSelected = isAnswered ? state.answered[idx].selected : (window.tempSelections && window.tempSelections[idx] ? window.tempSelections[idx] : []);

                let optionsHtml = '';
                q.opts.forEach((opt, oIdx) => {{
                    const letter = String.fromCharCode(65 + oIdx);
                    let optClass = 'option';
                    if (isAnswered) {{
                        if (q.ans.includes(letter)) optClass += ' correct-opt';
                        else if (userSelected.includes(letter)) optClass += ' incorrect-opt';
                    }} else if (userSelected.includes(letter)) {{
                        optClass += ' selected';
                    }}

                    optionsHtml += `
                        <div class="${{optClass}}" onclick="toggleOption(${{idx}}, '${{letter}}')">
                            <input type="checkbox" id="q${{idx}}o${{oIdx}}" 
                                ${{userSelected.includes(letter) ? 'checked' : ''}} 
                                ${{isAnswered ? 'disabled' : ''}}>
                            <span>${{letter}}. ${{opt}}</span>
                        </div>
                    `;
                }});

                card.innerHTML = `
                    <div class="question-text">Q${{idx + 1}}. ${{q.text}}</div>
                    <div class="options">${{optionsHtml}}</div>
                    <button class="btn" id="btn-${{idx}}" 
                        onclick="validateQuestion(${{idx}})"
                        ${{isAnswered || userSelected.length === 0 ? 'disabled' : ''}}>
                        Valider
                    </button>
                    <div class="feedback ${{isAnswered ? (state.answered[idx].score > 0 ? 'correct' : 'incorrect') : ''}}" 
                        style="display: ${{isAnswered ? 'block' : 'none'}}">
                        <strong>${{isAnswered ? (state.answered[idx].score === 1 ? 'Correct !' : (state.answered[idx].score > 0 ? 'Partiellement correct' : 'Incorrect')) : ''}}</strong>
                        <div class="explanation">💡 ${{q.expl}}</div>
                    </div>
                `;
                container.appendChild(card);
            }});
            updateGlobalUI();
        }}

        window.toggleOption = function(qIdx, letter) {{
            if (state.answered[qIdx] || state.timeUp) return;
            if (!window.tempSelections) window.tempSelections = {{}};
            if (!window.tempSelections[qIdx]) window.tempSelections[qIdx] = [];
            const idx = window.tempSelections[qIdx].indexOf(letter);
            if (idx > -1) window.tempSelections[qIdx].splice(idx, 1);
            else window.tempSelections[qIdx].push(letter);
            const card = document.getElementById('q-' + qIdx);
            const btn = document.getElementById('btn-' + qIdx);
            btn.disabled = window.tempSelections[qIdx].length === 0;
            const opts = card.querySelectorAll('.option');
            opts.forEach((o, i) => {{
                const l = String.fromCharCode(65 + i);
                if (window.tempSelections[qIdx].includes(l)) o.classList.add('selected');
                else o.classList.remove('selected');
                o.querySelector('input').checked = window.tempSelections[qIdx].includes(l);
            }});
        }};

        window.validateQuestion = function(idx) {{
            if (state.timeUp) return;
            const selected = window.tempSelections ? window.tempSelections[idx] : [];
            if (!selected || selected.length === 0) return;
            const correctAnswers = questions[idx].ans.split('');
            let correctFound = 0; let wrongFound = 0;
            selected.forEach(l => {{
                if (correctAnswers.includes(l)) correctFound++;
                else wrongFound++;
            }});
            let points = (correctFound / correctAnswers.length) - (wrongFound * 0.5);
            points = Math.max(0, points); if (points \u003e 0.99) points = 1;
            state.answered[idx] = {{ selected: selected, score: points }};
            state.score += points;
            localStorage.setItem(storageKey, JSON.stringify(state));
            renderQuiz();
        }};
        
        window.resetProgress = function() {{
            if (confirm("Voulez-vous vraiment réinitialiser ce quiz ?")) {{
                localStorage.removeItem(storageKey);
                location.reload();
            }}
        }};

        function revealAll() {{
            state.timeUp = true;
            questions.forEach((q, idx) => {{
                if (state.answered[idx] === undefined) {{
                    state.answered[idx] = {{ selected: [], score: 0 }};
                }}
            }});
            localStorage.setItem(storageKey, JSON.stringify(state));
            renderQuiz();
        }}

        if (hasTimer && !state.timeUp) {{
            const timerEl = document.getElementById('timer');
            const interval = setInterval(() => {{
                state.timeLeft--;
                const m = Math.floor(state.timeLeft / 60);
                const s = state.timeLeft % 60;
                timerEl.textContent = `${{m.toString().padStart(2, '0')}}:${{s.toString().padStart(2, '0')}}`;
                if (state.timeLeft <= 0) {{
                    clearInterval(interval);
                    revealAll();
                }} else {{
                    localStorage.setItem(storageKey, JSON.stringify(state));
                }}
            }}, 1000);
        }} else if (state.timeUp) {{
            const timerEl = document.getElementById('timer');
            if(timerEl) timerEl.textContent = "00:00";
        }}

        renderQuiz();
    </script>
</body>
</html>"""
    return html

def generate_export_html(content, title, m_type, **kwargs):
    """Dispatche vers le bon template HTML selon le type de contenu. Supporte les types BD (shorthand) et UI (longhand)."""
    # JS Quiz
    if m_type in ["QCM JS Interactif", "QCM_JS"]:
        return generate_js_quiz_html(content, title, timer_seconds=kwargs.get('timer_seconds', 0))
    # QCM Classique
    elif m_type in ["QCM Classique", "QCM"]:
        return generate_html_content(content, title, **kwargs)
    # QA
    elif m_type in ["Questions / Réponses", "QA"]:
        return generate_qa_html(content, title)
    # Glossaire
    elif m_type in ["Glossaire (Concept | Définition)", "DEF"]:
        return generate_def_html(content, title)
    # Synthèse
    elif m_type in ["Synthèse MD (Style Pro)", "Synthèse (Markdown)", "SUM"]:
        return generate_sum_html(content, title)
    return ""

def perform_stats(csv_text):
    f = io.StringIO(csv_text); reader = csv.reader(f, delimiter='|'); header = next(reader, None)
    
    ans_col_idx = -1
    if header:
        for j, col in enumerate(header):
            if col.strip().upper() in ["RÉPONSE", "REPONSE", "ANSWER"]:
                ans_col_idx = j
                break

    total, single, multi, all_ans = 0, 0, 0, []
    for row in reader:
        if not row or not any(row): continue
        if str(row[0]).strip().lower() in ["question", "titre"]: continue
        if len(row) < 7: continue
        total += 1
        
        # Identify Answer Column
        ans_idx = ans_col_idx
        if ans_idx == -1 or ans_idx >= len(row):
            ans_pattern = re.compile(r'^[A-Z]([;, ]{0,2}[A-Z])*$')
            search_limit = min(len(row) - 1, 11)
            for j in range(search_limit, 1, -1):
                val = row[j].strip().upper()
                if val and len(val) <= 15 and ans_pattern.match(val):
                    ans_idx = j
                    break
            if ans_idx == -1: ans_idx = max(1, len(row) - 2)
        
        opts = [o.strip() for o in row[1:ans_idx] if o.strip()]
        num_opts = len(opts)
        lets = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[:num_opts]
        
        raw_ans = str(row[ans_idx]).strip().upper()
        # Extract valid letters
        ans = ""
        for char in raw_ans:
            if char in lets: ans += char
            elif char in [';', ',', ' ', ':', '.', '/', '?']: continue
            else: break
            
        if len(ans) > 1: multi += 1
        else: single += 1
        for char in ans:
            if char in lets: all_ans.append(char)
    counts = Counter(all_ans); total_ans = len(all_ans) if all_ans else 1
    dist = {k: (v/total_ans * 100) for k, v in counts.items()}
    return total, single, multi, dist

def parse_csv(text):
    f = io.StringIO(text); reader = csv.reader(f, delimiter='|'); header = next(reader, None)
    
    ans_col_idx = -1
    if header:
        for j, col in enumerate(header):
            if col.strip().upper() in ["RÉPONSE", "REPONSE", "ANSWER"]:
                ans_col_idx = j
                break

    data = []
    for row in reader:
        if not row or not any(row): continue
        if str(row[0]).strip().lower() in ["question", "titre"]: continue
        if len(row) < 7: continue
        
        # Identify Answer Column
        ans_idx = ans_col_idx
        if ans_idx == -1 or ans_idx >= len(row):
            ans_pattern = re.compile(r'^[A-Z]([;, ]{0,2}[A-Z])*$')
            search_limit = min(len(row) - 1, 11)
            for j in range(search_limit, 1, -1):
                val = row[j].strip().upper()
                if val and len(val) <= 15 and ans_pattern.match(val):
                    ans_idx = j
                    break
            if ans_idx == -1: ans_idx = max(1, len(row) - 2)

        opts = [o.strip() for o in row[1:ans_idx] if o.strip()]
        num_opts = len(opts)
        lets = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[:num_opts]
        
        raw_ans = row[ans_idx].strip().upper()
        # Robust answer extraction
        ans_clean = ""
        for char in raw_ans:
            if char in lets: ans_clean += char
            elif char in [';', ',', ' ', ':', '.', '/', '?']: continue
            else: break
            
        q = {
            'text': row[0].strip(),
            'opts': opts,
            'ans': ans_clean,
            'expl': "|".join(row[ans_idx+1:])
        }
        data.append(q)
    return data

def generate_result_report(questions, user_answers, score, title, identity=None, cheat_warnings=0):
    """Génère le HTML du rapport de résultats personnalisé avec identité et stats de triche"""
    from datetime import datetime
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    name = f"{identity['prenom']} {identity['nom']}" if identity and identity['nom'] else "Étudiant Anonyme"
    user_id = f" (ID: {identity['id']})" if identity and identity['id'] else ""
    
    warnings_html = ""
    if cheat_warnings > 0:
        warnings_html = f'<p style="color:red; font-weight:bold;">⚠️ ALERTES SÉCURITÉ (Sorties d\'onglet) : {cheat_warnings}</p>'
    else:
        warnings_html = '<p style="color:green; font-weight:bold;">✅ Environnement sécurisé respecté.</p>'
    
    rows = ""
    for idx, q in enumerate(questions):
        u_ans_letters = user_answers.get(idx, "")
        is_correct = "✅" if u_ans_letters == q['ans'] else "❌"
        color = "#27ae60" if u_ans_letters == q['ans'] else "#e74c3c"
        
        mapping = {'A':0, 'B':1, 'C':2, 'D':3, 'E':4, 'F':5}
        inv_mapping = {v: k for k, v in mapping.items()}
        
        opts_html = '<ul style="list-style:none; padding-left:0; margin: 10px 0;">'
        for i, opt in enumerate(q['opts']):
            letter = inv_mapping.get(i)
            box = "[ &nbsp; ]"
            if letter in q['ans']: box = "[ X ]"
            elif letter in u_ans_letters: box = "[ x ]"
            
            line_style = "margin-bottom: 4px; font-size: 10pt;"
            if letter in q['ans']: line_style += " color: #27ae60; font-weight: bold;"
            elif letter in u_ans_letters: line_style += " color: #e74c3c;"
            opts_html += f'<li style="{line_style}">{box} {letter}. {opt}</li>'
        opts_html += "</ul>"

        rows += f"""
        <div style="margin-bottom: 30px; border-left: 6px solid {color}; padding: 15px 20px; background: #fff; box-shadow: 0 2px 4px rgba(0,0,0,0.02); border-radius: 0 8px 8px 0; page-break-inside: avoid;">
            <p style="font-family: 'Georgia', serif; font-weight:bold; font-size:12pt; margin-bottom:10px; color:#1a1a1a;">Q{idx+1}. {q['text']} {is_correct}</p>
            {opts_html}
            <div style="margin-top: 15px; border-top: 1px dashed #eee; padding-top: 10px;">
                <p style="font-family: 'Georgia', serif; font-size: 10.5pt; margin: 5px 0;"><strong>Votre sélection :</strong> <span style="color:{color}; font-weight:bold;">{u_ans_letters if u_ans_letters else "AUCUNE"}</span></p>
                <div style="font-family: 'Georgia', serif; font-size: 10pt; color: #444; background: #fdfdfd; padding: 12px; border: 1px solid #f0f0f0; border-radius: 6px; margin-top: 8px; line-height: 1.5;">
                    💡 <strong>Explication :</strong> <span style="font-style: italic;">{q['expl']}</span>
                </div>
            </div>
        </div>
        """
    
    html = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><title>Résultats {title}</title>
<style>
    body {{ font-family: 'Georgia', serif; padding: 40px; color: #333; }}
    h1 {{ color: #2c3e50; text-align: center; border-bottom: 2px solid #2c3e50; }}
    .header-box {{ background: #f8f9fa; padding: 15px; border: 1px solid #ddd; margin-bottom: 30px; border-radius: 8px; }}
    .score-box {{ background: #eef9f0; border: 2px solid #27ae60; padding: 20px; text-align: center; font-size: 18pt; margin-bottom: 30px; border-radius: 8px; }}
</style></head><body>
    <div style="max-width: 900px; margin: auto;">
        <h1>Rapport d'Examen : {title}</h1>
        <div class="header-box">
            <p><strong>Candidat :</strong> {name}{user_id}</p>
            <p><strong>Date de passage :</strong> {now}</p>
            {warnings_html}
        </div>
        <div class="score-box">Score Final : <strong>{score} / {len(questions)}</strong> ({(score/len(questions)*100):.1f}%)</div>
        <hr style="border: 0; border-top: 2px solid #eee; margin-bottom: 40px;">
        {rows}
    </div>
</body></html>"""
    return html

# --- PAGE FUNCTIONS ---

def page_pdf_transformer():
    st.header("📄 Extracteur de Documents (PDF/Word + OCR)")
    st.info("Étape 1 : Téléchargez votre document. Étape 2 : Choisissez le type d'exercice. Étape 3 : Utilisez le prompt généré avec votre IA préférée.")

    # File type selector
    file_type = st.radio("Type de document:", ["PDF", "Word (.docx)"], horizontal=True)
    
    if file_type == "PDF":
        uploaded_file = st.file_uploader("Glissez votre PDF ici", type="pdf")
        use_ocr = st.checkbox("🔍 Activer l'OCR (pour PDFs scannés)", value=False, 
                             disabled=not OCR_AVAILABLE,
                             help="OCR non disponible" if not OCR_AVAILABLE else "Active la reconnaissance optique de caractères pour documents scannés")
    else:
        uploaded_file = st.file_uploader("Glissez votre fichier Word ici", type="docx")
        use_ocr = False
    
    if uploaded_file:
        valid, msg = validate_file_upload(uploaded_file, 
                                          allowed_types=["pdf" if file_type == "PDF" else "docx"], 
                                          max_size_mb=15)
        if not valid:
            st.error(msg)
            return

        try:
            # Extract text based on file type
            if file_type == "PDF":
                if use_ocr:
                    with st.spinner("🔍 OCR en cours... Patience"):
                        pdf_text = extract_text_from_pdf(uploaded_file.read(), use_ocr=True)
                else:
                    pdf_text = extract_text_from_pdf(uploaded_file.read())
            else:  # DOCX
                pdf_text = extract_text_from_docx(uploaded_file.read())
            
            if "Erreur" in pdf_text or "[" in pdf_text[:20]:
                st.error(pdf_text)
                return
            
            st.success(f"✅ Texte extrait ! ({len(pdf_text)} caractères)")
            
            cleaned_text = " ".join(pdf_text.split())[:100000] # Limite augmentée pour les longs documents
            
            st.subheader("⚙️ Configurer l'IA")
            ex_type = st.radio("Type d'exercice souhaité :", 
                              ["QCM (Interactif)", "Q&A (Flashcards)", "Glossaire", "Synthèse"],
                              horizontal=True)
        except Exception as e:
            logger.error(f"Erreur lors de l'extraction PDF : {e}")
            st.error("Impossible de lire ce PDF. Vérifiez qu'il n'est pas protégé ou corrompu.")
            return
        
        target_lang = st.selectbox("Langue cible :", ["Français", "Arabe", "Anglais"])
        
        if ex_type == "QCM (Interactif)":
            prompt = f"""Tu es un expert en ingénierie pédagogique. À partir du texte fourni, génère un examen QCM de haute qualité.
            
            CONSIGNES STRICTES :
            1. Format : CSV strict (délimiteur '|')
            2. Colonnes : Question|A|B|C|D|E|F|Réponse|Explication
            3. Réponse : Indique la lettre (ex: A) ou les lettres (ex: AC) sans séparateur.
            4. Qualité : Crée des distracteurs plausibles. L'explication doit justifier la bonne réponse.
            5. Langue : {target_lang}.
            
            TEXTE DE RÉFÉRENCE :
            {cleaned_text}"""
            suffix = "_QCM.csv"
            
        elif ex_type == "Q&A (Flashcards)":
            prompt = f"""Génère une série de questions-réponses (Flashcards) pour aider à la mémorisation du texte suivant.
            
            CONSIGNES STRICTES :
            1. Format : CSV strict (délimiteur '|')
            2. Colonnes : Question|Réponse
            3. Langue : {target_lang}.
            
            TEXTE DE RÉFÉRENCE :
            {cleaned_text}"""
            suffix = "_QA.csv"
            
        elif ex_type == "Glossaire":
            prompt = f"""Identifie tous les concepts clés, termes techniques et définitions importantes dans le texte suivant.
            
            CONSIGNES STRICTES :
            1. Format : CSV strict (délimiteur '|')
            2. Colonnes : Concept|Définition
            3. Langue : {target_lang}.
            
            TEXTE DE RÉFÉRENCE :
            {cleaned_text}"""
            suffix = "_DEF.csv"
            
        elif ex_type == "Synthèse":
            prompt = f"""Rédige une synthèse structurée et pédagogique du texte suivant. 
            Utilise du Markdown pour la mise en forme (titres, listes, gras).
            
            CONSIGNES :
            1. Style : Clair, concis et professionnel.
            2. Langue : {target_lang}.
            3. Format : Résumé structuré.
            
            TEXTE DE RÉFÉRENCE :
            {cleaned_text}"""
            suffix = "_SUM.md"
        
        st.subheader("🤖 Votre Prompt IA")
        st.write(f"Copiez ce prompt et collez-le dans votre IA (ChatGPT, Claude, etc.) pour générer votre module `{suffix}`.")
        
        # Guide interactif rapide
        with st.expander("❓ Comment utiliser ce prompt ?"):
            st.markdown(f"""
            1. **Copiez** le texte ci-dessous.
            2. **Allez** sur [ChatGPT](https://chat.openai.com) ou [Claude.ai](https://claude.ai).
            3. **Collez** et envoyez.
            4. **Copiez** le résultat de l'IA (en ignorant le texte superflu).
            5. **Allez** dans l'onglet **'✍️ Créateur'** pour enregistrer votre module avec le suffixe `{suffix}`.
            """)
            
        st.text_area("📋 Prompt à copier :", prompt, height=300)
        
        with st.expander("🎓 Guide : Comment obtenir les meilleurs résultats avec l'IA ?", expanded=True):
            st.markdown(f"""
            ### 🚀 Étapes à suivre :
            1. **Recopie le prompt** ci-dessus.
            2. **Colle-le** dans ton IA préférée (ChatGPT, Claude, Gemini, Mistral).
            3. **Vérifie** que l'IA respecte bien le format `Question|A|B|C|D|E|F|Réponse|Explication`.
            4. **Copie le résultat CSV** généré par l'IA.
            
            ### 💡 Conseils pour un QCM de qualité :
            * **Température** : Si possible, demande à l'IA d'utiliser une `température de 0.2` pour plus de précision factuelle.
            * **Complexité** : N'hésite pas à ajouter au prompt : *"Génère des questions de niveau expert avec des pièges subtils."*
            * **Vérification** : Toujours relire les explications générées pour s'assurer qu'elles correspondent au cours.
            
            ### ⚠️ Format de fichier :
            Pour que le système reconnaisse le type de contenu automatiquement, nomme tes fichiers avec ces suffixes :
            - **_QCM.csv** : Pour les questions à choix multiples.
            - **_QA.csv** : Pour les flashcards simple Question/Réponse.
            - **_SUM.md** : Pour les synthèses et résumés.
            """)
        
        st.info(f"💡 **Conseil rapide** : Une fois le contenu généré par l'IA, utilisez l'onglet **'Créateur'** pour l'enregistrer avec le suffixe `{suffix}`.")

def page_pdf_merger():
    st.header("📄 Fusionneur de PDF (Merger)")
    st.info("Téléchargez plusieurs PDF et réorganisez-les avant de les fusionner en un seul fichier.")
    
    uploaded_files = st.file_uploader("Choisissez vos fichiers PDF", type="pdf", accept_multiple_files=True)
    
    if uploaded_files:
        st.subheader("🔄 Ordre des fichiers")
        # Interface de tri simplifiée avec st.multiselect
        filenames = [f.name for f in uploaded_files]
        ordered_filenames = st.multiselect(
            "Réorganisez l'ordre (Sélectionnez dans l'ordre voulu) :",
            filenames,
            default=filenames,
            help="L'ordre de sélection déterminera l'ordre dans le PDF final."
        )
        
        if st.button("🚀 Fusionner les PDF", type="primary", use_container_width=True):
            if not ordered_filenames:
                st.warning("Veuillez sélectionner au moins un fichier.")
                return
                
            try:
                merger = PyPDF2.PdfMerger()
                # Map ordered names back to file objects
                file_map = {f.name: f for f in uploaded_files}
                
                with st.spinner("Fusion en cours..."):
                    for name in ordered_filenames:
                        # Reset file pointer to beginning before reading
                        file_map[name].seek(0)
                        merger.append(io.BytesIO(file_map[name].read()))
                    
                    output = io.BytesIO()
                    merger.write(output)
                    merger.close()
                    
                    st.success("✅ Fusion terminée !")
                    st.download_button(
                        label="📥 Télécharger le PDF fusionné",
                        data=output.getvalue(),
                        file_name="fusion_combinee.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )
            except Exception as e:
                st.error(f"Erreur lors de la fusion : {e}")
                logger.error(f"Erreur PDF Merger: {e}")

def page_creator():
    st.header("✍️ Créateur de Contenu (HTML/PDF)")
    
    with st.sidebar:
        st.subheader("⚙️ Configuration")
        module_title = st.text_input("Titre du Module", value=st.session_state.get('editing_name', "Nouveau Module"))
        
        q_types = ["QCM Classique", "QCM JS Interactif", "Questions / Réponses", "Glossaire (Concept | Définition)", "Synthèse MD (Style Pro)"]
        q_type = st.radio("Type", q_types, 
                          index=q_types.index(st.session_state.get('editing_type', "QCM Classique")))

        # Manual Save Button
        if st.button("💾 Enregistrer dans la base", use_container_width=True, type="primary"):
            if module_title and module_title != "Nouveau Module" and st.session_state.get("csv_source_input"):
                try:
                    m_type_db = "QCM"
                    if "Interactive" in q_type or "JS" in q_type: m_type_db = "QCM_JS"
                    elif "Questions" in q_type: m_type_db = "QA"
                    elif "Glossaire" in q_type: m_type_db = "DEF"
                    elif "Synthèse" in q_type: m_type_db = "SUM"
                    
                    db_save_module(module_title, "Général", m_type_db, st.session_state.csv_source_input)
                    st.toast(f"✅ Module enregistré : {module_title}", icon="💾")
                except Exception as e:
                    st.error(f"Erreur lors de l'enregistrement : {e}")
                    logger.error(f"Erreur save manuelle: {e}")
            else:
                st.warning("Veuillez saisir un titre et du contenu avant d'enregistrer.")

        # out_name and doc_title are now the same
        out_name = module_title
        doc_title = module_title
        
        html_mode = st.radio("Style", ["Examen", "Révision"])
        
        timer_active = st.checkbox("⏱️ Activer Minuteur", value=False)
        timer_seconds = 0
        if timer_active:
            timer_min = st.number_input("Minutes", 1, 120, 15)
            timer_seconds = timer_min * 60

        c1, c2 = st.columns(2)
        shuffle_q = c1.checkbox("Mélanger Q", value=False)
        shuffle_o = c2.checkbox("Mélanger O", value=False)
        use_3_col = st.checkbox("3 Colonnes", value=True)
        add_qr = st.checkbox("QR Code", value=True)
        add_sheet = st.checkbox("Feuille Réponses", value=True)
        open_all = False
        if "Questions" in q_type:
            open_all = st.checkbox("Ouvrir tout", value=False)

    # The title is handled by module_title above

    default_val = st.session_state.get("csv_source_input", "")
    if not default_val:
        default_val = st.session_state.get("pdf_extracted_text", "")
        
    csv_in = st.text_area("Contenu (|)", height=250, value=default_val)
    st.session_state.csv_source_input = csv_in
    
    if csv_in and module_title and module_title != "Nouveau Module":
        errors, _ = validate_csv_data(csv_in, q_type)
        if errors:
            for e in errors: st.error(e)

        # --- STATS ---
        try:
            total_stats, sing_stats, mult_stats, dist_stats = perform_stats(csv_in)
            st.divider()
            st.subheader("📊 Statistiques")
            s1, s2, s3 = st.columns(3)
            s1.metric("Total", total_stats)
            s2.metric("Unique", sing_stats)
            s3.metric("Multiple", mult_stats)
            dist_str = " | ".join([f"**{k}**: {v:.1f}%" for k, v in sorted(dist_stats.items())])
            st.info(f"📍 Distribution : {dist_str}")
        except: pass

        # Generate HTML with the correct template
        html_out = generate_export_html(csv_in, doc_title, q_type, 
                                        use_columns=use_3_col, add_qr=add_qr, mode=html_mode,
                                        shuffle_q=shuffle_q, shuffle_o=shuffle_o, add_sheet=add_sheet,
                                        open_all=open_all, timer_seconds=timer_seconds)
        
        c1, c2 = st.columns(2)
        with c1:
            st.download_button("📥 Télécharger HTML", html_out, f"{out_name}.html")
        with c2:
            pdf_bytes = convert_html_to_pdf(html_out)
            if pdf_bytes: st.download_button("📄 TÉLÉCHARGER PDF", pdf_bytes, f"{out_name}.pdf")
        
        st.subheader("👁️ Aperçu")
        st.components.v1.html(html_out, height=600, scrolling=True)

def page_quiz():
    # Sidebar config for Quiz Page (keep only rev_mode here)
    with st.sidebar:
        st.divider()
        st.subheader("📖 Mode Révision")
        rev_mode = st.toggle("Activer Flashcards QCM", value=False)
        shuffle_q = st.toggle("Mélanger les questions", value=False)
        shuffle_o = st.toggle("Mélanger les options", value=True)
    
    st.header("⚡ Mode Quiz Flash Interactif")
    
    # Handle pre-loaded module from Explorer or Resume logic
    if "auto_load_csv" in st.session_state and st.session_state.auto_load_csv:
        st.session_state.quiz_csv_area = st.session_state.auto_load_csv
        st.session_state.csv_source_input = st.session_state.auto_load_csv
        st.session_state.auto_load_csv = None
        st.info(f"📦 Module '{st.session_state.get('quiz_mod')}' chargé.")

    if not st.session_state.quiz_started and not st.session_state.score_submitted:
        # Resume Check
        mod_name = st.session_state.get("quiz_mod")
        if st.session_state.identity["verified"] and mod_name and mod_name != "Choisir...":
            progress = db_load_progress(st.session_state.identity["email"], mod_name)
            if progress:
                st.success(f"⏳ Progression trouvée : Question {progress['idx']+1}.")
                c1, c2 = st.columns(2)
                if c1.button("▶ REPRENDRE", type="primary"):
                    st.session_state.quiz_started = True
                    st.session_state.current_course_name = mod_name
                    st.session_state.shuffled_questions = parse_csv(st.session_state.csv_source_input)
                    st.session_state.current_q_idx = progress['idx']
                    st.session_state.user_answers = {int(k): v for k, v in progress['answers'].items()}
                    st.session_state.validated_current = False
                    st.session_state.start_time = time.time()
                    st.rerun()
                if c2.button("🔄 RECOMMENCER"):
                    db_clear_progress(st.session_state.identity["email"], mod_name)
                    st.info("Progression réinitialisée.")
                    st.rerun()

        # --- MODULE LOADING Logic (SQL Based) ---
        st.subheader("📂 Charger un module")
        all_modules = db_get_modules(m_type="QCM")
        if all_modules:
            mod_options = {f"{m[1]}": m for m in all_modules}
            sel_mod_name = st.selectbox("Module", ["Choisir..."] + list(mod_options.keys()), key="quiz_mod_sel")
            if sel_mod_name != "Choisir...":
                selected_module = mod_options[sel_mod_name]
                if st.button("📥 Charger ce module"):
                    st.session_state.quiz_csv_area = selected_module[4]
                    st.session_state.csv_source_input = selected_module[4]
                    st.session_state.quiz_mod = selected_module[1]
                    st.success(f"Module '{selected_module[1]}' chargé !")
                    st.rerun()
        else:
            st.info("💡 Aucun module de type 'QCM' trouvé. Utilisez le 'Créateur' pour en enregistrer un.")

        csv_quiz = st.text_area("Source CSV du Quiz", height=150, value=st.session_state.get("csv_source_input", ""), key="quiz_csv_area")
        
        # --- COMPACT CANDIDATE INFO ---
        st.subheader("👤 Informations Candidat")
        c1, c2, c3 = st.columns(3)
        st.session_state.identity["nom"] = c1.text_input("Nom", value=st.session_state.identity["nom"], placeholder="Nom")
        st.session_state.identity["prenom"] = c2.text_input("Prénom", value=st.session_state.identity["prenom"], placeholder="Prénom")
        st.session_state.identity["id"] = c3.text_input("Numéro ID", value=st.session_state.identity["id"], placeholder="CNE / ID")
        
        if not st.session_state.identity["verified"]:
            st.caption("ℹ️ Connectez-vous dans 'Historique' pour l'auto-enregistrement des scores.")

        if st.button("🚀 DÉMARRER L'EXAMEN BLANC", type="primary", use_container_width=True):
            if not csv_quiz: st.error("Collez ou chargez un CSV !")
            else:
                st.session_state.quiz_started = True
                st.session_state.start_time = time.time()
                st.session_state.user_answers = {}
                
                # Identify course name for history
                mod_name = st.session_state.get("quiz_mod", "Quiz Manuel")
                st.session_state.current_course_name = mod_name if mod_name != "Choisir..." else "Quiz Manuel"
                # Parsing and Shuffling
                questions = parse_csv(csv_quiz)
                if shuffle_q:
                    questions = random.sample(questions, len(questions))
                
                if shuffle_o:
                    for q_item in questions:
                        if len(q_item['opts']) > 1:
                            # 1. Identify original answer(s) text
                            original_ans_letters = list(q_item['ans']) # can be 'AB'
                            letters = ['A', 'B', 'C', 'D', 'E', 'F']
                            correct_texts = [q_item['opts'][letters.index(l)] for l in original_ans_letters if letters.index(l) < len(q_item['opts'])]
                            
                            # 2. Shuffle options
                            random.shuffle(q_item['opts'])
                            
                            # 3. Update answer field with new letters
                            new_ans_letters = []
                            for i, opt_text in enumerate(q_item['opts']):
                                if opt_text in correct_texts:
                                    new_ans_letters.append(letters[i])
                            q_item['ans'] = "".join(sorted(new_ans_letters))

                st.session_state.shuffled_questions = questions
                st.session_state.current_q_idx = 0
                st.session_state.validated_current = False
                st.session_state.score_submitted = False
                st.rerun()
    elif st.session_state.quiz_started:
        questions = st.session_state.shuffled_questions
        num_q = len(questions)
        idx = st.session_state.current_q_idx
        q = questions[idx]
        
        st.progress((idx + 1) / num_q)
        
        # --- COMPACT HEADER ---
        head_c1, head_c2, head_c3 = st.columns([0.2, 0.6, 0.2])
        head_c1.markdown(f"📝 **Q. {idx+1} / {num_q}**")
        head_c2.markdown(f"<div style='text-align:center; font-style:italic;'>{st.session_state.current_course_name}</div>", unsafe_allow_html=True)
        if head_c3.button("🚪 QUITTER", use_container_width=True, help="Sortir de l'examen"):
            st.session_state.confirm_exit = True
            st.rerun()

        if st.session_state.confirm_exit:
            st.warning("⚠️ Confirmer la sortie ?")
            exit_c1, exit_c2 = st.columns(2)
            if exit_c1.button("✅ OUI", type="primary", use_container_width=True):
                st.session_state.confirm_exit = False
                st.session_state.quiz_started = False
                st.rerun()
            if exit_c2.button("❌ NON", use_container_width=True):
                st.session_state.confirm_exit = False
                st.rerun()
            st.stop()
        
        st.markdown(f"### {q['text']}")
        st.markdown("<br>", unsafe_allow_html=True) # Subtle spacing
        
        letters = ['A', 'B', 'C', 'D', 'E', 'F'][:len(q['opts'])]
        
        if rev_mode:
            # FLASHCARD QCM LOGIC
            if not st.session_state.validated_current:
                if st.button("▶ RÉVÉLER LES RÉPONSES", type="primary", use_container_width=True):
                    st.session_state.validated_current = True
                    st.rerun()
            else:
                # Show choices with answer highlighted
                options_html = '<div style="margin: 15px 0;">'
                for i, l in enumerate(letters):
                    is_correct = l in q['ans']
                    bg = "#d4edda" if is_correct else "transparent"
                    border = "#28a745" if is_correct else "#ddd"
                    icon = "✅" if is_correct else ""
                    options_html += f'<div style="padding: 12px; margin-bottom: 10px; border: 1px solid {border}; border-radius: 10px; background-color: {bg}; font-size: 14pt;"><strong>{l}.</strong> {q["opts"][i]} <span style="float: right;">{icon}</span></div>'
                options_html += "</div>"
                st.markdown(options_html, unsafe_allow_html=True)
                st.info(f"💡 **Explication** : {q['expl']}")
                if idx < num_q - 1:
                    if st.button("➡️ SUIVANT", type="primary", use_container_width=True):
                        st.session_state.current_q_idx += 1
                        st.session_state.validated_current = False
                        st.rerun()
                else: 
                    st.success("Module terminé !")
            st.stop() # Skip standard quiz logic if in rev_mode

        selected = []
        if not st.session_state.validated_current:
            # Force uniform checkbox interface for all questions
            for i, l in enumerate(letters):
                prev_val = l in st.session_state.user_answers.get(idx, "")
                if st.checkbox(f"{l}. {q['opts'][i]}", key=f"q{idx}_{l}", value=prev_val):
                    selected.append(l)
            
            st.session_state.user_answers[idx] = "".join(sorted(selected))
        else:
            # RENDER COLORED FEEDBACK (STATIC HTML)
            u_ans = st.session_state.user_answers.get(idx, "")
            options_html = '<div style="margin: 15px 0;">'
            for i, l in enumerate(letters):
                is_correct = l in q['ans']
                is_chosen = l in u_ans
                
                bg_color = "transparent"
                border_color = "#ddd"
                icon = ""
                text_color = "#333"
                
                if is_chosen:
                    if is_correct:
                        bg_color = "#d4edda"
                        border_color = "#28a745"
                        icon = "✅ "
                    else:
                        bg_color = "#f8d7da"
                        border_color = "#dc3545"
                        icon = "❌ "
                elif is_correct:
                    border_color = "#28a745" 
                    bg_color = "#f0fff4"
                
                options_html += f'<div style="padding: 12px; margin-bottom: 10px; border: 1px solid {border_color}; border-radius: 10px; background-color: {bg_color}; color: {text_color}; font-size: 11pt;"><strong>{l}.</strong> {q["opts"][i]} <span style="float: right;">{icon}</span></div>'
            options_html += "</div>"
            st.markdown(options_html, unsafe_allow_html=True)
        
        st.markdown('---')
        
        if not st.session_state.validated_current:
            is_disabled = (not selected)
            if is_disabled:
                st.info("💡 Sélectionnez au moins une réponse pour valider.")
            
            if st.button("✔️ VALIDER POUR VOIR LA RÉPONSE", type="primary", use_container_width=True, disabled=is_disabled):
                st.session_state.validated_current = True
                # SAVE PROGRESS TO DB
                if st.session_state.identity["verified"] and st.session_state.current_course_name != "Quiz Manuel":
                    db_save_progress(st.session_state.identity["email"], st.session_state.current_course_name, idx, st.session_state.user_answers)
                st.rerun()
        else:
            # SHOW FEEDBACK
            u_ans = st.session_state.user_answers.get(idx, "") or "NULL"
            if u_ans == q['ans']:
                st.success(f"✅ Correct ! La réponse était : {q['ans']}")
            else:
                st.error(f"❌ Incorrect. Votre réponse : {u_ans} | Bonne réponse : {q['ans']}")
            
            st.info(f"💡 **Explication** : {q['expl']}")
            
            # --- FAVORITES BUTTON ---
            email = st.session_state.identity.get("email", "anonyme")
            c_fav, c_nav = st.columns([1, 2])
            with c_fav:
                if st.button("⭐ Favori", use_container_width=True, key=f"fav_click_{idx}"):
                    new_status = db_toggle_favorite(email, st.session_state.current_course_name, q['text'], q['opts'], q['ans'], q['expl'])
                    if new_status == "added": st.toast("Ajouté aux favoris !")
                    else: st.toast("Retiré des favoris.")
            
            with c_nav:
                if idx < num_q - 1:
                    if st.button("➡️ QUESTION SUIVANTE", type="primary", use_container_width=True):
                        st.session_state.current_q_idx += 1
                        st.session_state.validated_current = False
                        st.rerun()
                else:
                    if st.button("🏁 TERMINER L'EXAMEN", type="primary", use_container_width=True):
                        st.session_state.quiz_started = False
                        st.session_state.score_submitted = True
                        
                        # Recalculate score with partial credits
                        questions = st.session_state.shuffled_questions
                        total_score = 0.0
                        for i, q_data in enumerate(questions):
                            u_ans = st.session_state.user_answers.get(i, "")
                            correct_ans = q_data['ans']
                            
                            if u_ans == correct_ans:
                                total_score += 1.0
                            elif len(correct_ans) > 1: # Partial scoring for multi-choice
                                # Formula: max(0, (Corrects_choisis - Incorrects_choisis) / Total_Corrects)
                                set_correct = set(correct_ans)
                                set_user = set(u_ans)
                                
                                correct_chosen = len(set_user.intersection(set_correct))
                                incorrect_chosen = len(set_user.difference(set_correct))
                                
                                q_score = max(0.0, (correct_chosen - incorrect_chosen) / len(set_correct))
                                total_score += q_score
                        
                        st.session_state.final_score = total_score
                        st.session_state.final_total = len(questions)
                        
                        if st.session_state.identity["verified"]:
                            db_save_score(st.session_state.identity["email"], st.session_state.current_course_name, total_score, len(questions))
                            db_clear_progress(st.session_state.identity["email"], st.session_state.current_course_name)
                        st.rerun()

    if st.session_state.score_submitted:
        score = st.session_state.get('final_score', 0)
        num_q = st.session_state.get('final_total', 1)
        
        st.balloons()
        st.markdown(f"""
            <div style="text-align:center; padding:30px; background:#f0f7f4; border-radius:15px; border:2px solid #27ae60; margin-bottom: 20px;">
                <h1 style="color:#27ae60; margin:0;">SCORE FINAL : {score:.1f} / {num_q}</h1>
                <p style="font-size:16pt;">Candidat : <strong>{st.session_state.identity['prenom']} {st.session_state.identity['nom']}</strong></p>
                <p style="font-size:14pt;">Taux de réussite : <strong>{(score/num_q*100):.1f}%</strong></p>
            </div>
        """, unsafe_allow_html=True)
        
        # --- CERTIFICATE BUTTON ---
        if (score / num_q) >= 0.8:
            st.success("🏆 Félicitations ! Vous avez réussi l'examen avec brio.")
            user_full_name = f"{st.session_state.identity['prenom']} {st.session_state.identity['nom']}"
            cert_html = generate_certificate_html(user_full_name, st.session_state.current_course_name, score, num_q)
            cert_pdf = convert_html_to_pdf(cert_html)
            if cert_pdf:
                st.download_button(
                    "🎓 Télécharger mon Diplôme (PDF)",
                    data=cert_pdf,
                    file_name=f"Certificat_{st.session_state.current_course_name}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )

        # --- RESULTS & PDF REPORT ---
        questions = st.session_state.get('shuffled_questions', [])
        result_html = generate_result_report(questions, st.session_state.user_answers, score, "Examen Officiel", 
                                             identity=st.session_state.identity, 
                                             cheat_warnings=st.session_state.cheat_warnings)
        result_pdf = convert_html_to_pdf(result_html)
        if result_pdf:
            st.download_button("📄 TÉLÉCHARGER MON COMPTE-RENDU (PDF)", result_pdf, f"resultats_{st.session_state.identity['nom']}.pdf", mime="application/pdf", use_container_width=True)
        
        if st.button("🔄 REFAIRE UN QUIZ"):
            st.session_state.score_submitted = False
            st.session_state.quiz_started = False
            st.session_state.user_answers = {}
            st.rerun()

        st.subheader("📝 Correction détaillée")
        for idx, q in enumerate(questions):
            u_ans = st.session_state.user_answers.get(idx, "") or "NULL"
            if u_ans == q['ans']:
                st.success(f"**Q{idx+1}**: Correct ! Votre réponse : {u_ans}")
            else:
                st.error(f"**Q{idx+1}**: Incorrect. Votre réponse : {u_ans} | Correcte : {q['ans']}")
                st.info(f"💡 **Explication** : {q['expl']}")

def page_history():
    st.header("📊 Mon Historique & Compte")
    
    if not st.session_state.identity["verified"]:
        st.subheader("🔐 Connexion (Simulation)")
        email = st.text_input("Votre Email")
        if st.button("Recevoir le Code"):
            st.session_state.verification_code = "1234" # Simulation
            st.info("Simulation : Votre code est 1234")
        
        code = st.text_input("Code reçu")
        if st.button("Vérifier"):
            if code == "1234":
                st.session_state.identity["email"] = email
                st.session_state.identity["verified"] = True
                # Persist to DB
                db_save_user(email, st.session_state.identity["nom"], st.session_state.identity["prenom"], st.session_state.identity["id"])
                st.success("Connecté !")
                st.rerun()
            else:
                st.error("Code incorrect.")
    else:
        st.write(f"Connecté en tant que : **{st.session_state.identity['email']}**")
        if st.button("🚪 Déconnexion"):
            st.session_state.identity["verified"] = False
            st.rerun()
            
        st.subheader("👤 Mon Profil")
        st.write(f"Nom : **{st.session_state.identity['nom']}**")
        st.write(f"Prénom : **{st.session_state.identity['prenom']}**")
        
        st.subheader("📈 Mes derniers scores (Base de Données)")
        df_db = db_get_history(st.session_state.identity["email"])
        if df_db.empty:
            st.info("Aucun historique pour le moment.")
        else:
            st.table(df_db)
            
            # Export options
            st.divider()
            st.subheader("📥 Exporter mes données")
            col1, col2, col3 = st.columns(3)
            
            with col1:
                csv_data = df_db.to_csv(index=False)
                st.download_button(
                    "📊 CSV",
                    data=csv_data,
                    file_name=f"historique_{st.session_state.identity['email']}.csv",
                    mime="text/csv"
                )
            
            with col2:
                json_data = df_db.to_json(orient='records', indent=2)
                st.download_button(
                    "📋 JSON",
                    data=json_data,
                    file_name=f"historique_{st.session_state.identity['email']}.json",
                    mime="application/json"
                )
            
            with col3:
                # Full user data export (RGPD)
                user_data = db_export_all_user_data(st.session_state.identity['email'])
                full_json = json_lib.dumps(user_data, indent=2, ensure_ascii=False)
                st.download_button(
                    "🗂️ Toutes mes données",
                    data=full_json,
                    file_name=f"donnees_completes_{st.session_state.identity['email']}.json",
                    mime="application/json",
                    help="Export complet conforme RGPD"
                )
        
        # Recommendations section
        st.divider()
        st.subheader("💡 Modules recommandés pour vous")
        recommendations = get_user_recommendations(st.session_state.identity['email'], limit=3)
        
        if recommendations:
            for module_name, reason, category in recommendations:
                with st.container():
                    col_icon, col_info, col_action = st.columns([1, 5, 2])
                    with col_icon:
                        st.markdown("### 📚")
                    with col_info:
                        st.markdown(f"**{module_name}**")
                        st.caption(f"📂 {category} • {reason}")
                    with col_action:
                        if st.button("🚀 Lancer", key=f"rec_{module_name}"):
                            # Load this module
                            modules = db_get_modules()
                            target_mod = [m for m in modules if m[1] == module_name]
                            if target_mod:
                                m = target_mod[0]
                                st.session_state.auto_load_csv = m[4]  # content
                                st.session_state.quiz_mod = m[1]  # name
                                st.session_state.current_page = "⚡ Quiz Interactif"
                                st.rerun()
                    st.markdown("---")
        else:
            st.info("Aucune recommandation pour le moment.")

def page_discover():
    st.markdown("""
    <style>
    .module-card {
        background: white; border-radius: 12px; padding: 20px;
        box-shadow: 0 4px 10px rgba(0,0,0,0.05); border: 1px solid #f0f0f0;
        transition: transform 0.2s; margin-bottom: 20px;
        display: flex; flex-direction: column; gap: 15px;
    }
    .module-card:hover { transform: translateY(-5px); box-shadow: 0 8px 15px rgba(0,0,0,0.08); }
    .card-header { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
    .icon-box { background: #f8fafc; padding: 10px; border-radius: 50%; font-size: 1.4em; }
    .module-name { font-weight: 700; font-size: 1.05em; color: #1e293b; margin: 0; }
    .type-badge { font-size: 0.75em; background: #f1f5f9; color: #64748b; padding: 2px 8px; border-radius: 10px; text-transform: uppercase; font-weight: 600; }
    .best-score { background: #fffbeb; color: #d97706; padding: 4px 12px; border-radius: 15px; font-size: 0.8em; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

    st.header("🔍 Explorateur de Modules (BD)")
    
    search_q = st.text_input("🔍 Rechercher un module...", "")
    
    # Pagination state
    if 'discover_page' not in st.session_state:
        st.session_state.discover_page = 0
    
    PAGE_SIZE = 20
    offset = st.session_state.discover_page * PAGE_SIZE
    
    # Get modules with pagination
    all_modules = db_get_modules(search=search_q, limit=PAGE_SIZE + 1, offset=offset)
    has_more = len(all_modules) > PAGE_SIZE
    display_modules = all_modules[:PAGE_SIZE]
    
    total_count = db_count_modules(search=search_q)
    
    if not display_modules:
        st.info("Aucun module trouvé dans la base de données. Utilisez le 'Créateur' pour en ajouter.")
        return
    
    # Stats
    st.caption(f"📊 {total_count} module(s) au total • Page {st.session_state.discover_page + 1}")

    categories = sorted(list(set([m[2] for m in display_modules if m[2]])))
    if not categories: categories = ["Général"]
    
    tabs = st.tabs([f"📂 {cat}" for cat in categories])
    
    for i, cat in enumerate(categories):
        with tabs[i]:
            # Filter modules for this category
            cat_modules = [m for m in display_modules if m[2] == cat]
            
            if not cat_modules:
                st.info("Catégorie vide.")
                continue
            
            cols = st.columns(2)
            for idx, mod in enumerate(cat_modules):
                m_id, m_name, m_cat, m_type, m_content, m_date = mod
                with cols[idx % 2]:
                    best = "N/A"
                    progress = False
                    if m_type in ["QCM", "QCM_JS"] and st.session_state.identity["verified"]:
                        best = db_get_best_score(st.session_state.identity["email"], m_name)
                        p_data = db_load_progress(st.session_state.identity["email"], m_name)
                        if p_data: progress = True
                    
                    icons = {"QCM": "⚡", "QCM_JS": "🕹️", "QA": "❓", "DEF": "📜", "SUM": "📝"}
                    icon = icons.get(m_type, "📄")

                    with st.container():
                        card_html = f"""<div class="module-card">
<div class="card-header">
<div class="icon-box">{icon}</div>
<div>
    <p class="module-name">{m_name}</p>
    <span class="type-badge">{m_type}</span>
</div>
</div>
<div>
{f'<span class="best-score">🏆 Record : {best}</span>' if m_type in ["QCM", "QCM_JS"] else ""}
{"<span class='in-progress'>⏳ En cours</span>" if progress else ""}
</div>
</div>"""
                        st.markdown(card_html, unsafe_allow_html=True)
                        
                        # Actions directly below card content but visually inside
                        ac1, ac2 = st.columns(2)
                        if m_type in ["QCM", "QCM_JS"]:
                            if ac1.button("🚀 Lancer", key=f"launch_{m_id}", use_container_width=True):
                                st.session_state.auto_load_csv = m_content
                                st.session_state.quiz_mod = m_name
                                st.session_state.current_page = "⚡ Quiz Interactif"
                                st.rerun()
                        else:
                            if ac1.button("👁️ Voir", key=f"view_{m_id}", use_container_width=True):
                                # Open directly in local browser
                                if open_local_html(m_content, m_name, m_type):
                                    st.toast(f"🌐 Ouverture de l'aperçu : {m_name}")
                                else:
                                    st.error("Impossible d'ouvrir l'aperçu HTML local.")
                                # We still set the view_content for the internal visualizer as fallback
                                st.session_state.view_content = {"name": m_name, "content": m_content, "type": m_type}
                                st.session_state.current_page = "👁️ Visualiseur"
                                st.rerun()
                        
                        # --- Multi-format Exports ---
                        with ac2.expander("📥 Export", expanded=False):
                            d_col1, d_col2, d_col3 = st.columns(3)
                            d_col1.download_button("CSV", m_content, f"{m_name}.csv", key=f"ex_csv_{m_id}", help="CSV")
                            html_exp = generate_export_html(m_content, m_name, m_type)
                            d_col2.download_button("HTM", html_exp, f"{m_name}.html", key=f"ex_htm_{m_id}", help="HTML")
                            pdf_exp = convert_html_to_pdf(html_exp)
                            if pdf_exp:
                                with d_col3.popover("⚙️"):
                                    st.write("🔧 PDF Master")
                                    zoom_val = st.slider("Zoom", 0.5, 2.0, 1.0, 0.1, key=f"zoom_{m_id}")
                                    target_p = st.number_input("Pages visées", 0, 10, 0, key=f"p_{m_id}", help="0 pour auto")
                                    
                                    # Heuristic: if target_p > 0, we adjust zoom
                                    # (very rough estimate: 1 page ~= 1.0 zoom for typical 20q QCM)
                                    final_zoom = zoom_val
                                    if target_p > 0:
                                        # Assume 1.0 zoom = 2 pages for 50 questions
                                        # Let's use a dynamic factor
                                        total_q = m_content.count('\n') # Row count estimate
                                        est_p = (total_q * 0.05) if m_type == "QCM" else (total_q * 0.08)
                                        if est_p > 0:
                                            final_zoom = min(zoom_val, (target_p / est_p))
                                    
                                    scaled_pdf = convert_html_to_pdf(html_exp, zoom=final_zoom)
                                    if scaled_pdf:
                                        st.download_button("⬇️ Télécharger", scaled_pdf, f"{m_name}.pdf", key=f"dl_pdf_{m_id}", use_container_width=True)
                            else:
                                d_col3.caption("X")
                        st.write("---")
    
    # Pagination controls
    st.divider()
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if st.session_state.discover_page > 0:
            if st.button("⬅️ Page précédente"):
                st.session_state.discover_page -= 1
                st.rerun()
    with col3:
        if has_more:
            if st.button("Page suivante ➡️"):
                st.session_state.discover_page += 1
                st.rerun()

def page_visualizer():
    v = st.session_state.view_content
    if not v["name"]:
        st.warning("Aucun contenu à visualiser.")
        if st.button("Retour à l'Explorateur"):
            st.session_state.current_page = "🔍 Explorer"
            st.rerun()
        return

    col_h1, col_h2 = st.columns([0.8, 0.2])
    col_h1.header(f"👁️ Visualisation : {v['name']}")
    if col_h2.button("🔙 Retour", use_container_width=True):
        st.session_state.current_page = "🔍 Explorer"
        st.rerun()

    st.divider()
    
    if v["type"] == "SUM":
        st.markdown(f"""
        <div style="font-family: 'Inter', sans-serif; color: #334155; line-height: 1.7;">
            {v["content"]}
        </div>
        """, unsafe_allow_html=True)
    elif v["type"] == "QA":
        # Simple parsing for Q&A
        lines = v["content"].split("\n")
        for line in lines:
            if line.strip().startswith("Q:"):
                st.markdown(f"#### ❓ {line.strip()[2:]}")
            elif line.strip().startswith("R:"):
                st.markdown(f"> **Réponse :** {line.strip()[2:]}")
                st.divider()
    elif v["type"] == "DEF":
        # Definitions look
        lines = v["content"].split("\n")
        for line in lines:
            if "|" in line:
                concept, definition = line.split("|", 1)
                st.markdown(f"### 📜 {concept.strip()}")
                st.info(definition.strip())
    else:
        st.code(v["content"])

def page_admin_crud():
    st.header("⚙️ Gestion Administrative (CRUD)")
    st.info("Gérez ici tous les contenus stockés dans la base de données SQLite.")
    
    # System utilities section
    with st.expander("🛠️ Utilitaires Système"):
        col_util1, col_util2, col_util3 = st.columns(3)
        
        with col_util1:
            st.subheader("🧹 LocalStorage")
            if st.button("🗑️ Vider LocalStorage", help="Supprime toutes les données en cache du navigateur"):
                st.components.v1.html("""
                <script>
                localStorage.clear();
                sessionStorage.clear();
                alert('LocalStorage et SessionStorage vidés !');
                </script>
                """, height=0)
                st.success("LocalStorage vidé !")
        
        with col_util2:
            st.subheader("🔄 Base de Données")
            if st.button("🧹 Supprimer Doublons", help="Supprime les modules en double"):
                with db_context() as conn:
                    c = conn.cursor()
                    # Find and remove duplicates, keeping the latest one
                    c.execute("""
                        DELETE FROM educational_modules 
                        WHERE id NOT IN (
                            SELECT MAX(id) 
                            FROM educational_modules 
                            GROUP BY name, type, category
                        )
                    """)
                    deleted = c.rowcount
                    conn.commit()
                st.success(f"✅ {deleted} doublon(s) supprimé(s)")
        
        with col_util3:
            st.subheader("📊 Statistiques")
            with db_context() as conn:
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM educational_modules")
                total_modules = c.fetchone()[0]
                c.execute("SELECT COUNT(DISTINCT email) FROM users")
                total_users = c.fetchone()[0]
                c.execute("SELECT COUNT(*) FROM history")
                total_attempts = c.fetchone()[0]
            
            st.metric("Modules totaux", total_modules)
            st.metric("Utilisateurs", total_users)
            st.metric("Tentatives quiz", total_attempts)
    
    st.divider()
    
    # Bulk export options
    col_search, col_zip, col_excel = st.columns([2, 1, 1])
    with col_search:
        search = st.text_input("🔍 Rechercher dans toute la base...", "")
    with col_zip:
        st.write("")  # Spacing
        if st.button("📦 Export ZIP", use_container_width=True):
            with st.spinner("Création du ZIP..."):
                zip_data = create_bulk_export_zip()
                if zip_data:
                    st.download_button("⬇️ ZIP", data=zip_data, file_name=f"modules_{datetime.datetime.now().strftime('%Y%m%d')}.zip", mime="application/zip")
    with col_excel:
        st.write("")
        excel_data = db_export_to_excel()
        st.download_button("📊 Excel Complet", data=excel_data, file_name=f"BD_Master_{datetime.datetime.now().strftime('%Y%m%d')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    
    tabs = st.tabs(["⚡ QCM", "❓ Q&A", "📜 Définitions", "📝 Résumés"])
    types_map = {"⚡ QCM": "QCM", "❓ Q&A": "QA", "📜 Définitions": "DEF", "📝 Résumés": "SUM"}

    for t_name, t_code in types_map.items():
        with tabs[list(types_map.keys()).index(t_name)]:
            mods = db_get_modules(m_type=t_code, search=search)
            if not mods:
                st.warning(f"Aucun contenu de type {t_code} trouvé.")
                continue

            # --- DASHBOARD HEADER ---
            h1, h2, h3, h4 = st.columns([3, 1.5, 2.5, 3])
            h1.markdown("**Nom du Module**")
            h2.markdown("**Date**")
            h3.markdown("**Formats**")
            h4.markdown("**Actions**")
            st.divider()

            for m in mods:
                mid, mname, mcat, mtype, mcont, mdate = m
                r1, r2, r3, r4 = st.columns([3, 1.5, 2.5, 3])
                
                # Column 1: Name & Type
                icons = {"QCM": "⚡", "QA": "❓", "DEF": "📜", "SUM": "📝"}
                icon = icons.get(mtype, "📄")
                r1.markdown(f"{icon} **{mname}**")
                
                # Column 2: Date
                r2.write(mdate.split()[0] if mdate else "N/A")
                
                # Column 3: Multi-format Downloads
                with r3:
                    d1, d2, d3 = st.columns(3)
                    d1.download_button("💾", mcont, f"{mname}.csv", help="CSV", key=f"am_csv_{mid}")
                    html_code = generate_export_html(mcont, mname, mtype)
                    d2.download_button("🌐", html_code, f"{mname}.html", help="HTML", key=f"am_html_{mid}")
                    pdf_code = convert_html_to_pdf(html_code)
                    if pdf_code:
                        with d3.popover("⚙️"):
                            st.write("🔧 PDF Master")
                            z_val = st.slider("Zoom", 0.5, 2.0, 1.0, 0.1, key=f"am_z_{mid}")
                            t_p = st.number_input("Pages visées", 0, 10, 0, key=f"am_p_{mid}", help="0 pour auto")
                            
                            f_z = z_val
                            if t_p > 0:
                                t_q = mcont.count('\n')
                                e_p = (t_q * 0.05) if mtype == "QCM" else (t_q * 0.08)
                                if e_p > 0: f_z = min(z_val, (t_p / e_p))
                            
                            scaled_pdf = convert_html_to_pdf(html_code, zoom=f_z)
                            if scaled_pdf:
                                st.download_button("⬇️ PDF", scaled_pdf, f"{mname}.pdf", key=f"am_dl_{mid}", use_container_width=True)
                    else:
                        d3.button("❌", disabled=True, help="PDF non généré", key=f"am_pdf_err_{mid}")

                # Column 4: Quick Actions
                with r4:
                    a1, a2, a3, a4 = st.columns(4)
                    if a1.button("✏️", help="Éditer", key=f"ed_{mid}"):
                        st.session_state.csv_source_input = mcont
                        st.session_state.editing_name = mname
                        st.session_state.editing_type = "QCM Classique" if mtype == "QCM" else "Questions / Réponses" if mtype == "QA" else "Glossaire (Concept | Définition)" if mtype == "DEF" else "Synthèse (Markdown)"
                        st.session_state.current_page = "✍️ Créateur"
                        st.rerun()
                    
                    if a2.button("🗑️", help="Supprimer", key=f"de_{mid}"):
                        db_delete_module(mid)
                        st.success("Supprimé !")
                        st.rerun()
                        
                    if a3.button("👁️", help="Voir", key=f"vi_{mid}"):
                        st.session_state.view_content = {"name": mname, "type": mtype, "content": mcont}
                        st.session_state.current_page = "👁️ Visualiseur"
                        st.rerun()
                        
                    if a4.button("🚀", help="Quiz", key=f"qu_{mid}"):
                        st.session_state.auto_load_csv = mcont
                        st.session_state.quiz_mod = mname
                        st.session_state.current_page = "⚡ Quiz Interactif"
                        st.rerun()
                
                st.divider()

def page_summaries():
    # Ancienne page maintenue pour compatibilité ou simplifiée
    st.header("📚 Bibliothèque de Résumés")
    all_sums = db_get_modules(m_type="SUM")
    if not all_sums:
        st.info("Aucun résumé trouvé.")
        return

    for mid, name, cat, mtype, cont, date in all_sums:
        with st.expander(f"📖 {name} ({cat})"):
            st.markdown(cont)
            if st.button("👁️ Ouvrir dans le Visualiseur", key=f"lib_{mid}"):
                st.session_state.view_content = {"name": name, "content": cont, "type": "SUM"}
                st.session_state.current_page = "👁️ Visualiseur"
                st.rerun()

def page_guide_ia():
    st.header("💡 Guide Complet : Génération par IA")
    
    st.markdown("""
    ### 🎨 L'Art du Prompting
    Pour obtenir des résultats parfaits, utilisez ces modèles de prompts avec votre IA (ChatGPT, Claude, etc.).
    
    > [!IMPORTANT]
    > Remplacez **[COLLEZ LE TEXTE ICI]** par le contenu de votre cours dans les modèles ci-dessous.
    """)

    tabs = st.tabs(["⚡ QCM", "❓ Q&A", "📜 Glossaire", "📝 Synthèse"])
    
    with tabs[0]:
        st.subheader("Modèle QCM (Interactif)")
        qcm_prompt = """Tu es un expert en ingénierie pédagogique. À partir du texte fourni, génère un examen QCM de haute qualité.

CONSIGNES STRICTES :
1. Format : CSV strict (délimiteur '|')
2. Colonnes : Question|A|B|C|D|E|F|Réponse|Explication
3. Réponse : Indique la lettre (ex: A) ou les lettres (ex: AC) sans séparateur.
4. Qualité : Crée des distracteurs plausibles. L'explication doit justifier la bonne réponse.
5. Langue : Français.

TEXTE DE RÉFÉRENCE :
[COLLEZ LE TEXTE ICI]"""
        st.text_area("Copiez ce prompt pour les QCM :", qcm_prompt, height=300, key="guide_qcm")

    with tabs[1]:
        st.subheader("Modèle Q&A (Flashcards)")
        qa_prompt = """Tu es un expert en mémorisation active. À partir du texte fourni, génère des questions-réponses percutantes.

CONSIGNES STRICTES :
1. Format : CSV strict (délimiteur '|')
2. Colonnes : Question|Réponse
3. Langue : Français.

TEXTE DE RÉFÉRENCE :
[COLLEZ LE TEXTE ICI]"""
        st.text_area("Copiez ce prompt pour les Flashcards :", qa_prompt, height=250, key="guide_qa")

    with tabs[2]:
        st.subheader("Modèle Glossaire (Concepts)")
        def_prompt = """Identifie tous les concepts clés, termes techniques et définitions importantes dans le texte suivant.

CONSIGNES STRICTES :
1. Format : CSV (délimiteur '|')
2. Colonnes : Concept|Définition
3. Langue : Français.

TEXTE DE RÉFÉRENCE :
[COLLEZ LE TEXTE ICI]"""
        st.text_area("Copiez ce prompt pour le Glossaire :", def_prompt, height=250, key="guide_def")

    with tabs[3]:
        st.subheader("Modèle Synthèse (Markdown)")
        sum_prompt = """Rédige une synthèse structurée et pédagogique du texte suivant. 
Utilise du Markdown pour la mise en forme (titres, listes, gras).

CONSIGNES :
1. Style : Clair, concis et professionnel.
2. Langue : Français.
3. Format : Résumé structuré.

TEXTE DE RÉFÉRENCE :
[COLLEZ LE TEXTE ICI]"""
        st.text_area("Copiez ce prompt pour la Synthèse :", sum_prompt, height=250, key="guide_sum")

    st.divider()
    st.info("🎯 Astuce : Utilisez Claude 3.5 Sonnet ou GPT-4o pour les meilleurs résultats.")


def page_favorites():
    st.header("⭐ Mes Questions Favorites")
    st.info("Retrouvez ici les questions que vous avez marquées pour révision.")
    
    email = st.session_state.identity.get("email", "anonyme")
    favs = db_get_favorites(email)
    
    if not favs:
        st.warning("Vous n'avez pas encore de favoris.")
        return
    
    for i, f in enumerate(favs, 1):
        with st.expander(f"Question {i} - Module: {f['module']}"):
            st.write(f"**{f['text']}**")
            for j, opt in enumerate(f['opts'], 1):
                st.write(f"{chr(64+j)}. {opt}")
            st.success(f"Réponse : {f['ans']}")
            st.info(f"Explication : {f['expl']}")
            if st.button(f"🗑️ Retirer", key=f"del_fav_{i}"):
                db_toggle_favorite(email, f['module'], f['text'], f['opts'], f['ans'], f['expl'])
                st.rerun()

# --- Execute Page ---
if st.session_state.current_page == "📄 PDF Transformer": page_pdf_transformer()
elif st.session_state.current_page == "📄 PDF Merger": page_pdf_merger()
elif st.session_state.current_page == "✍️ Créateur": page_creator()
elif st.session_state.current_page == "🔍 Explorer": page_discover()
elif st.session_state.current_page == "📚 Résumés": page_summaries()
elif st.session_state.current_page == "⚡ Quiz Interactif": page_quiz()
elif st.session_state.current_page == "⭐ Mes Favoris": page_favorites()
elif st.session_state.current_page == "📊 Historique": page_history()
elif st.session_state.current_page == "💡 Guide IA": page_guide_ia()
elif st.session_state.current_page == "⚙️ Gestion BD": page_admin_crud()
elif st.session_state.current_page == "👁️ Visualiseur": page_visualizer()

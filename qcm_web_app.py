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

# --- ADVANCED LIBS ---
import PyPDF2
import sqlite3

def extract_text_from_pdf(file_bytes):
    """Extraie le texte d'un fichier PDF uploader."""
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text.strip()
    except Exception as e:
        return f"Erreur d'extraction : {e}"

def validate_csv_data(csv_text, q_type):
    """Analyse le CSV et retourne une liste d'erreurs/avertissements."""
    errors = []
    warnings = []
    f = io.StringIO(csv_text.strip())
    reader = csv.reader(f, delimiter='|')
    
    # Check header
    header = next(reader, None)
    if not header:
        return ["Le fichier est vide."], []

    for i, row in enumerate(reader, 1):
        if not any(row): continue # Skip empty lines
        
        if q_type == "QCM Classique":
            if len(row) < 7:
                errors.append(f"Ligne {i} : Colonnes insuffisantes ({len(row)}/7 minimum).")
                continue
            
            # Check options vs answer
            q_text = row[0].strip()
            ans = (row[7] if len(row) >= 9 else row[5]).strip().upper()
            opts = [row[j] for j in range(1, 7 if len(row) >= 9 else 5) if row[j].strip()]
            num_opts = len(opts)
            lets = "ABCDEF"[:num_opts]
            
            if not ans:
                errors.append(f"Ligne {i} : Réponse manquante.")
            else:
                for char in ans.replace(',', '').replace(' ', ''):
                    if char not in lets:
                        errors.append(f"Ligne {i} : La réponse '{char}' n'est pas cohérente avec les {num_opts} options fournies.")
        
        elif q_type in ["Questions / Réponses", "Glossaire (Concept | Définition)"]:
            if len(row) < 2:
                errors.append(f"Ligne {i} : Format attendu 'A|B', trouvé seulement {len(row)} colonnes.")
    
    return errors, warnings

# Configuration de la page
st.set_page_config(page_title="QCM Master Pro v3", layout="wide", page_icon="🎯")

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

# --- DATABASE LOGIC ---
DB_NAME = "qcm_master.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Table Utilisateurs
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (email TEXT PRIMARY KEY, nom TEXT, prenom TEXT, user_id TEXT)''')
    # Table Historique des scores
    c.execute('''CREATE TABLE IF NOT EXISTS history 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  email TEXT, course TEXT, score INTEGER, total INTEGER, date TEXT)''')
    # Table Progression Quiz (En cours)
    c.execute('''CREATE TABLE IF NOT EXISTS quiz_progress 
                 (email TEXT, module_name TEXT, current_idx INTEGER, 
                  answers_json TEXT, last_updated TEXT,
                  PRIMARY KEY (email, module_name))''')
    conn.commit()
    conn.close()

def db_save_user(email, nom, prenom, user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (email, nom, prenom, user_id) VALUES (?, ?, ?, ?)", 
              (email, nom, prenom, user_id))
    conn.commit()
    conn.close()

def db_save_score(email, course, score, total):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    c.execute("INSERT INTO history (email, course, score, total, date) VALUES (?, ?, ?, ?, ?)", 
              (email, course, score, total, date_str))
    conn.commit()
    conn.close()

def db_get_best_score(email, course):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT MAX(score), total FROM history WHERE email = ? AND course = ?", (email, course))
    res = c.fetchone()
    conn.close()
    if res and res[0] is not None:
        return f"{res[0]} / {res[1]}"
    return "N/A"

import json

def db_save_progress(email, module_name, current_idx, answers):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    ans_json = json.dumps(answers)
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    c.execute("INSERT OR REPLACE INTO quiz_progress (email, module_name, current_idx, answers_json, last_updated) VALUES (?, ?, ?, ?, ?)",
              (email, module_name, current_idx, ans_json, date_str))
    conn.commit()
    conn.close()

def db_load_progress(email, module_name):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT current_idx, answers_json FROM quiz_progress WHERE email = ? AND module_name = ?", (email, module_name))
    res = c.fetchone()
    conn.close()
    if res:
        return {"idx": res[0], "answers": json.loads(res[1])}
    return None

def db_clear_progress(email, module_name):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM quiz_progress WHERE email = ? AND module_name = ?", (email, module_name))
    conn.commit()
    conn.close()

def db_get_history(email):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT date as Date, course as Examen, CAST(score AS TEXT) || ' / ' || CAST(total AS TEXT) as Score FROM history WHERE email = ? ORDER BY id DESC", conn, params=(email,))
    conn.close()
    return df

# Initialize DB on load
init_db()

# --- FONCTIONS UTILES ---
def convert_html_to_pdf(source_html):
    """Convertit le HTML en PDF bytes via pdfkit."""
    try:
        config = pdfkit.configuration(wkhtmltopdf=r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe")
        pdf_bytes = pdfkit.from_string(source_html, False, configuration=config)
        return pdf_bytes
    except Exception as e:
        st.error(f"Erreur PDF : {e}")
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

def generate_html_content(csv_text, title, use_columns, add_qr=True, mode="Examen", shuffle_q=False, shuffle_o=False, q_type="QCM Classique", add_sheet=True):
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
    next(reader, None) # Skip header
    
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
            if len(row) < 7: continue
            q_text = row[0].strip()
            if len(row) >= 9:
                opts = [row[i].strip() for i in range(1, 7)]
                ans = row[7].strip()
                expl = row[8].strip()
            else:
                opts = [row[i].strip() for i in range(1, 5)]
                ans = row[5].strip()
                expl = row[6].strip()
            
            lets = ['A', 'B', 'C', 'D', 'E', 'F'][:len(opts)]
            correct_indices = [lets.index(l) for l in ans if l in lets]
            
            raw_questions.append({
                'text': q_text,
                'opts_data': [{'text': o, 'is_correct': (i in correct_indices)} for i, o in enumerate(opts) if o],
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
                    <details>
                        <summary>▶ Réponse</summary>
                        <div class="qa-answer">{q['ans']}</div>
                    </details>
                </div>"""
                answers_rows += f"<tr><td>{q_num}</td><td colspan='2' style='font-weight:bold;'>{q['ans']}</td></tr>"
            else:
                opts_list = q['opts_data']
                if shuffle_o: random.shuffle(opts_list)
                final_lets = ['A', 'B', 'C', 'D', 'E', 'F'][:len(opts_list)]
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

def perform_stats(csv_text):
    f = io.StringIO(csv_text); reader = csv.reader(f, delimiter='|'); next(reader, None)
    total, single, multi, all_ans = 0, 0, 0, []
    for row in reader:
        if len(row) < 7: continue
        total += 1
        ans = str(row[7] if len(row) >= 9 else row[5]).strip().upper().replace(',', '').replace(' ', '')
        if len(ans) > 1: multi += 1
        else: single += 1
        for char in ans:
            if char in 'ABCDEF': all_ans.append(char)
    counts = Counter(all_ans); total_ans = len(all_ans) if all_ans else 1
    dist = {k: (v/total_ans * 100) for k, v in counts.items()}
    return total, single, multi, dist

def parse_csv(text):
    f = io.StringIO(text); reader = csv.reader(f, delimiter='|'); next(reader, None)
    data = []
    for row in reader:
        if len(row) < 7: continue
        q = {'text': row[0].strip()}
        if len(row) >= 9:
            q['opts'] = [row[i].strip() for i in range(1, 7)]
            q['ans'] = row[7].strip().replace(' ', '').replace(',', '').upper()
            q['expl'] = row[8].strip()
        else:
            q['opts'] = [row[i].strip() for i in range(1, 5)]
            q['ans'] = row[5].strip().replace(' ', '').replace(',', '').upper()
            q['expl'] = row[6].strip()
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
        <div style="margin-bottom: 25px; border-left: 5px solid {color}; padding-left: 15px; page-break-inside: avoid;">
            <p style="font-weight:bold; font-size:11pt; margin-bottom:5px;">Q{idx+1}. {q['text']} {is_correct}</p>
            {opts_html}
            <p style="font-size: 10pt; margin: 5px 0;"><strong>Votre sélection :</strong> {u_ans_letters if u_ans_letters else "NULL"}</p>
            <p style="font-size: 9pt; color: #555; background: #f9f9f9; padding: 8px; border-radius: 4px; margin-top: 5px;">
                💡 <em>Explication : {q['expl']}</em>
            </p>
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
    <h1>Rapport d'Examen : {title}</h1>
    <div class="header-box">
        <p><strong>Candidat :</strong> {name}{user_id}</p>
        <p><strong>Date de passage :</strong> {now}</p>
        {warnings_html}
    </div>
    <div class="score-box">Score Global : <strong>{score} / {len(questions)}</strong> ({(score/len(questions)*100):.1f}%)</div>
    <hr style="border: 0; border-top: 1px solid #eee; margin-bottom: 30px;">
    {rows}
</body></html>"""
    return html

# --- PERSISTENCE JS ---
def inject_persistence_js():
    st.components.v1.html("""
    <script>
    const saveState = () => {
        const answers = window.parent.document.querySelectorAll('input[type="radio"]:checked');
        const data = {};
        answers.forEach(input => {
            data[input.name] = input.value;
        });
        localStorage.setItem('qcm_persistence', JSON.stringify(data));
    };
    window.parent.document.addEventListener('change', saveState);
    </script>
    """, height=0)

def load_persistence_js():
    st.components.v1.html("""
    <script>
    const data = localStorage.getItem('qcm_persistence');
    if (data) {
        // This is tricky in Streamlit as we can't easily send data back to Python session_state 
        // without a custom component or a specific trigger.
        // For now, we will notify the user that recovery is available.
        console.log("Persistence data found:", data);
    }
    </script>
    """, height=0)

# --- PAGE FUNCTIONS ---

def page_pdf_transformer():
    st.header("📄 PDF Transformer (Extraction & IA)")
    st.info("Étape 1 : Téléchargez votre PDF. Étape 2 : Choisissez le type d'exercice. Étape 3 : Utilisez le prompt généré avec votre IA préférée.")

    uploaded_pdf = st.file_uploader("Glissez votre PDF ici", type="pdf")
    if uploaded_pdf:
        pdf_text = extract_text_from_pdf(uploaded_pdf.read())
        if "Erreur" in pdf_text:
            st.error(pdf_text)
        else:
            st.success("✅ Texte extrait avec succès !")
            
            cleaned_text = " ".join(pdf_text.split())[:15000] # Limite pour les prompts
            
            st.subheader("⚙️ Configurer l'IA")
            ex_type = st.radio("Type d'exercice souhaité :", 
                              ["QCM (Interactif)", "Q&A (Flashcards)", "Synthèse & Définitions"],
                              horizontal=True)
            
            target_lang = st.selectbox("Langue cible :", ["Français", "Arabe", "Anglais"])
            
            if ex_type == "QCM (Interactif)":
                prompt = f"""Agis comme un expert pédagogique. À partir du texte suivant, génère un QCM au format CSV strict avec le délimiteur '|'.
                Colonnes : Question|A|B|C|D|E|F|Réponse|Explication
                Langue : {target_lang}.
                Suffixe de fichier recommandé : _QCM.csv
                
                Texte : {cleaned_text}"""
                suffix = "_QCM.csv"
            elif ex_type == "Q&A (Flashcards)":
                prompt = f"""Génère une liste de Questions/Réponses pédagogiques à partir du texte.
                Format CSV strict (délimiteur |) : Question|Réponse
                Langue : {target_lang}.
                Suffixe de fichier recommandé : _QA.csv
                
                Texte : {cleaned_text}"""
                suffix = "_QA.csv"
            else:
                prompt = f"""Génère une synthèse pédagogique structurée.
                Inclus : 1. Points clés, 2. Définitions importantes, 3. Résumé global.
                Format : Markdown.
                Langue : {target_lang}.
                Suffixe de fichier recommandé : _SUM.md
                
                Texte : {cleaned_text}"""
                suffix = "_SUM.md"

            st.text_area(f"📋 Prompt IA pour {ex_type}", prompt, height=250)
            st.info(f"💡 **Conseil** : Une fois le contenu généré par l'IA, utilisez l'onglet **'Créateur'** pour l'enregistrer avec le nom se terminant par `{suffix}`.")

def page_creator():
    st.header("✍️ Créateur de Contenu (HTML/PDF)")
    
    # Sidebar config for this page
    MOD_DIR = "modules"
    if not os.path.exists(MOD_DIR): os.makedirs(MOD_DIR)
    categories = [d for d in os.listdir(MOD_DIR) if os.path.isdir(os.path.join(MOD_DIR, d))] or ["Général"]
    
    with st.sidebar:
        st.subheader("📁 Modules")
        sel_cat = st.selectbox("Catégorie", categories)
        cat_path = os.path.join(MOD_DIR, sel_cat)
        mod_files = [f for f in os.listdir(cat_path) if f.endswith(".csv")]
        if mod_files:
            sel_mod = st.selectbox("Charger", ["-- Choisir --"] + mod_files)
            if sel_mod != "-- Choisir --" and st.button("📂 Charger"):
                with open(os.path.join(cat_path, sel_mod), "r", encoding="utf-8") as f:
                    st.session_state.csv_source_input = f.read()
                st.rerun()
        
        st.divider()
        doc_title = st.text_input("Titre", "Examen NLP")
        out_name = st.text_input("Nom fichier", "qcm_output")
        q_type = st.radio("Type", ["QCM Classique", "Questions / Réponses", "Glossaire (Concept | Définition)"])
        html_mode = st.radio("Style", ["Examen", "Révision"])
        c1, c2 = st.columns(2)
        shuffle_q = c1.checkbox("Mélanger Q", value=False)
        shuffle_o = c2.checkbox("Mélanger O", value=False)
        use_3_col = st.checkbox("3 Colonnes", value=True)
        add_qr = st.checkbox("QR Code", value=True)
        add_sheet = st.checkbox("Feuille Réponses", value=True)

    default_val = st.session_state.get("csv_source_input", "")
    if not default_val:
        default_val = st.session_state.get("pdf_extracted_text", "")
        
    csv_in = st.text_area("Contenu CSV (|)", height=250, value=default_val)
    st.session_state.csv_source_input = csv_in
    
    if csv_in:
        errors, _ = validate_csv_data(csv_in, q_type)
        if errors:
            for e in errors: st.error(e)
            
        with st.expander("💾 Sauvegarder"):
            save_name = st.text_input("Nom fichier", value=out_name)
            if st.button("💾 Enregistrer"):
                os.makedirs(os.path.join(MOD_DIR, sel_cat), exist_ok=True)
                with open(os.path.join(MOD_DIR, sel_cat, f"{save_name}.csv"), "w", encoding="utf-8") as f:
                    f.write(csv_in)
                st.success("Enregistré !")

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

        html_out = generate_html_content(csv_in, doc_title, use_3_col, add_qr, mode=html_mode, shuffle_q=shuffle_q, shuffle_o=shuffle_o, q_type=q_type, add_sheet=add_sheet)
        
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
    inject_persistence_js()
    
    # Handle pre-loaded module from Explorer or Resume logic
    if "auto_load_csv" in st.session_state and st.session_state.auto_load_csv:
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

        # --- MODULE LOADING Logic ---
        st.subheader("📁 Charger un module")
        MODULES_DIR = "modules"
        if os.path.exists(MODULES_DIR):
            categories = [d for d in os.listdir(MODULES_DIR) if os.path.isdir(os.path.join(MODULES_DIR, d))]
            if categories:
                cat = st.selectbox("Catégorie", ["Choisir..."] + categories, key="quiz_cat")
                if cat != "Choisir...":
                    cat_path = os.path.join(MODULES_DIR, cat)
                    files = [f for f in os.listdir(cat_path) if f.endswith('.csv')]
                    if files:
                        mod_file = st.selectbox("Module", ["Choisir..."] + files, key="quiz_mod")
                        if mod_file != "Choisir...":
                            if st.button("📥 Charger ce module"):
                                with open(os.path.join(cat_path, mod_file), "r", encoding="utf-8") as f:
                                    st.session_state.csv_source_input = f.read()
                                st.success(f"Module '{mod_file}' chargé !")

        csv_quiz = st.text_area("Source CSV du Quiz", height=150, value=st.session_state.get("csv_source_input", ""), key="quiz_csv_area")
        
        st.subheader("👤 Candidat")
        c1, c2 = st.columns(2)
        st.session_state.identity["nom"] = c1.text_input("Nom", value=st.session_state.identity["nom"])
        st.session_state.identity["prenom"] = c2.text_input("Prénom", value=st.session_state.identity["prenom"])
        st.session_state.identity["id"] = st.text_input("ID", value=st.session_state.identity["id"])
        
        if not st.session_state.identity["verified"]:
            st.warning("⚠️ Accès restreint. Connectez-vous dans la page 'Historique' (Simulation) pour enregistrer vos scores.")

        if st.button("🚀 DÉMARRER"):
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
        
        # --- QUIZ HEADER with EXIT button ---
        head_c1, head_c2 = st.columns([0.85, 0.15])
        head_c1.subheader(f"Question {idx+1} / {num_q}")
        if head_c2.button("🚪 QUITTER", use_container_width=True):
            st.session_state.confirm_exit = True
            st.rerun()

        if st.session_state.confirm_exit:
            st.warning("⚠️ **Confirmer la sortie ?** Votre progression restera sauvegardée localement.")
            exit_c1, exit_c2 = st.columns(2)
            if exit_c1.button("✅ OUI, QUITTER", type="primary", use_container_width=True):
                st.session_state.confirm_exit = False
                st.session_state.quiz_started = False
                st.rerun()
            if exit_c2.button("❌ ANNULER", use_container_width=True):
                st.session_state.confirm_exit = False
                st.rerun()
            st.stop()

        st.write(f"### {q['text']}")
        st.markdown('---')
        
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
            is_multi = len(q['ans']) > 1
            if is_multi:
                st.caption("*(Plusieurs réponses possibles)*")
                for i, l in enumerate(letters):
                    prev_val = l in st.session_state.user_answers.get(idx, "")
                    if st.checkbox(f"{l}. {q['opts'][i]}", key=f"q{idx}_{l}", value=prev_val):
                        selected.append(l)
            else:
                prev_idx = None
                current_ans = st.session_state.user_answers.get(idx, "")
                if current_ans:
                    try: prev_idx = letters.index(current_ans)
                    except: pass
                
                choice = st.radio(f"Selection Q{idx+1}", 
                                 [f"{l}. {q['opts'][i]}" for i, l in enumerate(letters)],
                                 index=prev_idx, key=f"q{idx}", label_visibility="collapsed")
                if choice: selected = [choice[0]]
            
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
            
            if idx < num_q - 1:
                if st.button("➡️ QUESTION SUIVANTE", type="primary", use_container_width=True):
                    st.session_state.current_q_idx += 1
                    st.session_state.validated_current = False
                    st.rerun()
            else:
                if st.button("🏁 TERMINER L'EXAMEN", type="primary", use_container_width=True):
                    st.session_state.quiz_started = False
                    st.session_state.score_submitted = True
                    # Record in history
                    score = 0
                    for i, q_data in enumerate(questions):
                        if st.session_state.user_answers.get(i, "") == q_data['ans']:
                            score += 1
                    
                    if st.session_state.identity["verified"]:
                        db_save_score(st.session_state.identity["email"], st.session_state.current_course_name, score, num_q)
                        db_clear_progress(st.session_state.identity["email"], st.session_state.current_course_name)
                    
                    st.session_state.history.append({
                        "Date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "Examen": st.session_state.current_course_name,
                        "Email": st.session_state.identity["email"] if st.session_state.identity["verified"] else "Anonyme",
                        "Score": f"{score} / {num_q}"
                    })
                    st.rerun()

    if st.session_state.score_submitted:
        questions = st.session_state.shuffled_questions
        num_q = len(questions)
        score = 0
        for idx, q in enumerate(questions):
            if st.session_state.user_answers.get(idx, "") == q['ans']:
                score += 1
        
        st.balloons()
        st.markdown(f"""
            <div style="text-align:center; padding:30px; background:#f0f7f4; border-radius:15px; border:2px solid #27ae60; margin-bottom: 20px;">
                <h1 style="color:#27ae60; margin:0;">SCORE FINAL : {score} / {num_q}</h1>
                <p style="font-size:16pt;">Candidat : <strong>{st.session_state.identity['prenom']} {st.session_state.identity['nom']}</strong></p>
                <p style="font-size:14pt;">Taux de réussite : <strong>{(score/num_q*100):.1f}%</strong></p>
            </div>
        """, unsafe_allow_html=True)
        
        if score / num_q >= 0.8:
            st.success("🏆 Félicitations ! Vous avez obtenu un certificat.")
            pdf_diploma = generate_diploma(f"{st.session_state.identity['prenom']} {st.session_state.identity['nom']}", score, num_q, "Examen NLP")
            if pdf_diploma:
                st.download_button("📥 TÉLÉCHARGER MON DIPLÔME", pdf_diploma, "diplome_reussite.pdf")

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

def page_discover():
    st.markdown("""
    <style>
    .module-card {
        background: white;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        border: 1px solid #eee;
        transition: transform 0.2s, box-shadow 0.2s;
        margin-bottom: 20px;
        height: 100%;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }
    .module-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 8px 15px rgba(0,0,0,0.1);
    }
    .card-header {
        display: flex;
        align-items: center;
        margin-bottom: 12px;
        gap: 10px;
    }
    .icon-box {
        background: #f0f4f8;
        padding: 8px;
        border-radius: 8px;
        font-size: 1.5em;
    }
    .module-name {
        font-weight: bold;
        font-size: 1.1em;
        color: #2c3e50;
        margin: 0;
    }
    .best-score {
        background: #fff8e1;
        color: #f57c00;
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 0.85em;
        font-weight: bold;
        display: inline-block;
        margin-top: 5px;
    }
    .in-progress {
        background: #e3f2fd;
        color: #1976d2;
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 0.85em;
        font-weight: bold;
        display: inline-block;
        margin-top: 5px;
    }
    </style>
    """, unsafe_allow_html=True)

    st.header("🔍 Explorateur de Modules")
    
    MODULES_DIR = "modules"
    if not os.path.exists(MODULES_DIR):
        st.info("Aucun module créé pour le moment. Allez dans 'Créateur' pour commencer.")
        return

    categories = [d for d in os.listdir(MODULES_DIR) if os.path.isdir(os.path.join(MODULES_DIR, d))]
    
    if not categories:
        st.info("Aucun module trouvé.")
        return

    # Use tabs for categories
    tabs = st.tabs([f"📂 {cat}" for cat in categories])
    
    for i, cat in enumerate(categories):
        with tabs[i]:
            cat_path = os.path.join(MODULES_DIR, cat)
            files = [f for f in os.listdir(cat_path) if f.endswith('.csv')]
            
            if not files:
                st.info("Dossier vide.")
                continue
            
            # Grid layout for cards
            cols = st.columns(2)
            for idx, f in enumerate(files):
                with cols[idx % 2]:
                    # File type detection
                    f_type = "QCM"
                    if "_QA" in f: f_type = "QA"
                    elif "_SUM" in f or f.endswith(".md"): f_type = "SUM"
                    
                    best = "N/A"
                    progress = False
                    if f_type == "QCM" and st.session_state.identity["verified"]:
                        best = db_get_best_score(st.session_state.identity["email"], f)
                        p_data = db_load_progress(st.session_state.identity["email"], f)
                        if p_data: progress = True
                    
                    icons = {"QCM": "⚡", "QA": "❓", "SUM": "📝"}
                    icon = icons.get(f_type, "📄")

                    card_html = f"""<div class="module-card">
<div class="card-header">
<div class="icon-box">{icon}</div>
<p class="module-name">{f.replace('.csv', '').replace('.md', '')}</p>
</div>
<div>
{f'<span class="best-score">🏆 Record : {best}</span>' if f_type == "QCM" else ""}
{"<span class='in-progress'>⏳ En cours</span>" if progress else ""}
<span style='color: grey; font-size: 0.8em; display: block;'>Type: {f_type}</span>
</div>
</div>"""
                    st.markdown(card_html, unsafe_allow_html=True)
                    
                    # Action buttons
                    full_path = os.path.join(cat_path, f)
                    with open(full_path, "r", encoding="utf-8") as file_data:
                        content = file_data.read()
                    
                    ac1, ac2 = st.columns(2)
                    if f_type == "QCM":
                        if ac1.button("🚀 Lancer", key=f"q_{f}_{i}"):
                            st.session_state.auto_load_csv = content
                            st.session_state.quiz_mod = f
                            st.session_state.current_page = "⚡ Quiz Interactif"
                            st.rerun()
                    else:
                        if ac1.button("👁️ Voir", key=f"v_{f}_{i}"):
                            st.session_state.view_content = {"name": f, "content": content, "type": f_type}
                            st.session_state.current_page = "👁️ Visualiseur"
                            st.rerun()
                    
                    # Tooltip for download
                    if f.endswith('.csv'):
                        html_code = generate_html_content(content, f.replace(".csv", ""), use_columns=True)
                        ac2.download_button("📥 HTML", data=html_code, file_name=f.replace(".csv", ".html"), mime="text/html", key=f"dl_{f}_{i}")
                    else:
                        ac2.download_button("📥 File", data=content, file_name=f, mime="text/plain", key=f"dl_{f}_{i}")
                    st.write("") 

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
        st.markdown(v["content"])
    elif v["type"] == "QA":
        # Simple parsing for Q&A
        lines = v["content"].split("\n")
        for line in lines:
            if line.strip().startswith("Q:"):
                st.info(f"**{line.strip()}**")
            elif line.strip().startswith("R:"):
                st.write(line.strip().replace("R:", "*Rép :*"))
    else:
        st.code(v["content"])

# --- MAIN NAVIGATION ---
if "current_page" not in st.session_state:
    st.session_state.current_page = "📄 PDF Transformer"

with st.sidebar:
    st.title("🚀 Navigation")
    pages = ["📄 PDF Transformer", "✍️ Créateur", "🔍 Explorer", "⚡ Quiz Interactif", "📊 Historique", "👁️ Visualiseur"]
    # Hide Visualizer from direct selectbox if not active
    nav_pages = [p for p in pages if p != "👁️ Visualiseur" or st.session_state.current_page == "👁️ Visualiseur"]
    
    idx = 0
    if st.session_state.current_page in nav_pages:
        idx = nav_pages.index(st.session_state.current_page)
        
    choice = st.selectbox("Aller vers :", nav_pages, index=idx)
    st.session_state.current_page = choice

if st.session_state.current_page == "📄 PDF Transformer": page_pdf_transformer()
elif st.session_state.current_page == "✍️ Créateur": page_creator()
elif st.session_state.current_page == "🔍 Explorer": page_discover()
elif st.session_state.current_page == "⚡ Quiz Interactif": page_quiz()
elif st.session_state.current_page == "📊 Historique": page_history()
elif st.session_state.current_page == "👁️ Visualiseur": page_visualizer()

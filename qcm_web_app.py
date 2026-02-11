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
    st.info("Utilisez cet outil pour extraire le texte de vos PDF de cours et le transformer en QCM via les prompts fournis.")
    
    with st.expander("💡 Guide : Prompts pour LLM"):
        st.markdown("""
        **1. Pour QCM Classique :**
        > Agit comme un expert pédagogique. À partir du texte suivant, génère un QCM de [X] questions au format CSV avec le délimiteur '|'.
        > Colonnes : `Question|A|B|C|D|E|F|Réponse|Explication`
        
        **2. Pour Questions / Réponses (Flashcards) :**
        > Format CSV : `Question|Réponse` (Délimiteur '|')
        
        **3. Pour Glossaire (Définitions) :**
        > Format CSV : `Concept|Définition` (Délimiteur '|')
        """)

    uploaded_pdf = st.file_uploader("Glissez votre PDF ici", type="pdf")
    if uploaded_pdf:
        pdf_text = extract_text_from_pdf(uploaded_pdf.read())
        if "Erreur" in pdf_text:
            st.error(pdf_text)
        else:
            st.success("Texte extrait avec succès !")
            st.text_area("Texte extrait", pdf_text, height=300)
            if st.button("✨ Envoyer vers le Créateur"):
                st.session_state.pdf_extracted_text = pdf_text
                st.success("Texte prêt pour le Créateur !")

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
    st.header("⚡ Mode Quiz Flash Interactif")
    inject_persistence_js()
    
    if not st.session_state.quiz_started:
        csv_quiz = st.text_area("Source CSV du Quiz", height=150, key="csv_source_input")
        
        st.subheader("👤 Candidat")
        c1, c2 = st.columns(2)
        st.session_state.identity["nom"] = c1.text_input("Nom", value=st.session_state.identity["nom"])
        st.session_state.identity["prenom"] = c2.text_input("Prénom", value=st.session_state.identity["prenom"])
        st.session_state.identity["id"] = st.text_input("ID", value=st.session_state.identity["id"])
        
        if not st.session_state.identity["verified"]:
            st.warning("⚠️ Accès restreint. Connectez-vous dans la page 'Historique' (Simulation) pour enregistrer vos scores.")

        if st.button("🚀 DÉMARRER"):
            if not csv_quiz: st.error("Collez un CSV !")
            else:
                st.session_state.quiz_started = True
                st.session_state.start_time = time.time()
                st.session_state.user_answers = {}
                st.session_state.shuffled_questions = parse_csv(csv_quiz)
                st.rerun()
    else:
        questions = st.session_state.shuffled_questions
        idx = st.session_state.current_q_idx
        q = questions[idx]
        
        st.progress((idx + 1) / len(questions))
        st.subheader(f"Question {idx+1} / {len(questions)}")
        st.write(f"### {q['text']}")
        
        ans = st.radio("Choisissez :", q['opts'] + ["Auncune réponse (NULL)"], key=f"q_{idx}")
        
        c1, c2, c3 = st.columns(3)
        if idx > 0 and c1.button("⬅️ Précédent"):
            st.session_state.current_q_idx -= 1
            st.rerun()
        
        if idx < len(questions) - 1:
            if c3.button("Suivant ➡️"):
                st.session_state.current_q_idx += 1
                st.rerun()
        else:
            if c3.button("🏁 TERMINER"):
                # --- SUBMISSION LOGIC ---
                score = 0
                questions = st.session_state.shuffled_questions
                user_ans = st.session_state.user_answers
                
                # Mapping user selection to A, B, C
                mapping = {opt: chr(65+i) for i, opt in enumerate(q['opts'])} # A=65
                # Wait, mapping needs to be consistent with parse_csv
                
                for i, q_data in enumerate(questions):
                    choice = user_ans.get(i, "")
                    if choice == q_data['ans']:
                        score += 1
                
                # Record in history
                st.session_state.history.append({
                    "Date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "Examen": "Quiz Rapide",
                    "Email": st.session_state.identity["email"] if st.session_state.identity["verified"] else "Anonyme",
                    "Score": f"{score} / {len(questions)}"
                })
                
                st.session_state.quiz_started = False
                st.session_state.last_score = (score, len(questions))
                st.success(f"Terminé ! Score : {score} / {len(questions)}")
                
                if score / len(questions) >= 0.8:
                    st.balloons()
                    st.success("🏆 Félicitations ! Vous avez obtenu un certificat.")
                    pdf_diploma = generate_diploma(f"{st.session_state.identity['prenom']} {st.session_state.identity['nom']}", score, len(questions), "Examen NLP")
                    if pdf_diploma:
                        st.download_button("📥 TÉLÉCHARGER MON DIPLÔME", pdf_diploma, "diplome_reussite.pdf")
                
                rep_html = generate_result_report(questions, user_ans, score, "Résultats", st.session_state.identity)
                st.components.v1.html(rep_html, height=800, scrolling=True)

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
                st.success("Connecté !")
                st.rerun()
            else:
                st.error("Code incorrect.")
    else:
        st.write(f"Connecté en tant que : **{st.session_state.identity['email']}**")
        if st.button("🚪 Déconnexion"):
            st.session_state.identity["verified"] = False
            st.rerun()
            
        st.subheader("📈 Mes derniers scores")
        if not st.session_state.history:
            st.info("Aucun historique pour le moment.")
        else:
            df = pd.DataFrame(st.session_state.history)
            st.table(df)

# --- MAIN NAVIGATION ---
with st.sidebar:
    st.title("🚀 Navigation")
    choice = st.selectbox("Aller vers :", ["📄 PDF Transformer", "✍️ Créateur", "⚡ Quiz Interactif", "📊 Historique"])

if choice == "📄 PDF Transformer": page_pdf_transformer()
elif choice == "✍️ Créateur": page_creator()
elif choice == "⚡ Quiz Interactif": page_quiz()
elif choice == "📊 Historique": page_history()
v_val):
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
                        if st.button("✔️ VALIDER POUR VOIR LA RÉPONSE", type="primary", use_container_width=True):
                            st.session_state.validated_current = True
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
                                st.rerun()
                    st.markdown('</div>', unsafe_allow_html=True)
            
            # Auto-submit if time's up is handled by score_submitted check below
            
            if st.session_state.score_submitted:
                # Calculate final score
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
                
                result_html = generate_result_report(questions, st.session_state.user_answers, score, "Examen Officiel", 
                                                     identity=st.session_state.identity, 
                                                     cheat_warnings=st.session_state.cheat_warnings)
                result_pdf = convert_html_to_pdf(result_html)
                if result_pdf:
                    st.download_button("📄 TÉLÉCHARGER MON COMPTE-RENDU (PDF)", result_pdf, f"resultats_{st.session_state.identity['nom']}.pdf", mime="application/pdf", use_container_width=True)
                
                st.subheader("📝 Correction détaillée")
                for idx, q in enumerate(questions):
                    u_ans = st.session_state.user_answers.get(idx, "") or "NULL"
                    if u_ans == q['ans']:
                        st.success(f"**Q{idx+1}**: Correct ! Votre réponse : {u_ans}")
                    else:
                        st.error(f"**Q{idx+1}**: Incorrect. Votre réponse : {u_ans} | Correcte : {q['ans']}")
                        st.info(f"💡 **Explication** : {q['expl']}")
        else:
            st.info("👋 Prêt à commencer l'examen ? Remplissez vos informations et cliquez sur **🚀 DÉMARRER LE QUIZ** dans la barre latérale.")

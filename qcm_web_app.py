import streamlit as st
import pandas as pd
import csv
import io
import os
import time
from collections import Counter
import webbrowser
import pdfkit
from datetime import timedelta

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

# --- FONCTIONS UTILES ---
def convert_html_to_pdf(source_html):
    options = {
        'page-size': 'A4', 'margin-top': '0.5in', 'margin-right': '0.5in',
        'margin-bottom': '0.5in', 'margin-left': '0.5in', 'encoding': "UTF-8",
        'enable-local-file-access': None, 'print-media-type': None,
    }
    try:
        return pdfkit.from_string(source_html, False, options=options)
    except Exception as e:
        st.error(f"Erreur PDF : {e}")
        return None

def generate_answer_sheet(num_questions):
    """Génère une feuille de cochage propre (Matrice)"""
    rows = ""
    for i in range(1, num_questions + 1):
        rows += f"""
        <tr>
            <td style="font-weight:bold; width:30px;">{i}</td>
            <td style="width:30px; border:1px solid #000;"></td>
            <td style="width:30px; border:1px solid #000;"></td>
            <td style="width:30px; border:1px solid #000;"></td>
            <td style="width:30px; border:1px solid #000;"></td>
            <td style="width:30px; border:1px solid #000;"></td>
            <td style="width:30px; border:1px solid #000;"></td>
        </tr>"""
    
    return f"""
    <div style="page-break-before: always; margin-top:30px;">
        <h2 style="text-align:center;">FEUILLE DE RÉPONSES (À COCHER)</h2>
        <table style="width:auto; margin: 0 auto; border-collapse: collapse; text-align:center;">
            <thead>
                <tr>
                    <th>N°</th>
                    <th style="width:30px;">A</th><th style="width:30px;">B</th>
                    <th style="width:30px;">C</th><th style="width:30px;">D</th>
                    <th style="width:30px;">E</th><th style="width:30px;">F</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
        <p style="font-size:8pt; text-align:center; margin-top:10px;">Cochez la case correspondante à votre réponse.</p>
    </div>
    """

def generate_html_content(csv_text, title, use_columns, add_qr=True):
    col_css = "column-count: 3; -webkit-column-count: 3; -moz-column-count: 3; column-gap: 30px;" if use_columns else ""
    qr_code_html = f'<div style="text-align:right;"><img src="https://api.qrserver.com/v1/create-qr-code/?size=100x100&data=Correction_{title.replace(" ", "_")}#correction" alt="QR Correction" style="width:80px;"/> <br/><small>Scan pour correction</small></div>' if add_qr else ""
    
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
    .options li::before {{ content: attr(data-letter) ". "; font-weight: bold; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 9pt; }}
    th, td {{ border: 1px solid #000; padding: 5px; text-align: left; }}
    th {{ background-color: #eee; }}
    @media print {{ .no-print {{ display: none; }} }}
</style>
</head>
<body>
    {qr_code_html}
    <h1>{title}</h1>
    <div class="questions-wrapper">
"""
    
    f = io.StringIO(csv_text); reader = csv.reader(f, delimiter='|'); next(reader, None)
    questions_html, answers_rows, q_count = "", "", 0
    
    for row in reader:
        if len(row) < 7: continue
        q_count += 1
        q_text = row[0].strip()
        if len(row) >= 9:
            opts = [row[i].strip() for i in range(1, 7)]
            ans, expl, lets = row[7].strip(), row[8].strip(), ['A', 'B', 'C', 'D', 'E', 'F']
        else:
            opts = [row[i].strip() for i in range(1, 5)]
            ans, expl, lets = row[5].strip(), row[6].strip(), ['A', 'B', 'C', 'D']
            
        questions_html += f'<div class="question-block"><div class="question-text">{q_count}. {q_text}</div><ul class="options">'
        for i, opt in enumerate(opts):
            if opt: questions_html += f'<li data-letter="{lets[i]}">{opt}</li>'
        questions_html += "</ul></div>"
        
        answers_rows += f"<tr><td>{q_count}</td><td style='font-weight:bold;'>{ans}</td><td>{expl}</td></tr>"

    sheet_html = generate_answer_sheet(q_count)
    
    footer = f"""
    </div>
    {sheet_html}
    <div style="page-break-before: always;" id="correction">
        <h2>Correction</h2>
        <table><thead><tr><th>N°</th><th>Réponse</th><th>Explication</th></tr></thead><tbody>{answers_rows}</tbody></table>
    </div>
</body></html>"""
    
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

def generate_result_report(questions, user_answers, score, title):
    """Génère le HTML du rapport de résultats personnalisé"""
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
            # Logique des cases : [X] si correct, [x] si sélectionné par erreur, [ ] sinon
            box = "[ &nbsp; ]"
            if letter in q['ans']:
                box = "[ X ]"
            elif letter in u_ans_letters:
                box = "[ x ]"
            
            line_style = "margin-bottom: 4px; font-size: 10pt;"
            if letter in q['ans']:
                line_style += " color: #27ae60; font-weight: bold;"
            elif letter in u_ans_letters:
                line_style += " color: #e74c3c;"
                
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
    .score-box {{ background: #f8f9fa; border: 2px solid #2c3e50; padding: 20px; text-align: center; font-size: 18pt; margin-bottom: 30px; }}
</style></head><body>
    <h1>Rapport de Résultats : {title}</h1>
    <div class="score-box">Score Global : <strong>{score} / {len(questions)}</strong> ({(score/len(questions)*100):.1f}%)</div>
    {rows}
</body></html>"""
    return html

# --- SIDEBAR ---
with st.sidebar:
    st.title("⚙️ Mode & Config")
    mode = st.radio("Mode de l'application", ["📄 Créateur QCM (Original)", "⚡ Quiz Flash Interactif"], key="main_mode_radio")
    
    if mode == "📄 Créateur QCM (Original)":
        doc_title = st.text_input("Titre", "Examen NLP")
        out_name = st.text_input("Nom fichier", "qcm_output")
        use_3_col = st.checkbox("3 Colonnes (Original)", value=True)
        add_qr = st.checkbox("Ajouter QR Code Correction", value=True)
    else:
        time_limit = st.number_input("Limite de temps (min)", 1, 120, 20)
        if st.button("🚀 DÉMARRER LE QUIZ"):
            st.session_state.quiz_started = True
            st.session_state.start_time = time.time()
            st.session_state.user_answers = {}
            st.session_state.score_submitted = False
        if st.button("🔄 Reset Quiz"):
            st.session_state.quiz_started = False
            st.rerun()

# --- MAIN INTERFACE ---
if mode == "📄 Créateur QCM (Original)":
    st.header("🎯 QCM Master Pro (Export HTML/PDF)")
    csv_in = st.text_area("Collez votre CSV (|)", height=250)
    
    if csv_in:
        # --- CALCUL ET AFFICHAGE DES STATISTIQUES ---
        try:
            total_stats, sing_stats, mult_stats, dist_stats = perform_stats(csv_in)
            st.subheader("📊 Statistiques du QCM")
            stat_c1, stat_c2, stat_c3 = st.columns(3)
            stat_c1.metric("Total Questions", total_stats)
            stat_c2.metric("Choix Unique", sing_stats)
            stat_c3.metric("Choix Multiple", mult_stats)
            
            dist_str = " | ".join([f"**{k}**: {v:.1f}%" for k, v in sorted(dist_stats.items())])
            st.info(f"📍 **Distribution des réponses :** {dist_str}")
        except Exception as e:
            st.warning(f"Calcul des stats impossible : {e}")

        html_out = generate_html_content(csv_in, doc_title, use_3_col, add_qr)
        
        c1, c2 = st.columns(2)
        with c1:
            if st.button("✨ GÉNÉRER HTML"):
                with open(f"{out_name}.html", "w", encoding="utf-8") as f: f.write(html_out)
                st.success(f"Fichier '{out_name}.html' créé !")
                st.download_button("📥 Télécharger HTML", html_out, f"{out_name}.html")
        with c2:
            pdf_bytes = convert_html_to_pdf(html_out)
            if pdf_bytes:
                st.download_button("📄 TÉLÉCHARGER PDF", pdf_bytes, f"{out_name}.pdf")
        
        with st.expander("👁️ Aperçu du document"):
            st.components.v1.html(html_out, height=600, scrolling=True)

else:
    st.header("⚡ Mode Quiz Flash Interactif")
    
    # Hide source area if quiz is running to feel like an exam
    if not st.session_state.quiz_started:
        csv_quiz = st.text_area("Source CSV du Quiz", height=150, help="Collez le contenu CSV ici avant de démarrer.")
    else:
        # Keep data in session or re-parse from hidden area
        csv_quiz = st.session_state.get('last_csv_data', "")
        if not csv_quiz: # Fallback if first run
             st.warning("Veuillez réinitialiser et coller le CSV.")
             st.stop()

    if csv_quiz:
        st.session_state.last_csv_data = csv_quiz
        questions = parse_csv(csv_quiz)
        
        if st.session_state.quiz_started:
            # Chrono logic
            elapsed = time.time() - st.session_state.start_time
            total_sec = time_limit * 60
            remaining = max(0, total_sec - elapsed)
            percent_left = (remaining / total_sec) * 100
            
            # Timer color logic: turn red if < 10%
            timer_color = "#e74c3c" if percent_left <= 10 else "#27ae60"
            border_color = "#c0392b" if percent_left <= 10 else "#2c3e50"

            st.markdown(f"""
                <style>
                .stApp {{ background-color: #ffffff; }}
                .stMain {{ max-width: 900px; margin: 0 auto; }}
                .sticky-timer {{
                    position: fixed;
                    top: 60px;
                    right: 20px;
                    background-color: {timer_color};
                    color: white;
                    padding: 15px 25px;
                    border-radius: 12px;
                    z-index: 1001;
                    font-weight: bold;
                    box-shadow: 0 4px 15px rgba(0,0,0,0.2);
                    font-size: 16pt;
                    border: 3px solid {border_color};
                    transition: all 0.5s ease;
                }}
                .exam-card {{
                    background: #fff;
                    padding: 25px;
                    border-radius: 10px;
                    border: 1px solid #eee;
                    margin-bottom: 25px;
                    box-shadow: 0 2px 5px rgba(0,0,0,0.05);
                }}
                </style>
            """, unsafe_allow_html=True)

            # Display Sticky Timer
            st.markdown(f'<div class="sticky-timer">⏳ {str(timedelta(seconds=int(remaining)))}</div>', unsafe_allow_html=True)
            
            if remaining <= 0:
                st.error("⌛ TEMPS ÉCOULÉ !")
                st.session_state.score_submitted = True
            
            # Render questions in "Exam View"
            for idx, q in enumerate(questions):
                with st.container():
                    st.markdown(f'<div class="exam-card">', unsafe_allow_html=True)
                    st.markdown(f"### Question {idx+1}")
                    st.markdown(f"**{q['text']}**")
                    
                    letters = ['A', 'B', 'C', 'D', 'E', 'F'][:len(q['opts'])]
                    is_multi = len(q['ans']) > 1
                    
                    selected = []
                    if is_multi:
                        st.caption("*(Plusieurs réponses possibles)*")
                        for i, l in enumerate(letters):
                            if st.checkbox(f"{l}. {q['opts'][i]}", key=f"q{idx}_{l}"):
                                selected.append(l)
                    else:
                        choice = st.radio(f"Selection Q{idx+1}", 
                                         [f"{l}. {q['opts'][i]}" for i, l in enumerate(letters)],
                                         index=None, key=f"q{idx}", label_visibility="collapsed")
                        if choice: selected = [choice[0]]
                    
                    st.session_state.user_answers[idx] = "".join(sorted(selected))
                    st.markdown('</div>', unsafe_allow_html=True)
                
            if st.button("🏁 VALIDER MON EXAMEN", type="primary", use_container_width=True) or st.session_state.score_submitted:
                st.session_state.quiz_started = False
                st.session_state.score_submitted = True
                
                score = 0
                for idx, q in enumerate(questions):
                    if st.session_state.user_answers.get(idx, "") == q['ans']:
                        score += 1
                
                st.balloons()
                st.markdown(f"""
                    <div style="text-align:center; padding:30px; background:#f0f7f4; border-radius:15px; border:2px solid #27ae60;">
                        <h1 style="color:#27ae60; margin:0;">SCORE FINAL : {score} / {len(questions)}</h1>
                        <p style="font-size:16pt;">Résultat : <strong>{(score/len(questions)*100):.1f}%</strong></p>
                    </div>
                """, unsafe_allow_html=True)
                
                # --- GENERATION PDF RÉSULTATS ---
                result_html = generate_result_report(questions, st.session_state.user_answers, score, "Flash Quiz Result")
                result_pdf = convert_html_to_pdf(result_html)
                if result_pdf:
                    st.download_button("📄 TÉLÉCHARGER LE RAPPORT COMPLET (PDF)", result_pdf, "resultats_examen.pdf", mime="application/pdf", use_container_width=True)
                
                st.subheader("📝 Correction détaillée")
                for idx, q in enumerate(questions):
                    u_ans = st.session_state.user_answers.get(idx, "NULL")
                    if u_ans == q['ans']:
                        st.success(f"**Q{idx+1}**: Correct ! Votre réponse : {u_ans}")
                    else:
                        st.error(f"**Q{idx+1}**: Incorrect. Votre réponse : {u_ans} | Correcte : {q['ans']}")
                        st.info(f"💡 **Explication** : {q['expl']}")
        else:
            st.info("👋 Prêt à commencer ? Collez votre CSV ci-dessus, puis cliquez sur **🚀 DÉMARRER LE QUIZ** dans la barre latérale.")

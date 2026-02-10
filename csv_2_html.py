import tkinter as tk
from tkinter import scrolledtext, filedialog, messagebox, ttk
import csv
import io
import os
import webbrowser
from collections import Counter

class QCMGeneratorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("🎯 QCM Pro Generator v2.1 (Classic Style)")
        self.root.geometry("1000x850")
        self.root.configure(bg="#f4f7f6")
        self.primary_color = "#2c3e50"
        self.secondary_color = "#27ae60"
        self.setup_ui()

    def setup_ui(self):
        header = tk.Frame(self.root, bg=self.primary_color, pady=15)
        header.pack(fill=tk.X)
        tk.Label(header, text="🎯 QCM Pro Generator (Classic)", font=("Helvetica", 20, "bold"), bg=self.primary_color, fg="white").pack()
        
        main_frame = tk.Frame(self.root, bg="#f4f7f6", padx=20, pady=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        config_frame = tk.LabelFrame(main_frame, text="⚙️ Configuration", font=("Helvetica", 10, "bold"), bg="white", padx=15, pady=10)
        config_frame.pack(fill=tk.X, pady=(0, 15))

        row1 = tk.Frame(config_frame, bg="white")
        row1.pack(fill=tk.X)
        tk.Label(row1, text="Titre:", bg="white").pack(side=tk.LEFT, padx=(0, 5))
        self.title_var = tk.StringVar(value="QCM NLP")
        tk.Entry(row1, textvariable=self.title_var, width=35).pack(side=tk.LEFT, padx=(0, 20))
        
        tk.Label(row1, text="Fichier:", bg="white").pack(side=tk.LEFT, padx=(0, 5))
        self.file_var = tk.StringVar(value="qcm_nlp")
        tk.Entry(row1, textvariable=self.file_var, width=20).pack(side=tk.LEFT)

        row2 = tk.Frame(config_frame, bg="white")
        row2.pack(fill=tk.X, pady=(10, 0))
        tk.Label(row2, text="Mise en page PDF:", bg="white").pack(side=tk.LEFT, padx=(0, 5))
        self.col_style_var = tk.BooleanVar(value=True)
        tk.Radiobutton(row2, text="3 Colonnes (Original)", variable=self.col_style_var, value=True, bg="white").pack(side=tk.LEFT, padx=10)
        tk.Radiobutton(row2, text="1 Colonne", variable=self.col_style_var, value=False, bg="white").pack(side=tk.LEFT, padx=10)
        
        self.auto_open_var = tk.BooleanVar(value=True)
        tk.Checkbutton(row2, text="Ouvrir HTML après création", variable=self.auto_open_var, bg="white").pack(side=tk.RIGHT)

        text_frame = tk.LabelFrame(main_frame, text="📝 CSV Content (|)", bg="white", padx=10, pady=10)
        text_frame.pack(fill=tk.BOTH, expand=True)
        self.text_area = scrolledtext.ScrolledText(text_frame, font=("Consolas", 10))
        self.text_area.pack(fill=tk.BOTH, expand=True)
        
        button_frame = tk.Frame(main_frame, bg="#f4f7f6", pady=10)
        button_frame.pack(fill=tk.X)
        tk.Button(button_frame, text="🗑️ Effacer", command=lambda: self.text_area.delete("1.0", tk.END), bg="#e74c3c", fg="white", padx=15).pack(side=tk.LEFT)
        tk.Button(button_frame, text="✨ GÉNÉRER HTML (Style Original)", command=self.generate, bg=self.secondary_color, fg="white", font=("Helvetica", 11, "bold"), padx=30).pack(side=tk.RIGHT)

    def calculate_stats(self, csv_text):
        f = io.StringIO(csv_text); reader = csv.reader(f, delimiter='|'); next(reader, None)
        total, single, multi, letters = 0, 0, 0, []
        for row in reader:
            if len(row) < 7: continue
            total += 1
            ans = str(row[7] if len(row) >= 9 else row[5]).strip().upper().replace(',', '').replace(' ', '')
            if len(ans) > 1: multi += 1
            else: single += 1
            for char in ans:
                if char in 'ABCDEF': letters.append(char)
        counts = Counter(letters); total_l = len(letters) if letters else 1
        dist = {k: (v/total_l * 100) for k, v in counts.items()}
        return total, single, multi, dist

    def generate_html(self, csv_text, title, use_cols):
        col_style = "column-count: 3; column-gap: 0.5cm;" if use_cols else ""
        html = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><title>{title}</title>
<style>
    body {{ font-family: 'Georgia', serif; line-height: 1.5; color: #333; max-width: 900px; margin: 0 auto; padding: 20px; background-color: #fcfcfc; }}
    h1 {{ text-align: center; color: #2c3e50; border-bottom: 2px solid #2c3e50; padding-bottom: 10px; }}
    .q-block {{ background-color: #fff; border: 1px solid #ddd; border-radius: 5px; padding: 15px; margin-bottom: 15px; break-inside: avoid; }}
    .q-text {{ font-weight: bold; font-size: 1.1em; color: #2c3e50; margin-bottom: 10px; }}
    .opts {{ list-style: none; padding: 0; margin: 0; }}
    .opts li {{ margin-bottom: 4px; padding-left: 5px; font-size: 0.95em; }}
    .opts li::before {{ content: attr(data-letter) ". "; font-weight: bold; color: #555; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 30px; font-size: 0.9em; }}
    th, td {{ border: 1px solid #bdc3c7; padding: 8px; text-align: left; }}
    th {{ background-color: #2c3e50; color: white; }}
    tr:nth-child(even) {{ background-color: #f2f2f2; }}
    .correct {{ font-weight: bold; color: #27ae60; }}
    @media print {{
        @page {{ size: A4; margin: 0.8cm; }}
        body {{ font-size: 8pt; background-color: white; color: black; max-width: none; padding: 0; }}
        h1 {{ font-size: 14pt; margin: 0 0 10px 0; }}
        .wrapper {{ {col_style} }}
        .q-block {{ border: none; box-shadow: none; padding: 0; margin-bottom: 8px; border-bottom: 1px dashed #ccc; padding-bottom: 4px; }}
        .q-text {{ font-size: 8pt; margin-bottom: 3px; color: #000; }}
        .opts li {{ font-size: 7.5pt; margin-bottom: 1px; }}
        .ans-sec {{ page-break-before: always; }}
        table {{ font-size: 8pt; }}
        th {{ background-color: #ddd !important; color: black !important; }}
    }}
</style></head>
<body><h1>{title}</h1><div class="wrapper">"""
        
        f = io.StringIO(csv_text); reader = csv.reader(f, delimiter='|'); next(reader, None)
        ans_rows, q_num = "", 1
        for row in reader:
            if len(row) < 7: continue
            q = row[0].strip()
            if len(row) >= 9:
                opts = [row[i].strip() for i in range(1, 7)]
                c, e, lets = row[7].strip(), row[8].strip(), ['A', 'B', 'C', 'D', 'E', 'F']
            else:
                opts = [row[i].strip() for i in range(1, 5)]
                c, e, lets = row[5].strip(), row[6].strip(), ['A', 'B', 'C', 'D']
            
            html += f'<div class="q-block"><div class="q-text">{q_num}. {q}</div><ul class="opts">'
            for i, opt in enumerate(opts):
                if opt: html += f'<li data-letter="{lets[i]}">{opt}</li>'
            html += '</ul></div>'
            ans_rows += f'<tr><td>{q_num}</td><td class="correct">{c}</td><td>{e}</td></tr>'
            q_num += 1
            
        return html + f'</div><div class="ans-sec"><h2>Réponses</h2><table><thead><tr><th>N°</th><th>Réponse</th><th>Explication</th></tr></thead><tbody>{ans_rows}</tbody></table></div></body></html>'

    def generate(self):
        csv_data = self.text_area.get("1.0", tk.END).strip()
        if not csv_data: return
        try:
            total, sing, mult, dist = self.calculate_stats(csv_data)
            html_out = self.generate_html(csv_data, self.title_var.get(), self.col_style_var.get())
            file_path = filedialog.asksaveasfilename(initialfile=self.file_var.get(), defaultextension=".html", filetypes=[("HTML", "*.html")])
            if file_path:
                with open(file_path, "w", encoding="utf-8") as f: f.write(html_out)
                msg = f"✅ Export réussi !\nQuestions : {total}\n(Unique: {sing} | Multiple: {mult})\n\nDistribution :\n"
                for k, v in sorted(dist.items()): msg += f"  {k} : {v:.1f}%\n"
                messagebox.showinfo("Stats", msg)
                if self.auto_open_var.get(): webbrowser.open(f"file://{os.path.abspath(file_path)}")
        except Exception as e: messagebox.showerror("Erreur", str(e))

if __name__ == "__main__":
    root = tk.Tk(); app = QCMGeneratorApp(root); root.mainloop()
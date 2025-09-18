# Anschreiben-Generator (Streamlit)

Erstellt aus Lebenslauf (PDF) und Stellenanzeige ein maßgeschneidertes Anschreiben mit OpenAI.  
Enthält Editor, Überarbeiten-Funktion, Standard-PDF-Export **und** LaTeX-Export (moderncv-Template).

---

## Features

- 🔐 **OpenAI-API-Key** Eingabe (geheim/Passwortfeld)
- 📄 **Inputs**: Lebenslauf als **PDF** + **Stellenanzeige** (Text)
- ✍️ **Anschreiben generieren** (auf Basis von CV + Anzeige)
- 🧰 **Bearbeiten & Überarbeiten**  
  - Anschreiben im Editor frei anpassen  
  - Änderungswünsche angeben → Modell überarbeitet den aktuellen Entwurf  
  - Der **aktualisierte Text** erscheint sofort im Editor
- 📥 **Export**  
  - **Standard-PDF** direkt aus dem Editor  
  - **LaTeX-PDF (moderncv)**: Anschreiben + CV-Auszüge werden in ein LaTeX-Template eingefügt und (falls möglich) zu PDF kompiliert
- 🔽 **Modell-Auswahl** via Dropdown (Standard: `gpt-4o-mini`)  
  > Hinweis: Wenn dein Account weitere Modelle bereitstellt (z. B. `gpt-5`), kannst du sie in der Modellliste ergänzen.

---

## Systemvoraussetzungen

- Python 3.9+
- OpenAI-Account + API-Key
- Für LaTeX-Export (optional): TeX-Distribution mit `pdflatex` und **moderncv** (z. B. TeX Live / MiKTeX)

---

## Installation (Linux, alles in einem Befehl)

```bash
sudo apt-get update && sudo apt-get install -y texlive-latex-extra texlive-fonts-recommended texlive-fonts-extra texlive-lang-german latexmk && python3 -m pip install --upgrade pip && python3 -m pip uninstall -y pyfpdf && python3 -m pip install -U streamlit openai pypdf fpdf2

## Pakete installieren

python -m pip install -r requirements.txt

# app.py
import io
import textwrap
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Optional, Tuple
import unicodedata
import os
import re

import streamlit as st

# --- URL-Import Dependencies ---
try:
    import requests
    from bs4 import BeautifulSoup
except Exception:
    requests = None  # type: ignore
    BeautifulSoup = None  # type: ignore

# PDF-Reader: pypdf bevorzugt, PyPDF2 als Fallback
try:
    from pypdf import PdfReader
except Exception:
    try:
        from PyPDF2 import PdfReader  # type: ignore
    except Exception:
        PdfReader = None  # type: ignore

# OpenAI SDK
try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore

# PDF-Erzeugung (ohne LaTeX)
try:
    from fpdf import FPDF  # fpdf2
except Exception:
    FPDF = None  # type: ignore


# -------------------------------- Defaults --------------------------------

DEFAULT_LATEX_TEMPLATE = r"""
%% start of file 'anschreiben.tex'
\documentclass[11pt,a4paper,roman]{moderncv}
\usepackage[ngerman]{babel}

% moderncv themes
\moderncvstyle{classic}
\moderncvcolor{green}

% character encoding
\usepackage[utf8]{inputenc}

% adjust the page margins
\usepackage[scale=0.75]{geometry}

% personal data
\name{Lorem}{Ipsum}
\title{Bewerbung als \textbf{Specialist Softwareentwicklung (w/m/d)}}
\address{Loremstraße 123}{12345 Ipsumstadt}{Deutschland}
\phone[mobile]{+49~170~0000000}
\email{lorem.ipsum@example.com}

\begin{document}

%-----       letter       ---------------------------------------------------------
% recipient data
\recipient{\textbf{Lorem Consulting GmbH}}{Personalabteilung}
\date{\today}
\opening{Sehr geehrte Damen und Herren,}
\closing{Mit freundlichen Grüßen}
% \enclosure[Anlagen]{Lebenslauf, Zeugnisse}
\makelettertitle

Mit großem Interesse bewerbe ich mich als \textbf{Specialist Softwareentwicklung}. Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed non arcu eget ipsum efficitur luctus. Integer in sapien vel metus interdum euismod. Aenean bibendum, mi a rhoncus pretium, \textbf{qualitativ hochwertige Software} fermentum magna, vitae tempus arcu ipsum a metus.

Suspendisse potenti. Quisque vitae orci id risus gravida vulputate. Curabitur ut ante vitae neque elementum accumsan. Phasellus pharetra, elit non porta aliquet, leo libero faucibus arcu, a efficitur arcu lacus ut risus. In sit amet nibh finibus, \textbf{Skalierbarkeit}, luctus dolor in, maximus sem. Praesent \textbf{agile Zusammenarbeit} und \textbf{saubere Schnittstellen} als zentrale Arbeitsweise.

Praesent a magna sed nibh vestibulum volutpat. Etiam venenatis, lorem at dictum euismod, orci enim hendrerit sem, at ullamcorper urna lectus id nunc. Mauris pulvinar, lorem et mattis elementum, nunc justo luctus mi, a convallis lorem arcu a tortor. Donec ac nisl at quam ultricies varius, mit Fokus auf \textbf{Backend-Entwicklung}, \textbf{Datenverarbeitung} und \textbf{stabile Produktionssysteme}.

Nullam nec purus non risus hendrerit sodales. Integer pulvinar sem ac nunc blandit, nec ultricies turpis pharetra. Pellentesque habitant morbi tristique senectus et netus et malesuada fames ac turpis egestas. Cras dictum tincidunt elit, in pretium quam bibendum vitae. Ich freue mich darauf, \textbf{Prototypen iterativ zu entwickeln} und \textbf{messbaren Nutzen} zu schaffen.

\makeletterclosing

\end{document}
%% end of file 'anschreiben.tex'
"""


# ------------------------------- Hilfsfunktionen -------------------------------

def extract_text_from_pdf(file) -> str:
    if PdfReader is None:
        st.error("Bitte installiere entweder 'pypdf' oder 'PyPDF2', um PDF-Text zu extrahieren.")
        return ""
    try:
        reader = PdfReader(file)
        pages_text = []
        for page in getattr(reader, "pages", []):
            try:
                txt = page.extract_text() or ""
            except Exception:
                txt = ""
            pages_text.append(txt)
        return "\n".join(pages_text).strip()
    except Exception as e:
        st.error(f"PDF konnte nicht gelesen werden: {e}")
        return ""


def sanitize_for_pdf(text: str) -> str:
    return text.encode("latin-1", "replace").decode("latin-1")


def make_pdf(letter_text: str, title: str = "Anschreiben") -> bytes:
    if FPDF is None:
        st.error("Bitte installiere 'fpdf2' mit: pip install fpdf2")
        return b""

    letter_text = sanitize_for_pdf(letter_text)
    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    pdf.set_title(title)

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, title, ln=True)

    pdf.ln(2)
    pdf.set_font("Helvetica", size=12)
    for para in letter_text.split("\n\n"):
        para = para.strip()
        if not para:
            pdf.ln(4)
            continue
        wrapped = "\n".join(textwrap.wrap(para, width=90, replace_whitespace=False))
        pdf.multi_cell(0, 6, wrapped)
        pdf.ln(2)

    out = pdf.output(dest="S")
    if isinstance(out, (bytes, bytearray)):
        return bytes(out)
    else:
        return out.encode("latin-1", "ignore")


def truncate(text: str, max_chars: int = 24000) -> str:
    if len(text) <= max_chars:
        return text
    head = text[: max_chars // 2]
    tail = text[-max_chars // 2 :]
    return head + "\n\n…(gekürzt)…\n\n" + tail


def build_system_prompt() -> str:
    return (
        "Du bist ein erfahrener deutschsprachiger Bewerbungstexter. "
        "Erstelle ein prägnantes, professionelles Anschreiben (max. 1 Seite) im formellen 'Sie'-Ton. "
        "Passe Inhalt und Schwerpunkt auf die Stellenanzeige an und nutze belegbare Punkte aus dem Lebenslauf. "
        "Struktur: Absender/Betreff optional weglassen, Einstieg mit klarer Motivation, 2–3 Absätze mit relevanten "
        "Erfahrungen/Erfolgen (quantifiziert, sofern möglich), Abschluss mit Call-to-Action und freundlichem Gruß. "
        "Kein Markdown, keine Aufzählungszeichen, reiner Fließtext."
    )


def build_initial_user_prompt(cv_text: str, job_text: str) -> str:
    return (
        "Erstelle ein individuelles Anschreiben basierend auf folgenden Quellen.\n\n"
        "=== STELLENANZEIGE ===\n"
        f"{job_text}\n\n"
        "=== LEBENSLAUF ===\n"
        f"{cv_text}\n\n"
        "Beziehe dich ausdrücklich auf Anforderungen aus der Anzeige und verknüpfe sie mit passender Erfahrung "
        "aus dem Lebenslauf. Falls konkrete Firmennamen/Kontakte in der Anzeige fehlen, formuliere neutral."
    )


def build_refine_user_prompt(current_letter: str, change_request: str, cv_text: str, job_text: str) -> str:
    return (
        "Überarbeite das folgende Anschreiben gemäß der Änderungswünsche. "
        "Behalte Stil und Struktur professionell und kompakt (max. 1 Seite). "
        "Nutze weiterhin die Informationen aus Stellenanzeige und Lebenslauf.\n\n"
        "=== AKTUELLES ANSCHREIBEN ===\n"
        f"{current_letter}\n\n"
        "=== ÄNDERUNGSWÜNSCHE ===\n"
        f"{change_request}\n\n"
        "=== STELLENANZEIGE ===\n"
        f"{job_text}\n\n"
        "=== LEBENSLAUF ===\n"
        f"{cv_text}\n\n"
        "Gib ausschließlich den finalen Brieftext aus (kein Markdown, keine Erklärungen)."
    )


def build_latex_fill_prompt(letter_text: str, cv_text: str, latex_template: str, job_text: str, header: dict) -> str:
    """
    Stellt dem Modell optional ausfüllbare Kopf-Felder bereit.
    Nur NICHT-LEERE Felder sollen ersetzt/gesetzt werden, leere unverändert lassen.
    """
    header_instructions = (
        "- Setze die folgenden Felder NUR, wenn ein Wert angegeben ist; lasse sie sonst unverändert:\n"
        "  * \\name{Vorname}{Nachname}\n"
        "  * \\address{Zeile 1}{Zeile 2}{Land}\n"
        "  * \\phone[mobile]{...}\n"
        "  * \\email{...}\n"
        "  * \\recipient{Firma/Institution}{Abteilung}\n"
        "  * \\opening{Anrede}\n"
    )

    header_values = (
        f"- Vorname: {header.get('sender_first','')}\n"
        f"- Nachname: {header.get('sender_last','')}\n"
        f"- Adresse Zeile 1: {header.get('sender_addr1','')}\n"
        f"- Adresse Zeile 2: {header.get('sender_addr2','')}\n"
        f"- Land/Ort: {header.get('sender_country','')}\n"
        f"- Mobil: {header.get('sender_phone','')}\n"
        f"- E-Mail: {header.get('sender_email','')}\n"
        f"- Empfänger Firma: {header.get('recipient_company','')}\n"
        f"- Empfänger Abteilung: {header.get('recipient_dept','')}\n"
        f"- Anrede (opening): {header.get('opening_line','')}\n"
    )

    return (
        "Fülle das folgende LaTeX-Template (moderncv Brief) mit den bereitgestellten Inhalten.\n"
        "- GIB EIN KOMPLETTES, KOMPILIERBARES LATEX-DOKUMENT zurück (mit \\documentclass ... \\begin{document} ... \\end{document}).\n"
        "- Ersetze 100% des vorhandenen Blindtexts ZWISCHEN \\makelettertitle und \\makeletterclosing durch den Brieftext (kein Lorem/Platzhalter).\n"
        "- Kopf-/Kontaktdaten bitte gemäß den optionalen Feldern setzen (siehe unten). Leere Felder unverändert lassen.\n"
        "- Belasse sonstige Präambel/Packages.\n"
        "- ESCAPE alle LaTeX-Sonderzeichen (# $ % & _ { } ~ ^ \\\\) korrekt.\n"
        "- Keine Erklärungen, KEINE Markdown-Fences, NUR LaTeX.\n\n"
        "=== OPTIONALE KOPF-FELDER ===\n"
        f"{header_instructions}\n"
        "Werte:\n"
        f"{header_values}\n"
        "=== BRIEF (LETTER) ===\n"
        f"{letter_text}\n\n"
        "=== LEBENSLAUF (CV Text) ===\n"
        f"{cv_text}\n\n"
        "=== STELLENANZEIGE (Kontext) ===\n"
        f"{job_text}\n\n"
        "=== LATEX TEMPLATE ===\n"
        f"{latex_template}\n\n"
        "Gib ausschließlich das finale LaTeX-Dokument aus."
    )


def build_qa_user_prompt(cv_text: str, job_text: str, question: str) -> str:
    return (
        "Beantworte die folgende Frage präzise anhand der bereitgestellten Kontexte. "
        "Wenn eine Information nicht in CV oder Anzeige steht, kennzeichne das klar.\n\n"
        "=== STELLENANZEIGE ===\n"
        f"{job_text}\n\n"
        "=== LEBENSLAUF ===\n"
        f"{cv_text}\n\n"
        "=== FRAGE ===\n"
        f"{question}\n"
    )


def _transliterate_to_ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def call_openai_chat(api_key: str, model: str, user_prompt: str, system_prompt: Optional[str] = None) -> str:
    if OpenAI is None:
        st.error("Bitte installiere das OpenAI-Python-SDK: pip install openai")
        return ""

    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    def _do_call(u_prompt: str, s_prompt: Optional[str]) -> str:
        client = OpenAI(api_key=api_key)
        messages = []
        if s_prompt:
            messages.append({"role": "system", "content": s_prompt})
        messages.append({"role": "user", "content": u_prompt})
        resp = client.chat.completions.create(model=model, messages=messages)
        return (resp.choices[0].message.content or "").strip()

    try:
        return _do_call(user_prompt, system_prompt)
    except UnicodeEncodeError:
        try:
            u2 = user_prompt.encode("utf-8", "ignore").decode("utf-8")
            s2 = system_prompt.encode("utf-8", "ignore").decode("utf-8") if system_prompt else None
            return _do_call(u2, s2)
        except UnicodeEncodeError:
            u3 = _transliterate_to_ascii(user_prompt)
            s3 = _transliterate_to_ascii(system_prompt) if system_prompt else None
            return _do_call(u3, s3)
    except Exception as e:
        st.error(f"OpenAI-Fehler: {e}")
        return ""


def strip_code_fences(s: str) -> str:
    s2 = s.strip()
    if s2.startswith("```"):
        lines = s2.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return s2


def compile_latex_to_pdf(tex_source: str) -> Tuple[Optional[bytes], Optional[str]]:
    if shutil.which("pdflatex") is None:
        return None, "pdflatex nicht gefunden. Bitte installiere TeX Live/MiKTeX + 'moderncv' oder kompiliere die .tex-Datei lokal."
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        tex_path = td_path / "main.tex"
        tex_path.write_text(tex_source, encoding="utf-8")
        try:
            cmd = ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "main.tex"]
            proc = subprocess.run(cmd, cwd=td_path, capture_output=True, text=True, timeout=120)
            log = proc.stdout + "\n" + proc.stderr
            pdf_path = td_path / "main.pdf"
            if proc.returncode == 0 and pdf_path.exists():
                return pdf_path.read_bytes(), log
            else:
                return None, log
        except Exception as e:
            return None, f"LaTeX-Kompilierungsfehler: {e}"


def fetch_text_from_url(url: str) -> str:
    if not requests or not BeautifulSoup:
        st.error("Bitte installiere 'requests' und 'beautifulsoup4' für den URL-Import (pip install requests beautifulsoup4).")
        return ""
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "text" not in content_type and "html" not in content_type:
            return resp.text.strip()[:200000]
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        for tag in soup.select("header, footer, nav, aside"):
            tag.decompose()
        text = soup.get_text(separator="\n")
        lines = [ln.strip() for ln in text.splitlines()]
        lines = [ln for ln in lines if ln]
        return "\n".join(lines)[:200000]
    except Exception as e:
        st.error(f"URL konnte nicht gelesen werden: {e}")
        return ""


# ------------------------------- Streamlit UI -------------------------------

st.set_page_config(page_title="Anschreiben-Generator (CV + Stellenanzeige)", page_icon="✉️", layout="wide")
st.title("✉️ Anschreiben-Generator")
st.caption("Lade deinen Lebenslauf als PDF hoch, füge die Stellenanzeige ein und erzeuge ein individuelles Anschreiben. Überarbeite den Text, exportiere als Standard-PDF oder fülle ein LaTeX-Template (moderncv) und kompiliere es zu PDF.")

# --- Session-State initialisieren ---
for key, default in [
    ("letter_text", ""),
    ("cv_text_cache", ""),
    ("job_text_cache", ""),
    ("change_request", ""),
    ("latex_template", DEFAULT_LATEX_TEMPLATE),
    ("_applied_latex_upload_hash", None),
    # Prompt-Editor State
    ("sys_prompt", ""),
    ("initial_user_prompt", ""),
    ("refine_user_prompt", ""),
    ("latex_user_prompt", ""),
    # Q&A State
    ("qa_question", ""),
    ("qa_answer", ""),
    # UI State
    ("job_text", ""),
    ("jd_url", ""),
    # Header fields
    ("sender_first",""),
    ("sender_last",""),
    ("sender_addr1",""),
    ("sender_addr2",""),
    ("sender_country",""),
    ("sender_phone",""),
    ("sender_email",""),
    ("recipient_company",""),
    ("recipient_dept",""),
    ("opening_line",""),
]:
    if key not in st.session_state:
        st.session_state[key] = default

with st.sidebar:
    st.subheader("🔐 OpenAI")
    api_key = st.text_input("OpenAI API Key", type="password", help="Wird nur lokal in dieser Sitzung genutzt.")

    MODEL_MAP = {
        "GPT-5": "gpt-5",
        "GPT-5 mini": "gpt-5-mini",
        "GPT-5 nano": "gpt-5-nano",
        "gpt-4o-mini": "gpt-4o-mini",
        "gpt-4o": "gpt-4o",
        "gpt-4.1-mini": "gpt-4.1-mini",
        "gpt-4.1": "gpt-4.1",
    }
    MODEL_OPTIONS = list(MODEL_MAP.keys())
    model_display = st.selectbox("Modell", options=MODEL_OPTIONS, index=0)
    model_id = MODEL_MAP.get(model_display, model_display)
    st.caption(f"Verwendete API-ID: `{model_id}`")

col1, col2 = st.columns(2, gap="large")

with col1:
    cv_file = st.file_uploader("Lebenslauf (PDF)", type=["pdf"])
    cv_text = ""
    if cv_file is not None:
        cv_text = extract_text_from_pdf(cv_file)
        if cv_text:
            st.success("Lebenslauf erkannt.")
            st.session_state.cv_text_cache = truncate(cv_text)
        with st.expander("Vorschau: erkannter CV-Text"):
            st.text_area("CV-Text", (cv_text or st.session_state.get("cv_text_cache", ""))[:5000], height=200)

# 🌐 Stellenanzeige aus URL laden (optional)
st.subheader("🌐 Stellenanzeige aus URL (optional)")
url_col, load_btn_col = st.columns([3, 1])
with url_col:
    jd_url = st.text_input("URL der Stellenanzeige", key="jd_url", placeholder="https://…")
with load_btn_col:
    if st.button("Anzeige von URL laden", use_container_width=True):
        if not jd_url:
            st.warning("Bitte zuerst eine URL eingeben.")
        else:
            loaded_text = fetch_text_from_url(jd_url)
            if loaded_text:
                st.session_state["job_text"] = loaded_text
                st.session_state["job_text_cache"] = truncate(loaded_text)
                st.success("Stellenanzeige aus URL geladen.")
            else:
                st.warning("Konnte keinen Text von der URL laden.")

with col2:
    job_text = st.text_area("Stellenanzeige (Text)", key="job_text", placeholder="Füge hier die vollständige Stellenanzeige ein …", height=260)

# 📌 Briefkopf-Felder (optional) – diese steuern die LaTeX-Header-Ersetzung durch das Modell
with st.expander("📌 Briefkopf-Felder (optional)", expanded=False):
    s1, s2 = st.columns(2, gap="large")
    with s1:
        st.text_input("Vorname", key="sender_first")
        st.text_input("Nachname", key="sender_last")
        st.text_input("Adresse – Zeile 1", key="sender_addr1", placeholder="z. B. Musterstraße 1")
        st.text_input("Adresse – Zeile 2", key="sender_addr2", placeholder="z. B. 12345 Musterstadt")
        st.text_input("Land/Ort", key="sender_country", placeholder="Deutschland")
    with s2:
        st.text_input("Mobilnummer", key="sender_phone", placeholder="+49 …")
        st.text_input("E-Mail", key="sender_email", placeholder="ich@example.com")
        st.text_input("Empfänger – Firma/Institution", key="recipient_company", placeholder="z. B. ACME GmbH")
        st.text_input("Empfänger – Abteilung", key="recipient_dept", placeholder="z. B. Personalabteilung")
        st.text_input("Anrede (opening)", key="opening_line", placeholder="Sehr geehrte Frau/geehrter Herr …")

# LaTeX-Template
with st.expander("📄 LaTeX-Template (optional – für Template-PDF)", expanded=False):
    up = st.file_uploader("LaTeX-Template hochladen (.tex)", type=["tex"], key="latex_uploader")
    if up is not None:
        content = up.read().decode("utf-8", errors="replace")
        up_hash = (len(content), hash(content))
        if st.session_state["_applied_latex_upload_hash"] != up_hash:
            st.session_state["latex_template"] = content
            st.session_state["_applied_latex_upload_hash"] = up_hash
        st.code(st.session_state["latex_template"], language="latex")
        st.info("Dieses hochgeladene Template wird verwendet. (Bearbeiten im Codeblock: Template erneut hochladen oder unten ohne Upload bearbeiten.)")
    else:
        st.text_area("LaTeX-Template bearbeiten (Default ist vorausgefüllt)", key="latex_template", height=260, help="Ohne Upload wird dieses verwendet.")

st.markdown("---")

# --- Prompt-Editor (ausklappbar, default zu) ---
def build_defaults_if_empty():
    if not st.session_state.sys_prompt:
        st.session_state.sys_prompt = build_system_prompt()
    if not st.session_state.initial_user_prompt:
        st.session_state.initial_user_prompt = build_initial_user_prompt(
            truncate(st.session_state.get("cv_text_cache", "")),
            truncate(st.session_state.get("job_text_cache", st.session_state.get("job_text", ""))),
        )
    if not st.session_state.refine_user_prompt:
        st.session_state.refine_user_prompt = build_refine_user_prompt(
            st.session_state.get("letter_text", ""),
            st.session_state.get("change_request", "Bitte stilistisch glätten & präzisieren."),
            truncate(st.session_state.get("cv_text_cache", "")),
            truncate(st.session_state.get("job_text_cache", st.session_state.get("job_text", ""))),
        )
    if not st.session_state.latex_user_prompt:
        st.session_state.latex_user_prompt = build_latex_fill_prompt(
            st.session_state.get("letter_text", ""),
            truncate(st.session_state.get("cv_text_cache", "")),
            st.session_state.get("latex_template", DEFAULT_LATEX_TEMPLATE),
            truncate(st.session_state.get("job_text_cache", st.session_state.get("job_text", ""))),
            header={k: st.session_state.get(k,"") for k in [
                "sender_first","sender_last","sender_addr1","sender_addr2","sender_country",
                "sender_phone","sender_email","recipient_company","recipient_dept","opening_line"
            ]}
        )

def regenerate_prompts():
    cv_src = truncate(st.session_state.get("cv_text_cache", ""))
    job_src = truncate(st.session_state.get("job_text_cache", st.session_state.get("job_text", "")))
    current_letter = st.session_state.get("letter_text", "")
    change_req = st.session_state.get("change_request", "Bitte stilistisch glätten & präzisieren.")
    latex_template = st.session_state.get("latex_template", DEFAULT_LATEX_TEMPLATE)
    header = {k: st.session_state.get(k,"") for k in [
        "sender_first","sender_last","sender_addr1","sender_addr2","sender_country",
        "sender_phone","sender_email","recipient_company","recipient_dept","opening_line"
    ]}
    st.session_state["sys_prompt"] = build_system_prompt()
    st.session_state["initial_user_prompt"] = build_initial_user_prompt(cv_src, job_src)
    st.session_state["refine_user_prompt"] = build_refine_user_prompt(current_letter, change_req, cv_src, job_src)
    st.session_state["latex_user_prompt"] = build_latex_fill_prompt(current_letter, cv_src, latex_template, job_src, header)

with st.expander("🧠 Prompts (bearbeitbar)", expanded=False):
    st.caption("Diese Prompts werden 1:1 an das Modell gesendet. Mit „Vorschläge übernehmen“ kannst du sie aus den aktuellen Eingaben neu generieren.")
    build_defaults_if_empty()
    p1, p2 = st.columns(2, gap="large")
    with p1:
        st.text_area("System-Prompt", key="sys_prompt", height=180)
        st.text_area("User-Prompt: Anschreiben ERSTELLEN", key="initial_user_prompt", height=220)
    with p2:
        st.text_area("User-Prompt: Anschreiben ÜBERARBEITEN", key="refine_user_prompt", height=220)
        st.text_area("User-Prompt: LaTeX füllen", key="latex_user_prompt", height=220)

    if st.button("🔄 Vorschläge übernehmen (aus aktuellen Eingaben neu generieren)"):
        regenerate_prompts()
        st.success("Prompts aktualisiert.")

st.markdown("---")

# 🧩 Kontext-Q&A
st.subheader("🧩 Kontext-Q&A (Fragen zu CV & Stellenanzeige)")
st.caption("Stelle hier kurze Fragen. Ich nutze dafür deinen CV-Text und die Stellenanzeige als Kontext.")

qa_left, qa_right = st.columns(2, gap="large")
with qa_left:
    st.text_area("Deine Frage", key="qa_question", height=120, placeholder="z. B.: Welche 3 Anforderungen erfülle ich bereits gut?")
    if st.button("▶️ Frage senden"):
        if not api_key:
            st.error("Bitte gib zuerst deinen OpenAI API Key ein.")
        else:
            cv_src = truncate(st.session_state.get("cv_text_cache", ""))
            job_src = truncate(st.session_state.get("job_text_cache", st.session_state.get("job_text", "")))
            if not (cv_src and job_src):
                st.warning("Bitte zuerst CV-Text und Stellenanzeige bereitstellen (Upload/Eingabe oder URL).")
            else:
                qa_user = build_qa_user_prompt(cv_src, job_src, st.session_state.qa_question or "")
                qa_sys = "Du bist ein präziser, deutschsprachiger Karriere-Assistent. Antworte knapp und konkret."
                answer = call_openai_chat(api_key, model_id, qa_user, system_prompt=qa_sys)
                st.session_state.qa_answer = answer or "Keine Antwort erhalten."

with qa_right:
    st.text_area("Antwort", value=st.session_state.qa_answer or "", height=180, placeholder="Hier erscheint die Antwort …")

st.markdown("---")

# Änderungswünsche-Feld
st.subheader("📝 Entwurf bearbeiten")
st.caption("Gib Änderungswünsche ein und klicke auf Überarbeiten – oder editiere danach den Text direkt im großen Feld.")
st.text_area("Änderungswünsche (optional)", key="change_request", placeholder="Z. B.: 'Kürzer, stärker auf Datenanalyse fokussieren …'", height=120)

# Buttons
generate_col, refine_col, export_col, export_tex_col = st.columns([1, 1, 1, 1])

# Anschreiben erstellen – frischer Prompt + harte Validierung
clicked_generate = generate_col.button("🪄 Anschreiben erstellen", use_container_width=True, disabled=not api_key)
if clicked_generate:
    if not api_key:
        st.error("Bitte gib zuerst deinen OpenAI API Key ein.")
    else:
        if 'cv_text' in locals() and cv_text:
            st.session_state.cv_text_cache = truncate(cv_text)
        if st.session_state.get("job_text"):
            st.session_state.job_text_cache = truncate(st.session_state["job_text"])

        cv_src = (st.session_state.get("cv_text_cache") or "").strip()
        job_src = (st.session_state.get("job_text_cache", st.session_state.get("job_text", "")) or "").strip()

        missing = []
        if not cv_src: missing.append("CV-Text (PDF hochladen)")
        if not job_src: missing.append("Stellenanzeige (Text / URL)")
        if missing:
            st.warning("Bitte zuerst bereitstellen: " + ", ".join(missing) + ".")
        else:
            sys = st.session_state.get("sys_prompt") or build_system_prompt()
            user = build_initial_user_prompt(truncate(cv_src), truncate(job_src))
            with st.spinner("Erzeuge Anschreiben …"):
                letter = call_openai_chat(api_key, model_id, user, system_prompt=sys)
            if letter:
                st.session_state.letter_text = letter
                st.success("Anschreiben erstellt!")
            else:
                st.error("Keine Antwort vom Modell erhalten. Bitte erneut versuchen.")

# Überarbeiten – frischer Prompt
clicked_refine = refine_col.button("🔁 Überarbeiten mit Änderungswünschen", use_container_width=True, disabled=not (api_key and st.session_state.letter_text))
if clicked_refine:
    if not api_key:
        st.error("Bitte gib zuerst deinen OpenAI API Key ein.")
    else:
        if 'cv_text' in locals() and cv_text:
            st.session_state.cv_text_cache = truncate(cv_text)
        if st.session_state.get("job_text"):
            st.session_state.job_text_cache = truncate(st.session_state["job_text"])

        current_letter = (st.session_state.get("letter_text") or "").strip()
        change_req = (st.session_state.get("change_request") or "Bitte stilistisch glätten & präzisieren.").strip()
        cv_src = truncate(st.session_state.get("cv_text_cache", "")).strip()
        job_src = truncate(st.session_state.get("job_text_cache", st.session_state.get("job_text", ""))).strip()

        missing = []
        if not current_letter: missing.append("Anschreiben")
        if not cv_src: missing.append("CV-Text")
        if not job_src: missing.append("Stellenanzeige")

        if missing:
            st.warning("Bitte zuerst bereitstellen: " + ", ".join(missing) + ".")
        else:
            user = build_refine_user_prompt(current_letter, change_req, cv_src, job_src)
            sys = st.session_state.get("sys_prompt") or build_system_prompt()
            with st.spinner("Überarbeite Anschreiben …"):
                revised = call_openai_chat(api_key, model_id, user, system_prompt=sys)
            if revised:
                st.session_state.letter_text = revised
                st.success("Anschreiben überarbeitet!")
            else:
                st.error("Keine Antwort vom Modell erhalten. Bitte erneut versuchen.")

# Editor
st.text_area("Anschreiben (editierbar)", key="letter_text", height=360, placeholder="Hier erscheint der Entwurf …")

# Normaler PDF-Export
if export_col.button("📄 Als PDF herunterladen", use_container_width=True, disabled=not st.session_state.letter_text):
    pdf_bytes = make_pdf(st.session_state.letter_text, title="Anschreiben")
    if pdf_bytes:
        st.download_button("Jetzt PDF speichern", data=pdf_bytes, file_name="Anschreiben.pdf", mime="application/pdf", use_container_width=True)

# LaTeX-PDF-Export (LLM, Guardrails prüfen nur den Briefkörper)
if export_tex_col.button("🧪 LaTeX-PDF erzeugen", use_container_width=True, disabled=not (api_key and st.session_state.letter_text)):
    if not api_key:
        st.error("Bitte gib zuerst deinen OpenAI API Key ein.")
    else:
        header = {k: st.session_state.get(k,"") for k in [
            "sender_first","sender_last","sender_addr1","sender_addr2","sender_country",
            "sender_phone","sender_email","recipient_company","recipient_dept","opening_line"
        ]}
        user = build_latex_fill_prompt(
            st.session_state.letter_text or "",
            truncate(st.session_state.get("cv_text_cache", "")),
            st.session_state.get("latex_template", DEFAULT_LATEX_TEMPLATE),
            truncate(st.session_state.get("job_text_cache", st.session_state.get("job_text", ""))),
            header=header
        )
        latex_filled = call_openai_chat(api_key, model_id, user, system_prompt=None) or ""
        latex_filled = strip_code_fences(latex_filled).strip()

        # Guardrails: Struktur + nur Briefkörper prüfen (Header darf Platzhalter vom Template behalten, wenn Felder leer)
        missing_structure = not (
            "\\documentclass" in latex_filled and "\\begin{document}" in latex_filled and "\\end{document}" in latex_filled
        )
        body_match = re.search(r"\\makelettertitle(.*?)\\makeletterclosing", latex_filled, flags=re.DOTALL)
        letter_body = body_match.group(1) if body_match else latex_filled

        placeholder_tokens = ["Lorem ipsum", "Lorem Ipsum"]
        still_placeholder = any(tok in letter_body for tok in placeholder_tokens)

        if missing_structure:
            st.error("Das Modell hat kein komplettes LaTeX-Dokument zurückgegeben. Bitte erneut versuchen oder den Prompt im Prompts-Panel schärfen.")
        elif still_placeholder:
            st.error("Im Briefkörper sind noch Platzhalter/Lorem-Texte. Bitte im Prompts-Panel präzisieren und erneut generieren.")
        else:
            with st.expander("Vorschau: generiertes LaTeX", expanded=False):
                st.code(latex_filled, language="latex")

            st.download_button("⬇️ LaTeX (.tex) herunterladen", data=latex_filled.encode("utf-8"), file_name="Anschreiben_moderncv.tex", mime="text/x-tex", use_container_width=True)

            with st.spinner("Kompiliere LaTeX zu PDF …"):
                pdf_bytes, log = compile_latex_to_pdf(latex_filled)

            if pdf_bytes:
                st.success("LaTeX erfolgreich kompiliert.")
                st.download_button("⬇️ LaTeX-PDF herunterladen", data=pdf_bytes, file_name="Anschreiben_moderncv.pdf", mime="application/pdf", use_container_width=True)
            else:
                st.warning("PDF konnte nicht kompiliert werden (fehlt 'pdflatex' oder das Paket 'moderncv'?).")
                if log:
                    with st.expander("Kompilierungslog anzeigen"):
                        st.text(log)

st.markdown("---")
st.caption(
    "Hinweise: "
    "• Kopf-Felder nur ausfüllen, wenn sie im PDF/Anzeige nicht korrekt stehen – leere Felder lässt das Modell unverändert. "
    "• LaTeX-Export benötigt lokal 'pdflatex' und die Klasse 'moderncv'. "
    "• Für URL-Import ggf. 'pip install requests beautifulsoup4' ausführen."
)

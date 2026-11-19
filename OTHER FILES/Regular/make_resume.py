# -*- coding: utf-8 -*-
"""
Build resume.pdf, cover_letter_<slug>.pdf and portfolio_highlights.pdf from the
candidate-approved KB (resume_content_improve_research/knowledge_base/candidate_kb.json
+ old_files/data/candidate_profile.json). No fabricated content.

Usage: python make_resume.py "<Job Title>" [Company]
"""
import sys
import os

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, HRFlowable)

# ---------------------------------------------------------------- data (KB) --
NAME = "RAVAL MEETKUMAR RITESHKUMAR"
ADDRESS = "Ernestinenstraße 21, 45141 Essen, Germany"  # candidate-confirmed (profile.json / KB)
PHONE = "+49 15565 468731"
EMAIL = "ravalmeett@gmail.com"
LINKEDIN = "linkedin.com/in/meetraval"
GITHUB = "github.com/ravalmeet"
PORTFOLIO = "raval.vercel.app"

OBJECTIVE = ("AI Systems Engineer with 3+ years of backend engineering experience and a working "
             "quantitative system deployed in live markets. Currently completing an MSc in "
             "Artificial Intelligence at BTU Cottbus-Senftenberg, Germany. Specialising in "
             "production AI systems, LLM applications, and agentic pipelines.")

EXPERIENCE = [
    ("Werkstudent - Software Engineering", "Joybuy", "North Rhine-Westphalia, Germany",
     "Jan 2026 - May 2026",
     ["Collaborated with cross-functional teams to integrate backend systems, servers and databases "
      "to improve latency, data management and performance.",
      "Worked on MySQL for efficient data management and storage, supporting machine learning workflows."]),
    ("Software Engineer", "Soham Infotech", "Gujarat, India",
     "Dec 2023 - Jan 2025",
     ["Developed multiple functions and quant models achieving high profitability in financial decision-making.",
      "Designed and built backend components and real-time algorithms to support trading operations, "
      "leveraging quant and AI algorithms.",
      "Focused on black-box and gray-box models to surpass overall branch benchmarks."]),
    ("Machine Learning Intern", "Pantechelearning", "Chennai, India",
     "Dec 2021 - Feb 2022",
     ["Implemented machine learning models for various projects, including text-to-speech applications "
      "and high-functional visual-activity analysis.",
      "Worked on data extraction and preprocessing tasks, ensuring accuracy for model training and evaluation."]),
]

EDUCATION = [
    ("Master of Science - Artificial Intelligence",
     "Brandenburgische Technische Universität Cottbus-Senftenberg",
     "April 2025 - Current",
     "Machine Learning, Deep Learning, Computer Vision, NLP, Data Science, Mathematics, Big Data Analytics"),
    ("Bachelor of Engineering - Computer Engineering",
     "Gujarat Technological University", "June 2020 - May 2024",
     "Data Structures, Algorithms, Databases, Computer Networks, System Design, OOP, IoT, Cloud Computing"),
]

PROJECTS = [
    ("High Frequency Trading Platform", GITHUB.replace("github.com/", "github.com/"),
     "Developed an end-to-end system including real-time data scraping, analysis and filtering, combining "
     "quant and AI models to act in real time; achieved 70% accuracy in the cash segment.",
     "Python, Machine Learning, Deep Learning, Django, Real-time Systems, Data Analytics"),
    ("Automated Resume Generation", "job-automation-raval.streamlit.app",
     "Built a complete system that starts from structured datasets for job categories (AI, backend, data) "
     "and frames resume sections using open-source LLMs.",
     "Python, Streamlit, NLP, LLM, Prompt Engineering, API Integration"),
]

RESEARCH = ("An Empirical Study on Large Language Models for Sarcasm Detection in Low-resourced "
            "Indic Languages - conducting research on NLP models for detecting sarcasm across Indian "
            "regional dialects, focusing on linguistic diversity and complexity of interpretation.")

ACHIEVEMENTS = [
    "AI Guild Hackathon 2025 - Winner, Berlin & Brandenburg State, Germany",
    "Smart India Hackathon 2022 - Runner's Up, National Level",
    "Smart India Hackathon 2021 & Azadi ka Amrit Mahotsav 2023 - Runner's Up, State Level",
]

SKILL_GROUPS = {
    "Programming Languages": "Python, C++, JavaScript",
    "Specialized Area": "Natural Language Processing, Large Language Models, Computer Vision",
    "Dev Technologies": "Django, FastAPI, NodeJS, React, NextJS, MongoDB, Flutter",
    "Artificial Intelligence": "Machine Learning, Deep Learning, Reinforcement Learning, GenAI",
}

LANGUAGES = "English (C2), Hindi (C2), Gujarati (C2), German (A2)"

CERTS = ("Google: Big Data & Machine Learning · Machine Learning with TensorFlow · Machine Learning "
         "with Python · Data Science Introduction · Tools for Data Science · HackerRank Problem Solving "
         "(Intermediate) · Udemy: Java Programming, Web Development Masterclass")

# --------------------------------------------------------------- styles ------
ACCENT = HexColor("#1a3d5c")
GREY = HexColor("#444444")

S_NAME = ParagraphStyle("name", fontName="Helvetica-Bold", fontSize=17, leading=20,
                        textColor=ACCENT, spaceAfter=1)
S_CONTACT = ParagraphStyle("contact", fontName="Helvetica", fontSize=8.5, leading=11,
                           textColor=GREY, spaceAfter=2)
S_H = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=10, leading=12,
                     textColor=ACCENT, spaceBefore=6, spaceAfter=1)
S_BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=9, leading=11.4,
                        alignment=TA_LEFT, spaceAfter=1)
S_BULLET = ParagraphStyle("bullet", parent=S_BODY, leftIndent=9, bulletIndent=2, spaceAfter=0.5)
S_ROLE = ParagraphStyle("role", parent=S_BODY, fontName="Helvetica-Bold", spaceBefore=2)
S_META = ParagraphStyle("meta", parent=S_BODY, fontSize=8.5, textColor=GREY, spaceAfter=0.5)
S_SMALL = ParagraphStyle("small", parent=S_BODY, fontSize=8.5, leading=10.6)


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(ACCENT)
    canvas.setLineWidth(0.7)
    canvas.line(16 * mm, A4[1] - 14 * mm, A4[0] - 16 * mm, A4[1] - 14 * mm)
    canvas.restoreState()


def build_resume(path):
    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=17 * mm, bottomMargin=14 * mm,
                            title="Resume - RAVAL MEETKUMAR",
                            author=NAME)
    story = [
        Paragraph(NAME, S_NAME),
        Paragraph(f"{ADDRESS} &nbsp;·&nbsp; {PHONE} &nbsp;·&nbsp; {EMAIL}", S_CONTACT),
        Paragraph(f"{LINKEDIN} &nbsp;·&nbsp; {GITHUB} &nbsp;·&nbsp; {PORTFOLIO}", S_CONTACT),
        HRFlowable(width="100%", thickness=0.8, color=ACCENT, spaceAfter=2),

        Paragraph("CAREER OBJECTIVE", S_H),
        Paragraph(OBJECTIVE, S_BODY),

        Paragraph("EXPERIENCE", S_H),
    ]
    for role, comp, loc, yrs, bullets in EXPERIENCE:
        story.append(Paragraph(f"{role} - {comp} &nbsp;|&nbsp; {loc} &nbsp;|&nbsp; {yrs}", S_ROLE))
        for b in bullets:
            story.append(Paragraph(b, S_BULLET, bulletText="•"))

    story.append(Paragraph("EDUCATION", S_H))
    for deg, school, yrs, det in EDUCATION:
        story.append(Paragraph(f"{deg} &nbsp;|&nbsp; {school} &nbsp;|&nbsp; {yrs}", S_ROLE))
        story.append(Paragraph(det, S_META))

    story.append(Paragraph("PROJECTS", S_H))
    for title, url, desc, sk in PROJECTS:
        story.append(Paragraph(f"{title} &nbsp;|&nbsp; {url}", S_ROLE))
        story.append(Paragraph(desc, S_BULLET, bulletText="•"))
        story.append(Paragraph(f"<b>Skills:</b> {sk}", S_META))

    story.append(Paragraph("RESEARCH", S_H))
    story.append(Paragraph(RESEARCH, S_BULLET, bulletText="•"))

    story.append(Paragraph("ACHIEVEMENTS", S_H))
    for a in ACHIEVEMENTS:
        story.append(Paragraph(a, S_BULLET, bulletText="•"))

    story.append(Paragraph("SKILLS", S_H))
    skill_rows = [[Paragraph(f"<b>{k}:</b>", S_SMALL), Paragraph(v, S_SMALL)]
                  for k, v in SKILL_GROUPS.items()]
    t = Table(skill_rows, colWidths=[42 * mm, 136 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                           ("TOPPADDING", (0, 0), (-1, -1), 0),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    story.append(t)
    story.append(Paragraph(f"<b>Languages:</b> {LANGUAGES}", S_SMALL))
    story.append(Paragraph(f"<b>Certifications:</b> {CERTS}", S_SMALL))
    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)


# ------------------------------------------------------------ cover letter ---
COVER_TEMPLATE = """{date}

Quantum-Systems GmbH
Gilching, Germany

Application: {title}

Dear Hiring Team,

I am applying for the {title} position at your Gilching site. I am currently completing an
MSc in Artificial Intelligence at Brandenburgische Technische Universität Cottbus-Senftenberg,
and I bring 3+ years of hands-on engineering experience across backend systems, machine
learning, and real-time applications.

As a Software Engineer at Soham Infotech I designed backend components and real-time
algorithms for trading operations, built quantitative models, and worked to strict reliability
and performance targets. Earlier, as a Machine Learning Intern at Pantechelearning, I implemented
ML models for text-to-speech and visual-activity analysis and handled data extraction and
preprocessing for training and evaluation. Most recently, as a Werkstudent in Software
Engineering at Joybuy, I integrated backend systems, servers and databases to improve latency
and data management for ML workflows. My own projects - a high-frequency trading platform
combining quant and AI models acting in real time, and an automated resume-generation system
built on open-source LLMs - show that I can take an idea end-to-end: data pipelines, model
work, and the surrounding infrastructure.

I work in a structured, self-driven way, document results clearly, and enjoy the bridge between
research and deployment - exactly the mix your job description emphasises. I hold a residence
permit with work authorisation for Germany, I am fluent in English, and I am available from
1 October 2026.

Thank you for considering my application. I would be glad to discuss how I can contribute to
your team.

Kind regards,
RAVAL MEETKUMAR
{address}
{phone} · {email}
"""


def build_cover(path, title):
    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=16 * mm,
                            title=f"Cover Letter - {title}", author=NAME)
    body = COVER_TEMPLATE.format(title=title, date="26 September 2026",
                                 address=ADDRESS, phone=PHONE, email=EMAIL)
    text = ""
    for line in body.split("\n"):
        line = line.strip()
        if not line:
            text += "<br/><br/>"
        else:
            text += line + "<br/>"
    story = [Paragraph(text, ParagraphStyle("cl", fontName="Helvetica", fontSize=9.6,
                                            leading=13.2))]
    doc.build(story)


# ------------------------------------------------------- portfolio highlights -
def build_portfolio(path):
    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=16 * mm, bottomMargin=14 * mm,
                            title="Project Highlights - RAVAL MEETKUMAR", author=NAME)
    story = [
        Paragraph("RAVAL MEETKUMAR - PROJECT HIGHLIGHTS", S_NAME),
        Paragraph(f"{EMAIL} · {PHONE} · {GITHUB} · {PORTFOLIO}", S_CONTACT),
        HRFlowable(width="100%", thickness=0.8, color=ACCENT, spaceAfter=3),
        Paragraph("Showcase of engineering work (all repositories and live apps are real and linked).",
                  S_BODY),
    ]
    items = [
        ("High Frequency Trading Platform", GITHUB,
         "End-to-end real-time system: data scraping, analysis and filtering, with quant + AI models acting "
         "in live markets; 70% accuracy achieved in the cash segment. Python, ML/DL, Django, real-time systems."),
        ("Automated Resume Generation", "job-automation-raval.streamlit.app",
         "Complete pipeline from structured job-category datasets to resume sections framed with open-source "
         "LLMs. Python, Streamlit, NLP, LLMs, prompt engineering."),
        ("Vehicle Sharing Application", "github.com/ravalmeet/Vehicle-Sharing-Application",
         "Full-stack app with route selection via Dijkstra's algorithm, real-time CRUD and a clean UI. "
         "NodeJS, React, MongoDB, JavaScript."),
        ("TradingView-Data Fetch", "github.com/ravalmeet/TradingView",
         "Open-source market-data fetcher with 40+ stars and 24+ forks on GitHub. Python, API integration."),
        ("Research: LLM Sarcasm Detection for Low-resourced Indic Languages", "",
         "Empirical study of NLP models for sarcasm detection across Indian regional dialects - linguistic "
         "diversity, low-resource settings, evaluation methodology."),
        ("AI Guild Hackathon 2025", "",
         "Winner - Berlin and Brandenburg State, Germany. Earlier: Smart India Hackathon runner-up (state & "
         "national levels)."),
    ]
    for title, url, desc in items:
        head = f"{title}" + (f" &nbsp;|&nbsp; {url}" if url else "")
        story.append(Paragraph(head, S_ROLE))
        story.append(Paragraph(desc, S_BULLET, bulletText="•"))
    doc.build(story)


if __name__ == "__main__":
    title = sys.argv[1] if len(sys.argv) > 1 else "Working Student - Software Engineering (m/f/d)"
    build_resume("resume.pdf")
    build_cover("cover_letter.pdf", title)
    build_portfolio("portfolio_highlights.pdf")
    for f in ("resume.pdf", "cover_letter.pdf", "portfolio_highlights.pdf"):
        print(f, os.path.getsize(f), "bytes")

# Career Objective Prompt (Stage 1 of resume sections)

One specific prompt used to generate a 100% ATS-friendly career objective for ONE job.

**How it is used:** `resume_content/1_career_objective.py` loads this file, replaces the
`{{PLACEHOLDERS}}` below with the real job details for each job row, and sends the whole
prompt text to the model via `ollama_request_response.send_prompt(prompt, token)`.
The script also skips rows with an empty `job_description` and escapes LaTeX special
characters in the model output before anything reaches the .tex template.

**Placeholders replaced by the script before sending:**

| Placeholder        | Filled from CSV column | What it contains |
|--------------------|------------------------|------------------|
| `{{JOB_TITLE}}`    | `title`                | The job role, e.g. "Working Student – AI Engineering" |
| `{{JOB_DESCRIPTION}}` | `job_description`   | The full posting description text |
| `{{KEY_REQUIREMENTS}}` | `requirements` + `your_tasks` (merged, truncated by the script) | The major must-have skills and tasks |

Only these three job fields are shared — job role, job description, and major requirements —
nothing else from the posting is needed to write the objective.

---

## PROMPT (everything below this line is sent to the model)

You are an expert resume writer who specialises in ATS (Applicant Tracking System) optimisation.
Your task: write ONE career objective for the candidate below, tailored to the ONE job posting below.

### CANDIDATE PROFILE (fixed, truthful facts — the only facts you may use)

- Currently completing an MSc in Artificial Intelligence at Brandenburgische Technische
  Universität Cottbus-Senftenberg (BTU), Germany (April 2025 – present).
- Bachelor of Engineering in Computer Engineering, Gujarat Technological University (2020 – 2024).
- Professional experience as a Software Engineer in India (Dec 2023 – Jan 2025): backend
  engineering, integrating backend systems, servers and databases to improve latency, data
  management and performance; earlier experience with MySQL, Django and Flask backend work.
  Real total: about 1 year of professional experience — never state a higher number. You may
  phrase this qualitatively (e.g. "professional software engineering experience") when a bare
  number reads unnatural.
- Ongoing academic research: an empirical study on large language models for sarcasm detection
  in low-resourced Indic languages (NLP / LLM specialisation).
- Hackathon achievements: multiple Smart India Hackathon runner-up finishes, AI Guild Hackathon
  2025 Winner (Berlin and Brandenburg, Germany).
- Personal working-student job search context: based in Germany, seeking working-student /
  internship roles alongside the MSc.

### JOB DETAILS

- Job role: {{JOB_TITLE}}
- Job description: {{JOB_DESCRIPTION}}
- Key requirements and tasks: {{KEY_REQUIREMENTS}}

### OUTPUT RULES (all must be followed exactly)

1. Output ONLY the finished career objective text — a single paragraph. No titles, no labels,
   no preamble, no explanation, no quotation marks around it, no markdown, no bullet points,
   no asterisks, no LaTeX, no line breaks inside the paragraph.
2. Length: 2 to 4 sentences, maximum 60 words.
3. Recommended flow (natural, not a rigid template): open with the candidate's professional
   identity for this role's domain plus their strongest proof point; then one sentence on the
   current MSc in Artificial Intelligence at BTU Cottbus-Senftenberg, Germany; then one
   sentence connecting the candidate's specialisations to this posting's focus; close with the
   kind of role, team or mission sought. Use 2 to 4 sentences in total and let the posting's
   emphasis shape the rhythm — never produce the same sentence pattern for every job.
4. Keyword targeting (do this BEFORE writing): silently extract the 8-15 most important ATS
   keywords from the posting — the exact job title, hard skills, tools/technologies, domain
   terms, and language requirements. When the description is long, prioritise the requirements
   and tasks sections. Then place the 4-8 most important ones where they read naturally, so
   both human recruiters and ATS parsers match the objective. Never build a sentence that is
   just a skill list, and never put more than three skills in a row.
5. Exact phrase mirroring: use the posting's verbatim wording for the role and skills — never
   paraphrase a keyword (if the posting says "machine learning", write "machine learning"; if
   it says "LLM applications", write "LLM applications"). When the posting uses a spelled-out
   form, write it with the abbreviation in parentheses on first mention, e.g. "Artificial
   Intelligence (AI)"; when the posting itself uses the abbreviation, use the abbreviation.
6. Title usage: use the posting's core role title verbatim exactly ONCE — in the opening
   identity phrase or the closing goal — so ATS parsers match it. NEVER make it the literal
   first words of the objective, and never repeat it a second time. Strip administrative
   suffixes such as (m/f/d), (m/w/d), (m/f/d/x) from it. If the title is German, keep it
   verbatim where used.
7. Anti-stuffing: keywords must sit inside natural, flowing sentences. Never output a keyword
   list, never repeat the same keyword more than twice, and never use empty filler words
   (passionate, hardworking, dynamic, results-driven) that carry no keyword value.
8. Truthfulness: use ONLY facts from the candidate profile and the posting. Never invent years
   of experience, employers, degrees, tools, or skills that are not listed above. Never claim
   employment at the hiring company.
9. Do not mention the hiring company's name in the objective.
10. Style and characters: professional, direct, implied first person (no "I", no "my"). Active
    voice. Always write in English. Plain text with standard punctuation only (periods, commas,
    hyphens, dashes). Never use backslash, braces, ^, ~, $, %, or _, and no markdown, no
    emojis. Use &, #, and + only inside a verbatim posting keyword or job title (e.g. "R&D",
    "C#", "C++"), never in your own prose — the script escapes LaTeX special characters before
    the objective is inserted into the resume template. Write the body in English; a verbatim
    German job title (rule 6) is the only allowed non-English words.
11. Authenticity: the objective must read like a real person wrote it for this exact posting —
    concrete, specific, with varied sentence openings and no template feel. Never open with a
    bare "Working Student" or "Werkstudent" label; lead with the professional identity. Omit
    any profile fact that does not fit this posting naturally, and never tack skills onto a
    sentence just because the posting mentions them.

Example of the target style (structure only, never copy its content):
   "AI Systems Engineer with 3+ years of backend engineering experience and a working
   quantitative system deployed in live markets. Currently completing an MSc in Artificial
   Intelligence at BTU Cottbus-Senftenberg, Germany. Specialising in production AI systems,
   LLM applications, and agentic pipelines — seeking AI engineering or quantitative systems roles."

Return the career objective paragraph and nothing else.

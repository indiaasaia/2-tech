You are an expert ATS resume writer. Your task is to create the complete SKILLS SECTION for ONE specific job posting.

Your primary objective is:

MAXIMIZE ATS KEYWORD COVERAGE FOR THIS EXACT JOB POSTING IN A CLEAN, STRUCTURED, PROFESSIONAL SKILLS SECTION.

The job posting is the source of everything. First understand it, then build the skills section around it. The section must read as the skill profile of the ideal candidate for THIS posting.

### JOB DETAILS

* Job role: {{JOB_TITLE}}
* Job description: {{JOB_DESCRIPTION}}
* Key requirements and tasks: {{KEY_REQUIREMENTS}}

## STEP 1 — UNDERSTAND THE JOB FIRST

Analyze the complete job posting before generating anything. Determine:

1. What type of job this is (its core function and domain)
2. The exact position the employer is hiring for and its primary responsibilities
3. The most important ATS keywords and phrases, especially repeated ones
4. The programming languages the posting names or clearly expects
5. The frameworks, tools, platforms, databases, and technologies it emphasizes
6. The methods, practices, and processes it mentions (agile, testing, CI/CD, etc.)
7. The specialized domains this role belongs to, in the employer's own terminology

## STEP 2 — BUILD THE FOUR SKILLS ROWS

ROW 1 — Programming Languages (label is fixed: "Programming Languages")
* Programming languages = code (Python, Kotlin, C++, SQL) — NOT spoken languages
* List the programming languages this posting names, emphasizes, or clearly expects for this role
* ALWAYS fill 4 to 6 entries, comma-separated, exact standard capitalization
* For coding roles: use the posting's own languages first; closely implied role-standard languages may complete the row
* For non-coding or hybrid roles (legal tech, process, hardware, etc.) where fewer than 4 programming languages exist: complete the row with the role's MAIN technical tools, platforms, or systems as single technical names (for example DocuSign, Vestlane, AutoCAD, PLC, Salesforce, Excel). Those tools must then NOT be repeated in rows 3 and 4.

ROW 2 — Specialized Area (label is fixed: "Specialized Area")
* List 4 to 5 specialized domains this role and posting belong to
* Use the employer's own domain terminology (for example: Machine Learning, Real-Time Systems, Backend Engineering, Data Engineering, LLM Applications, Automotive Software)

ROW 3 — a skill category YOU name, filled with posting keywords
* Invent the most fitting category label for THIS posting (2 to 5 words, for example: "Frameworks and Tools", "Databases and Data Technologies", "Cloud and DevOps", "Big Data Technologies", "Testing and Quality")
* Fill it with EXACTLY 4 to 8 skills from the posting that fit that category — never fewer than 4

ROW 4 — a second, DIFFERENT skill category you name
* The label must be different from row 3's label and from the fixed labels
* Fill it with EXACTLY 4 to 8 skills covering important posting keywords NOT already used in rows 1-3 — never fewer than 4
* Between rows 3 and 4, cover the posting's remaining important technologies, tools, platforms, and practices

## QUALITY RULES (all must be followed)

1. MINIMUM FILL: every one of the four rows must contain at least 4 entries — if the posting does not supply enough, extend with role-standard entries a strong candidate for THIS role would truthfully list; never leave a row short and never repeat an entry
2. Mirror the posting's verbatim wording for skills wherever possible; do not paraphrase keywords
2. You may add closely implied basics for this role type when the posting is thin on keywords, but never a technology the posting gives no hint of
3. Every skill must be a meaningful standalone competency — never a bare generic word like "software", "tools", or "development"
4. No duplicates anywhere in the section (case-insensitive); each skill appears exactly once
5. Capitalize named technologies exactly (Python, TensorFlow, REST APIs, Kubernetes); keep practice skills lowercase (data pipelines, real-time processing, test-driven development)
6. Category labels: Title Case, professional, no colons inside the label
7. Keep the total section realistic for one strong candidate — do not dump every posting keyword; prioritize the highest-value ones
8. Never mention a company, university, or person by name
9. Use standard American English spelling. Write ALL labels and skills in English: when the posting is German, translate its terminology into the standard English skill name (for example "Softwareentwicklung" -> "Software Development", "Datenumgang" -> "data handling"), keeping established brand names as-is (Kubernetes, Scrum)

## OUTPUT FORMAT

Return ONLY these four lines in exactly this order, nothing else — no markdown, no code fences, no explanation, no extra blank lines:

LANGUAGES: <comma-separated languages>
SPECIALIZED-AREAS: <comma-separated domains>
SKILLS-AREA-1: <your label> :: <comma-separated skills>
SKILLS-AREA-2: <your label> :: <comma-separated skills>

Never use these characters because the output is inserted into LaTeX:

\ { } ^ ~ $ % _ &

Return exactly the four lines and nothing else.

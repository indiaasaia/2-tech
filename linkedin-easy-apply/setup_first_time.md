# LinkedIn Easy Apply Bot — Complete Portable Setup & Deployment Guide

This guide provides everything needed to transfer and run the **LinkedIn Easy Apply Autonomous Bot** on any Windows laptop or PC for **24/7 continuous operation**.

Designed for **100% self-contained portability**:
- Single-folder deployment (`linkedin-easy-apply/`)
- 1-Click Interactive Setup Wizard (`setup.bat`)
- 1-Click Continuous Automation Runner & Live Web Dashboard (`start.bat`)

---

## 1. System Architecture & Autonomous AI Sprint Pipeline

The automation runs continuously without long pauses, sprinting job-by-job with a **10-second gap**:

```
┌────────────────────────────────────────────────────────────────────────┐
│                   AUTONOMOUS AI SPRINT PIPELINE                        │
│                                                                        │
│  [Step 1] Fetch Job Listing & Complete Description                     │
│           (Clicks "Show more" to extract full duties and requirements) │
│                                  │                                     │
│                                  ▼                                     │
│  [Step 2] Strict Screening Gates (English Only + Werkstudent/Intern)   │
│           (Drops any German-required ad; drops full-time/senior roles) │
│                                  │                                     │
│                                  ▼                                     │
│  [Step 3] Ollama Cloud Fit Rating (gpt-oss:120b)                       │
│           (Evaluates JD against Meetkumar's profile on 1-10 scale;     │
│            Accepts if Score > 7; skips if Score <= 7)                  │
│                                  │                                     │
│                                  ▼                                     │
│  [Step 4] Compile 100% ATS Tailored LaTeX Resume & English Letter      │
│           (Invokes local engine & bundled Tectonic compiler;           │
│            Safe fallback to master resume if compilation times out)    │
│                                  │                                     │
│                                  ▼                                     │
│  [Step 5] Submit Easy Apply Modal with Dynamic AI Q&A                  │
│           (Uploads tailored PDF; Ollama answers any custom questions)  │
│                                  │                                     │
│                                  ▼                                     │
│  [Step 6] 10-Second Sprint Pacing & Repeat                             │
│           (Immediate 10s pacing to next listing; caps at 50/day)       │
└────────────────────────────────────────────────────────────────────────┘
```

### Safety & AI Intelligence Features:
1. **Strictly English-Speaking Jobs:** Filters out any role requiring German (mandatory/fluent). Keeps English working-language postings.
2. **Werkstudent & Internship Roles Exclusively:** Only Werkstudent, Working Student, Internship, Praktikum, and Student Assistant roles are accepted. Drops all full-time regular, senior, lead, and apprenticeship roles.
3. **100% ATS Keyword Tailoring:** 100% of job ad keywords mapped into categorized LaTeX skill rows. Experience bullets grounded strictly in `candidate_kb.json` (no hallucination).
4. **Self-Contained Tectonic Engine:** Bundled portable compiler builds 2-page LaTeX PDF CV (`Meetkumar_Raval_CV_<Company>_<Role>.pdf`) and tailored English cover letter.
5. **Ollama Cloud Dynamic Q&A (`gpt-oss:120b`):** Answers custom/unexpected application questions, choosing the optimal ATS-qualifying option.
6. **10-Second Sprint Pacing:** Eliminates long pauses, maintaining fast progress while respecting LinkedIn safety norms.
7. **Daily Safety Cap:** Maximum 50 applications per day.
8. **Live Command Center:** Local dashboard at `http://localhost:5050` displaying real-time metrics, AI fit scores, and tailored resume status.

---

## 2. Moving to a New Laptop / PC

### What to Copy:
Copy the entire `linkedin-easy-apply` folder onto a USB flash drive or zip it and transfer to your second laptop.

```
linkedin-easy-apply/
  ├── chrome_profile/                    <-- [CRITICAL] Keeps your active LinkedIn login session
  ├── RAVAL_MEETKUMAR_RITESHKUMAR.pdf    <-- [CRITICAL] Your resume PDF
  ├── config.json                        <-- Your settings, keywords, contact info
  ├── requirements.txt                   <-- Python dependencies
  ├── setup.bat                          <-- 1-Click Setup Wizard
  ├── setup_wizard.py                    <-- Interactive verification engine
  ├── start.bat                          <-- 1-Click 24/7 Continuous Runner
  ├── main.py                            <-- Continuous loop & dashboard runner
  ├── apply_bot.py                       <-- Easy Apply browser engine
  └── dashboard.py                       <-- Web dashboard & metrics server
```

> [!TIP]
> **To make the transfer faster:** You can delete the `.venv/` folder before copying. `setup.bat` will automatically recreate the virtual environment on the new laptop in under 60 seconds.
> **DO NOT delete `chrome_profile/`** — it preserves your authenticated LinkedIn login cookies!

---

## 3. Prerequisites on the New Laptop

Before running the setup wizard, ensure the laptop has:

### A. Google Chrome
- Install standard Google Chrome from: [google.com/chrome](https://www.google.com/chrome/)

### B. Python (3.10 – 3.13)
- Download from: [python.org/downloads](https://www.python.org/downloads/)
- > [!IMPORTANT]
  > On the very first installer screen, **CHECK the box: `"Add python.exe to PATH"`**.

---

## 4. First-Time Setup (Only 2 Minutes)

Once the folder is on the new laptop:

1. Open the `linkedin-easy-apply` folder.
2. Double-click:
   ```cmd
   setup.bat
   ```
3. The automated setup wizard runs through 6 interactive verification steps:
   - **Step 1: System Check** — Verifies Python version and Google Chrome installation.
   - **Step 2: Resume Validation** — Confirms your PDF resume exists and links it.
   - **Step 3: Configuration Review** — Displays your name, city (Cottbus), phone number, expected salary, and search keywords for confirmation.
   - **Step 4: Live Browser & LinkedIn Session Check** — Opens Chrome, checks your LinkedIn feed login status, and verifies your resume in LinkedIn's Application Settings.
   - **Step 5: Diagnostic Search Dry-Run** — Tests job card selection and Easy Apply modal detection live.
   - **Step 6: Dashboard Initialization** — Generates local dashboard assets and concludes setup.

---

## 5. Starting the 24/7 Continuous Automation Loop

Whenever you are ready to start:

1. Double-click:
   ```cmd
   start.bat
   ```
2. What happens immediately:
   - The Web Dashboard is launched and opens in your browser at:
     **`http://localhost:5050`**
   - The terminal begins **Cycle #1**:
     - Searches for matching jobs in Germany (`AI Engineer`, `Python Developer`, `Full Stack Developer`, etc.).
     - Submits up to 3 Easy Apply applications with human-like typing and form filling.
     - Displays the live 5-minute cool-down countdown timer.
     - Repeats continuously 24 hours a day until you close the window or press `Ctrl+C`.

---

## 6. Keeping the Laptop Running 24/7 (Windows Settings)

To prevent Windows from putting the laptop to sleep when unattended:

1. **Keep Laptop Awake on AC Power**:
   - Open Windows **Settings** > **System** > **Power & battery**.
   - Under **Screen and sleep**:
     - Set *"When plugged in, put my device to sleep after"* to **Never**.
2. **Lid Close Action** (if closing the laptop lid):
   - Press `Win + R`, type `control` and press Enter.
   - Go to **Hardware and Sound** > **Power Options** > **Choose what closing the lid does**.
   - Under *"When plugged in"*, set *"When I close the lid"* to **Do nothing**.
   - Click **Save changes**.

---

## 7. Configuration Details (`config.json`)

If you ever want to adjust search keywords, locations, or salary expectations, edit `config.json`:

```json
{
  "personal_info": {
    "first_name": "Meetkumar",
    "last_name": "Raval",
    "city": "Cottbus",
    "country": "Germany",
    "postal_code": "03046",
    "phone_number": "015567018163"
  },
  "search_settings": {
    "keywords": [
      "AI werkstudent English"
    ],
    "locations": ["Germany"],
    "workplace_types": ["Remote", "Hybrid", "On-site"],
    "date_posted": "Past 24 hours"
  },
  "scheduler_settings": {
    "applications_per_run": 3,
    "loop_gap_minutes": 5,
    "daily_target": 50,
    "dashboard_port": 5050
  },
  "ollama_settings": {
    "enabled": true,
    "api_key": "YOUR_OLLAMA_API_KEY",
    "model": "gpt-oss:120b",
    "base_url": "https://ollama.com"
  }
}
```

---

## 8. Summary of Files

| File | Purpose |
|---|---|
| [`setup.bat`](file:///setup.bat) | First-time automated setup wizard (creates venv, installs requirements, tests Chrome & LinkedIn) |
| [`start.bat`](file:///start.bat) | Starts the 24/7 continuous application loop and launches the web dashboard |
| [`main.py`](file:///main.py) | Python continuous loop orchestrator & background Flask server |
| [`apply_bot.py`](file:///apply_bot.py) | Undetected Chrome Easy Apply automation engine |
| [`dashboard.py`](file:///dashboard.py) | Local web command center backend (`http://localhost:5050`) |
| [`regular_app_bridge.py`](file:///regular_app_bridge.py) | Bridge connecting REGULAR_APPLICATION & Tectonic compiler for tailored LaTeX CV/Cover letters |
| [`engine/`](file:///engine) | Self-contained resume & cover letter generation engine (analyst, keyword plan, LaTeX renderers) |
| [`tools/tectonic.exe`](file:///tools/tectonic.exe) | Bundled standalone LaTeX compiler (generates 2-page PDF resumes & cover letters) |
| [`config.json`](file:///config.json) | Candidate profile, search parameters, and rate-limiting limits |
| [`history.json`](file:///history.json) | Local database of applied jobs, timestamps, and application statuses |

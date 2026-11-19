"""Policy v3 keyword placement: truthful entry vocabulary, injector, grounding, gates.

Inline fixtures over the real approved KB; no previous-run files, no LLM calls.
"""
from __future__ import annotations

from resume_content_improve_research.generation import kb_loader
from resume_content_improve_research.generation.claimable_set import ClaimableSet, build_claimable_set
from resume_content_improve_research.generation.evidence_vocab import (
    entry_keywords,
    find_entry,
    vocabulary_violations,
)
from resume_content_improve_research.generation.factual_content import ground_components
from resume_content_improve_research.generation.keyword_injector import is_printed, skill_rows, strip_gap_phrases
from resume_content_improve_research.generation.keywords import build_keyword_plan
from resume_content_improve_research.verification.gates import check_g2_claims

KB = kb_loader.load_kb()
SOHAM = find_entry(KB, "soham")

JOB = {"title": "Working Student AI Engineering (m/f/d)", "company": "Muster GmbH",
       "job_description": "Build REST APIs in Python, deploy on Kubernetes and AWS.",
       "requirements": "Generative AI, prompt engineering, Docker, OWASP Top 10, Computer Science studies."}
ANALYSIS = {"language": "en", "required": ["python", "REST APIs", "studying Computer Science"],
            "preferred": ["Docker"], "tools": ["Kubernetes", "AWS"], "languages_required": []}
PLAN = build_keyword_plan(JOB, ANALYSIS).to_dict()


# ---------------------------------------------------------------------------
# Truthful entry vocabulary
# ---------------------------------------------------------------------------
class TestEvidenceVocabulary:
    def test_every_entry_passes_its_own_evidence(self):
        for entry in kb_loader.experiences(KB) + kb_loader.main_projects(KB):
            assert vocabulary_violations(" ".join(entry["evidence"]), entry, KB) == [], entry["id"]

    def test_invented_tools_at_a_real_employer_are_caught(self):
        text = "Deployed Kubernetes clusters on AWS and built Kafka streams with Python REST APIs."
        assert vocabulary_violations(text, SOHAM, KB) == ["Kubernetes", "AWS", "Kafka"]

    def test_forbidden_skill_beats_synonyms(self):
        assert "Django" in vocabulary_violations("Built Django services.", SOHAM, KB)

    def test_truthful_job_keywords_for_an_entry(self):
        terms = entry_keywords(SOHAM, KB, PLAN)
        assert "Python" in terms and "REST APIs" in terms
        assert "Kubernetes" not in terms and "Docker" not in terms
        resume_gen = entry_keywords(find_entry(KB, "resume_gen"), KB, PLAN)
        assert "Generative AI" in resume_gen and "prompt engineering" in [t.lower() for t in resume_gen]

    def test_free_phrase_job_keywords_are_checked_with_a_plan(self):
        """Regression (live 2026-10-17): "Implemented AI assistants by developing ML models"
        at Pantech; "AI assistants" is a job keyword, not a lexicon term."""
        job = dict(JOB, requirements=JOB["requirements"] + " Experience with AI assistants.")
        plan = build_keyword_plan(job, dict(ANALYSIS, required=ANALYSIS["required"] + ["AI assistants"])).to_dict()
        pantech = find_entry(KB, "pantechelearning")
        text = "Implemented AI assistants by developing machine learning models."
        assert "AI assistants" in vocabulary_violations(text, pantech, KB, plan)
        assert "AI assistants" not in vocabulary_violations(text, pantech, KB)    # lexicon-only blind spot
        assert "AI assistants" not in entry_keywords(pantech, KB, plan)          # never offered as truthful

    def test_soft_skills_and_education_never_count_as_entry_claims(self):
        assert vocabulary_violations("Collaborated with stakeholders and communicated results.",
                                     SOHAM, KB) == []


# ---------------------------------------------------------------------------
# Injector
# ---------------------------------------------------------------------------
class TestInjector:
    def test_gap_phrases_are_stripped(self):
        text, removed = strip_gap_phrases(
            "MSc AI student with Python. Working toward hands-on Docker experience. Eager to deepen pandas skills.")
        assert text == "MSc AI student with Python." and removed == 2

    def test_all_plan_keywords_in_rows_education_field_excluded(self):
        rows = skill_rows(PLAN, KB, {"languages": ["Python"], "specialized_areas": [], "areas": []})
        flat = rows["languages"] + rows["specialized_areas"] + [s for a in rows["areas"] for s in a["skills"]]
        for keyword in PLAN["keywords"]:
            if keyword["category"] == "education_field":
                assert not is_printed(keyword["term"], flat)
            else:
                assert is_printed(keyword["term"], flat), keyword["term"]
        assert all(rows[key] for key in ("languages", "specialized_areas"))   # never empty

    def test_draft_extras_must_be_kb_skills(self):
        draft = {"languages": ["Python"], "specialized_areas": ["Kafka", "Backend Components"],
                 "areas": [{"label": "x", "skills": ["Machine Learning"]}, {"label": "y", "skills": []}]}
        rows = skill_rows(PLAN, KB, draft)
        flat = rows["languages"] + rows["specialized_areas"] + [s for a in rows["areas"] for s in a["skills"]]
        assert "Kafka" not in flat and "Backend Components" not in flat
        assert is_printed("Machine Learning", flat)


# ---------------------------------------------------------------------------
# Grounding
# ---------------------------------------------------------------------------
def _components(soham_bullets: list[str]) -> dict:
    return {
        "objective": "Software engineer with Python and REST APIs. Working toward hands-on Docker experience.",
        "skills_section": {"languages": ["Python"], "specialized_areas": ["Machine Learning"],
                           "areas": [{"label": "A", "skills": ["Git"]}, {"label": "B", "skills": ["SQL"]}]},
        "experiences": [
            {"id": "soham", "bullets": soham_bullets, "skills": ["Python"]},
            {"id": "pantechelearning", "bullets": [], "description": "", "skills": []},
        ],
        "projects": [{"id": "hft", "bullets": [], "skills": []},
                     {"id": "resume_gen", "bullets": [], "skills": []}],
    }


class TestGrounding:
    def test_clean_generated_bullets_survive(self):
        bullets = ["Built modular REST APIs and quant models in Python for trading decisions."]
        grounded = ground_components(_components(bullets), ANALYSIS, KB, plan=PLAN)
        soham = grounded["experiences"][0]
        assert soham["bullets"] == bullets
        assert grounded["grounding_findings"] == []

    def test_fabricated_bullet_falls_back_to_evidence(self):
        grounded = ground_components(_components(["Deployed Kubernetes clusters on AWS."]), ANALYSIS, KB, plan=PLAN)
        soham = grounded["experiences"][0]
        assert soham["bullets"][0].startswith("Developed multiple functions")
        assert all(b.endswith(".") for b in soham["bullets"])           # no glued sentences
        assert any("Kubernetes" in f for f in grounded["grounding_findings"])

    def test_only_the_offending_bullet_is_dropped(self):
        clean = "Built modular REST APIs and quant models in Python for trading decisions."
        grounded = ground_components(_components([clean, "Deployed Kubernetes clusters on AWS."]),
                                     ANALYSIS, KB, plan=PLAN)
        assert grounded["experiences"][0]["bullets"] == [clean]
        assert any("Kubernetes" in f for f in grounded["grounding_findings"])

    def test_percentage_evidence_is_never_printed(self):
        grounded = ground_components(_components([]), ANALYSIS, KB, plan=PLAN)
        hft = next(p for p in grounded["projects"] if p["id"] == "hft")
        assert hft["bullets"] and not any("percent" in b for b in hft["bullets"])

    def test_gap_phrase_removed_from_objective(self):
        grounded = ground_components(_components([]), ANALYSIS, KB, plan=PLAN)
        assert "working toward" not in grounded["objective"].lower()

    def test_objective_style_becomes_profile_with_job_keywords(self):
        comp = _components([])
        comp["objective"] = "MSc AI student seeking a Working Student role to apply Python expertise."
        grounded = ground_components(comp, ANALYSIS, KB, plan=PLAN)
        assert "seeking" not in grounded["objective"].lower()
        assert "Python" in grounded["objective"] and "REST APIs" in grounded["objective"]

    def test_skills_section_carries_every_keyword(self):
        grounded = ground_components(_components([]), ANALYSIS, KB, plan=PLAN)
        section = grounded["skills_section"]
        flat = section["languages"] + section["specialized_areas"] + [s for a in section["areas"] for s in a["skills"]]
        for term in ("Kubernetes", "AWS", "Docker", "Generative AI", "OWASP Top 10", "REST APIs"):
            assert is_printed(term, flat), term

    def test_untrue_keyword_never_in_entry_rows(self):
        grounded = ground_components(_components([]), ANALYSIS, KB, plan=PLAN)
        for entry in grounded["experiences"] + grounded["projects"]:
            assert "Kubernetes" not in entry["skills"] and "AWS" not in entry["skills"]


# ---------------------------------------------------------------------------
# G2 with keywords
# ---------------------------------------------------------------------------
class TestG2Keywords:
    def test_keyword_tokens_are_mentionable(self):
        cset = build_claimable_set(ANALYSIS, KB, keywords=PLAN["targets"])
        assert check_g2_claims("Skills: Docker, Kubernetes, AWS, Python", cset, set()) == []

    def test_unrequested_technology_is_still_a_violation(self):
        cset = build_claimable_set(ANALYSIS, KB, keywords=PLAN["targets"])
        assert any("kafka" in f.lower() for f in check_g2_claims("Skills: Kafka", cset, set()))

    def test_digits_inside_a_keyword_are_not_metrics(self):
        cset = ClaimableSet(kb_skills=["Python"], keywords=["OWASP Top 10"])
        assert check_g2_claims("Security: OWASP Top 10", cset, set()) == []
        assert check_g2_claims("Improved latency by 10 ms", cset, set()) != []


def test_generator_retries_an_empty_first_reply(monkeypatch):
    """Regression (live run 2026-10-17): call 1 had no retry; one empty reply parked the job."""
    from resume_content_improve_research.generation import generator

    replies = iter([
        "",                                                                   # call 1: empty
        '{"career_objective": "Profile.", "skills_section": {"languages": ["Python"], '
        '"specialized_areas": [], "areas": [{"label": "A", "skills": []}, {"label": "B", "skills": []}]}}',
        '{"experiences": [{"id": "soham", "bullets": ["Built REST APIs."], "skills": []}, '
        '{"id": "pantechelearning", "bullets": ["Implemented models."], "skills": []}]}',
        '{"projects": [{"id": "hft", "bullets": ["Built a system."], "skills": []}, '
        '{"id": "resume_gen", "bullets": ["Built a generator."], "skills": []}]}',
    ])
    budgets: list[int] = []

    def fake(prompt, token, temperature=0.1, max_tokens=2000, attempts=3):
        budgets.append(max_tokens)
        return next(replies)

    monkeypatch.setattr(generator, "call_llm", fake)
    cset = build_claimable_set(ANALYSIS, KB, keywords=PLAN["targets"])
    components, meta = generator.generate_components(cset, KB, "Working Student AI", "tok", plan=PLAN)
    assert meta["calls"] == 4 and meta["repair_retries"] == 1
    assert components.objective == "Profile." and components.experiences[0]["bullets"] == ["Built REST APIs."]
    assert min(budgets) >= 4000


def test_letter_claimable_set_includes_job_keywords():
    from resume_content_improve_research.generation.cover_letter import build_letter_claimable_set

    cset = build_letter_claimable_set(ANALYSIS, KB, JOB)
    assert "kubernetes" in cset.mentionable() and "docker" in cset.mentionable()


def test_regeneration_feeds_findings_back(monkeypatch):
    from resume_content_improve_research.generation import generator

    replies = iter([
        '{"career_objective": "Profile.", "skills_section": {"languages": ["Python"], '
        '"specialized_areas": [], "areas": [{"label": "A", "skills": []}, {"label": "B", "skills": []}]}}',
        '{"experiences": [{"id": "soham", "bullets": ["Built REST APIs."], "skills": []}, '
        '{"id": "pantechelearning", "bullets": ["Implemented models."], "skills": []}]}',
        '{"projects": [{"id": "hft", "bullets": ["Built a system."], "skills": []}, '
        '{"id": "resume_gen", "bullets": ["Built a generator."], "skills": []}]}',
    ])
    prompts: list[str] = []

    def fake(prompt, token, temperature=0.1, max_tokens=2000, attempts=3):
        prompts.append(prompt)
        return next(replies)

    monkeypatch.setattr(generator, "call_llm", fake)
    cset = build_claimable_set(ANALYSIS, KB, keywords=PLAN["targets"])
    finding = "vocabulary: 'AI assistants' is not evidenced for pantechelearning"
    generator.generate_components(cset, KB, "Working Student AI", "tok", plan=PLAN, findings=[finding])
    assert all("PREVIOUS ATTEMPT FAILED" in p and finding in p for p in prompts)


def test_step4_vocabulary_findings():
    from types import SimpleNamespace

    from resume_content_improve_research.run_step4 import vocabulary_findings

    comp = SimpleNamespace(experiences=[{"id": "soham", "bullets": ["Deployed Kubernetes clusters on AWS."]}],
                           projects=[{"id": "hft", "bullets": []}])
    found = vocabulary_findings(comp, KB, PLAN)
    assert any("Kubernetes" in f and "soham" in f for f in found)

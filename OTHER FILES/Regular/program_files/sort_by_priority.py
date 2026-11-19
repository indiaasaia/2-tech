import re
import pandas as pd
from pathlib import Path

csv_path = Path("program_files/output/2_filted_jobs.csv")
df = pd.read_csv(csv_path)

def tech_score(row):
    t = (str(row.get("title", "")) + " " + str(row.get("job_description", ""))).lower()
    score = 0
    for w in ["ai", "artificial intelligence", "machine learning", "llm", "nlp", "data science", "agent", "software", "developer", "python", "cloud", "security"]:
        if re.search(r"\b" + re.escape(w) + r"\b", t):
            score += 2
    for w in ["thesis", "master thesis", "full-stack", "backend", "automation", "deep learning", "algorithm"]:
        if re.search(r"\b" + re.escape(w) + r"\b", t):
            score += 3
    for c in ["bosch", "sap", "quantum-systems", "sixt", "linde", "okapi", "ilert", "fraunhofer", "scalable capital", "qonto", "deutsche bank"]:
        if c in str(row.get("company", "")).lower():
            score += 5
    return score

df["priority"] = df.apply(tech_score, axis=1)
df = df.sort_values(by="priority", ascending=False).reset_index(drop=True)
df_clean = df.drop(columns=["priority"])
df_clean.to_csv(csv_path, index=False, encoding="utf-8")

print(f"Reordered {len(df_clean)} jobs by technical relevance:")
for idx, r in df_clean.head(15).iterrows():
    print(f"  {idx+1:2d}. [{r['source']}] {r['company']}: {r['title']}")

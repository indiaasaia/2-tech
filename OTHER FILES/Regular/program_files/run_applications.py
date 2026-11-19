import sys
import json
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
from autonomous_job_applier import AutonomousJobApplier

def main():
    bundles_path = Path("program_files/output_v2/application_bundles.json")
    with open(bundles_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    bundles = data.get("bundles", [])

    # Allow limiting count via CLI argument, e.g. python run_applications.py 1
    limit = len(bundles)
    if len(sys.argv) > 1:
        limit = int(sys.argv[1])

    print(f"Starting Autonomous Application Execution for top {limit} jobs...")
    applier = AutonomousJobApplier(profile_path="profile.json")

    results = []
    for idx, b in enumerate(bundles[:limit], 1):
        print(f"\n>>> Processing Application [{idx}/{limit}]: {b['title']} @ {b['company']}")
        res = applier.process_application(b)
        results.append(res)
        print(f"<<< Status: {res['application_status']} | Steps: {len(res['steps_completed'])} | Answered: {len(res['questions_answered'])}")

    output_path = Path("program_files/output_v2/application_results.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n[DONE] Saved execution results to {output_path}")

if __name__ == "__main__":
    main()

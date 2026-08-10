from __future__ import annotations

import json
from datetime import date

from manufacturing_agent.repository import project_root
from manufacturing_agent.workflow import ManufacturingApplicationAgent


def main() -> None:
    root = project_root()
    cases = json.loads((root / "data" / "evals" / "cases.json").read_text(encoding="utf-8"))
    agent = ManufacturingApplicationAgent()

    assessment_passed = 0
    for case in cases["assessment_cases"]:
        run = agent.assess(
            case["company_id"],
            policy_ids=[case["policy_id"]],
            as_of=date.fromisoformat(case["as_of"]),
            actor="evaluation_runner",
        )
        result = run.assessments[0]
        passed = (
            result.window_status.value == case["expected_window"]
            and result.eligibility_status.value == case["expected_eligibility"]
        )
        assessment_passed += int(passed)
        print(f"[{'PASS' if passed else 'FAIL'}] {case['name']}")

    retrieval_passed = 0
    for case in cases["retrieval_cases"]:
        results = agent.retrieve(case["query"], top_k=5)
        passed = any(
            result.citation.source_id == case["expected_source_id"]
            and case["must_contain"] in result.text
            for result in results
        )
        retrieval_passed += int(passed)
        print(f"[{'PASS' if passed else 'FAIL'}] 检索：{case['query']}")

    assessment_total = len(cases["assessment_cases"])
    retrieval_total = len(cases["retrieval_cases"])
    print("\n评测摘要")
    print(f"- 条件/窗口准确率：{assessment_passed}/{assessment_total}")
    print(f"- 引用检索 Top-5 命中率：{retrieval_passed}/{retrieval_total}")
    if assessment_passed != assessment_total or retrieval_passed != retrieval_total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()


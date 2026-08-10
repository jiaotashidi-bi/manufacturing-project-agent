from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date

from manufacturing_agent.audit import AuditStore
from manufacturing_agent.repository import project_root
from manufacturing_agent.workflow import ManufacturingApplicationAgent


@dataclass
class EvaluationReport:
    assessment_accuracy: float
    retrieval_recall_at_1: float
    retrieval_recall_at_3: float
    retrieval_recall_at_5: float
    retrieval_mrr: float
    citation_locator_coverage: float
    unknown_abstention_rate: float
    amount_hallucination_rate: float
    material_coverage: float
    audit_chain_validity: float


def ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def evaluate() -> EvaluationReport:
    root = project_root()
    cases = json.loads((root / "data" / "evals" / "cases.json").read_text(encoding="utf-8"))
    retrieval_cases = json.loads(
        (root / "data" / "evals" / "retrieval_v2.json").read_text(encoding="utf-8")
    )
    agent = ManufacturingApplicationAgent()

    assessment_passed = 0
    unknown_expected = 0
    unknown_correct = 0
    amount_total = 0
    amount_hallucinations = 0
    material_expected = 0
    material_returned = 0
    audit_valid = 0
    runs = []
    for case in cases["assessment_cases"]:
        run = agent.assess(
            case["company_id"],
            policy_ids=[case["policy_id"]],
            as_of=date.fromisoformat(case["as_of"]),
            actor="evaluation_runner",
        )
        runs.append(run)
        result = run.assessments[0]
        passed = (
            result.window_status.value == case["expected_window"]
            and result.eligibility_status.value == case["expected_eligibility"]
        )
        assessment_passed += int(passed)
        if case["expected_eligibility"] == "needs_information":
            unknown_expected += 1
            unknown_correct += int(result.eligibility_status.value == "needs_information")
        policy = agent.repository.get_policy(case["policy_id"])
        amount_total += 1
        amount_hallucinations += int(result.amount_note != policy.amount_note)
        material_expected += len(policy.materials)
        material_returned += len(result.material_results)
        audit_valid += int(AuditStore.verify(run))

    ranks: list[int | None] = []
    locator_count = 0
    result_count = 0
    for case in retrieval_cases:
        results = agent.retrieve(case["query"], top_k=5)
        rank = None
        for index, result in enumerate(results, start=1):
            result_count += 1
            locator_count += int(bool(result.citation.locator and result.citation.url))
            if (
                rank is None
                and result.citation.source_id == case["expected_source_id"]
                and case["must_contain"] in result.text
            ):
                rank = index
        ranks.append(rank)

    report = EvaluationReport(
        assessment_accuracy=ratio(assessment_passed, len(cases["assessment_cases"])),
        retrieval_recall_at_1=ratio(sum(rank == 1 for rank in ranks), len(ranks)),
        retrieval_recall_at_3=ratio(sum(rank is not None and rank <= 3 for rank in ranks), len(ranks)),
        retrieval_recall_at_5=ratio(sum(rank is not None and rank <= 5 for rank in ranks), len(ranks)),
        retrieval_mrr=ratio(sum(1 / rank for rank in ranks if rank), len(ranks)),
        citation_locator_coverage=ratio(locator_count, result_count),
        unknown_abstention_rate=ratio(unknown_correct, unknown_expected),
        amount_hallucination_rate=ratio(amount_hallucinations, amount_total),
        material_coverage=ratio(material_returned, material_expected),
        audit_chain_validity=ratio(audit_valid, len(runs)),
    )
    return report


def main() -> None:
    report = evaluate()
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    thresholds = {
        "assessment_accuracy": 1.0,
        "retrieval_recall_at_5": 0.9,
        "citation_locator_coverage": 1.0,
        "unknown_abstention_rate": 1.0,
        "amount_hallucination_rate": 0.0,
        "material_coverage": 1.0,
        "audit_chain_validity": 1.0,
    }
    failed = []
    values = asdict(report)
    for metric, threshold in thresholds.items():
        value = values[metric]
        if metric == "amount_hallucination_rate":
            passed = value <= threshold
        else:
            passed = value >= threshold
        if not passed:
            failed.append(f"{metric}={value:.3f} (threshold {threshold:.3f})")
    if failed:
        raise SystemExit("Evaluation failed: " + "; ".join(failed))


if __name__ == "__main__":
    main()

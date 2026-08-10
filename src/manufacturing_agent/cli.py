from __future__ import annotations

import argparse
from datetime import date

from .workflow import ManufacturingApplicationAgent


def main() -> None:
    parser = argparse.ArgumentParser(description="运行制造业项目申报 Agent 演示")
    parser.add_argument("--company", default="huaxin_precision")
    parser.add_argument("--policy", action="append", dest="policies")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()

    run = ManufacturingApplicationAgent().assess(
        company_id=args.company,
        policy_ids=args.policies,
        as_of=args.as_of,
        actor="cli_user",
    )
    print(run.draft_markdown)
    print(f"\n执行轨迹已保存：{run.run_id}")


if __name__ == "__main__":
    main()


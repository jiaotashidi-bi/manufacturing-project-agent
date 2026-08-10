from __future__ import annotations

import json

from manufacturing_agent.ingestion import SourceIngestor
from manufacturing_agent.repository import project_root


def main() -> None:
    ingestor = SourceIngestor(project_root())
    path, count = ingestor.build_index()
    print(f"已写入 {count} 个检索片段：{path}")
    print(json.dumps(ingestor.inventory(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


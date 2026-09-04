"""读 FreeRouter 的 state/health.json，给"免费模型列表"菜单用。

这个文件是 refresher 容器往 `./state:/app/state` 这个 bind mount 里写的
（见 FreeRouter 的 docker-compose.yml），所以宿主机上能直接读，不需要
`docker compose exec` 进容器、也不需要服务正在跑——哪怕服务停了，也能看
最后一次探测的结果。
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass

from config import HEALTH_FILE


@dataclass(frozen=True)
class ModelEntry:
    provider: str
    model_id: str
    status: str  # "healthy" | "quarantined" | "unknown"
    last_error: str | None
    last_ok: str | None


def load_updated_at() -> str | None:
    try:
        raw = json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw.get("updated_at")


def load_models() -> list[ModelEntry]:
    try:
        raw = json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries: list[ModelEntry] = []
    for item in raw.get("models", {}).values():
        if not isinstance(item, dict):
            continue
        entries.append(
            ModelEntry(
                provider=item.get("provider", "?"),
                model_id=item.get("model_id", "?"),
                status=item.get("status", "unknown"),
                last_error=item.get("last_error"),
                last_ok=item.get("last_ok"),
            )
        )
    return entries


def group_by_provider(entries: list[ModelEntry]) -> dict[str, list[ModelEntry]]:
    """按平台分组，每组里有问题的模型排前面，方便一眼看到需要管的东西。"""
    grouped: dict[str, list[ModelEntry]] = defaultdict(list)
    for entry in entries:
        grouped[entry.provider].append(entry)
    for items in grouped.values():
        items.sort(key=lambda e: (e.status == "healthy", e.model_id))
    return dict(sorted(grouped.items()))

"""读 FreeRouter 的 providers/*.yaml，给"添加免费 API"菜单用。

故意不 import freerouter.registry——那样会把这个独立外壳绑死在 FreeRouter
的 Python 依赖（pydantic 等）上。这里只解析菜单真正需要的几个字段，容错处理：
一个 yaml 解析失败不该导致整个列表挂掉。
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml

from config import ENV_FILE, PROVIDERS_DIR, read_env_file


@dataclass(frozen=True)
class ProviderInfo:
    provider_id: str
    name_zh: str
    credential: str | None
    extra_credentials: tuple[str, ...]
    signup_url: str | None
    active: bool


def load_providers() -> list[ProviderInfo]:
    """加载 providers 目录下所有平台定义，按 provider_id 排序。"""
    providers: list[ProviderInfo] = []
    for path in sorted(PROVIDERS_DIR.glob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError):
            continue
        if not isinstance(raw, dict):
            continue
        providers.append(
            ProviderInfo(
                provider_id=raw.get("id", path.stem),
                name_zh=raw.get("name_zh") or raw.get("name") or path.stem,
                credential=raw.get("credential"),
                extra_credentials=tuple(raw.get("extra_credentials") or ()),
                signup_url=raw.get("referral_url") or raw.get("console_url"),
                active=raw.get("status", "active") == "active",
            )
        )
    return providers


def missing_credential_providers() -> list[ProviderInfo]:
    """还没配全 Key 的、在路由里生效的平台（跟 `freerouter keys` 的"还没配置"一致）。"""
    configured = read_env_file(ENV_FILE)

    def needs_key(provider: ProviderInfo) -> bool:
        names = [provider.credential, *provider.extra_credentials]
        return any(name and not configured.get(name, "").strip() for name in names)

    return [p for p in load_providers() if p.active and p.credential and needs_key(p)]

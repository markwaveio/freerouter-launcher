"""个人链接 + 版本号 + 检查更新，给"关于"菜单用。

链接先留 None——真实的博客/赞助链接一填进来，对应的菜单项就会自动出现，
不用改 app.py。检查更新用的是 GitHub Releases 的 tag，跟 pyproject.toml 里
的 version 做比较；公开仓库，不需要 token。
"""

from __future__ import annotations

import json
import re
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Final

LAUNCHER_DIR: Final = Path(__file__).resolve().parent
GITHUB_REPO: Final = "markwaveio/freerouter-launcher"
GITHUB_URL: Final = f"https://github.com/{GITHUB_REPO}"
RELEASES_API: Final = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
REQUEST_TIMEOUT: Final = 8

# 待填：加上真实链接，菜单项就会自动出现。
BLOG_URL: str | None = None
COFFEE_URL: str | None = None
MORE_MODELS_URL: str | None = None


def local_version() -> str:
    """从 pyproject.toml 读当前版本号，避免两处维护同一个数字。"""
    pyproject = LAUNCHER_DIR / "pyproject.toml"
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        return str(data["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "0.0.0"


def _parse_version(text: str) -> tuple[int, ...]:
    """把 "v0.2.1" / "0.2.1" 这样的字符串转成能比大小的数字元组。"""
    cleaned = text.strip().lstrip("vV")
    parts: list[int] = []
    for piece in cleaned.split("."):
        digits = re.sub(r"\D", "", piece)
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def fetch_latest_release() -> dict[str, str] | None:
    """查 GitHub 上最新的 release；网络问题、还没发过 release 都安静地返回 None。"""
    request = urllib.request.Request(
        RELEASES_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "freerouter-launcher"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    tag = payload.get("tag_name")
    if not tag:
        return None
    return {
        "tag": tag,
        "url": payload.get("html_url", GITHUB_URL),
        "notes": (payload.get("body") or "").strip(),
    }


def check_for_update() -> dict[str, str] | None:
    """有新版本就返回 {tag, url, notes}；已经是最新或查不到就返回 None。"""
    release = fetch_latest_release()
    if release is None:
        return None
    if _parse_version(release["tag"]) > _parse_version(local_version()):
        return release
    return None

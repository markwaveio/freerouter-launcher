"""个人链接 + 版本号 + 检查更新，给"关于"菜单用。

链接留 None 的话对应菜单项不会出现——不用为了没填的东西改 app.py。检查更新用
的是 GitHub Releases 的 tag，跟 pyproject.toml 里的 version 做比较；公开仓库，
不需要 token。
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

BLOG_URL: str | None = "https://blog.markwave.top"
MORE_MODELS_URL: str | None = "https://blog.markwave.top/docs/skills-tools/model-pricing/"

# 赞助是一张收款二维码图片，不是链接——点菜单项会弹一个原生窗口把它显示出来
# （见 app.py 的 show_image_popup），不是拿浏览器打开。文件还没放进来之前，
# .exists() 是 False，菜单里就先不出现这一项，放进去后自动出现，不用改代码。
COFFEE_QR_PATH: Final = LAUNCHER_DIR / "assets" / "coffee_qr.png"


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

"""FreeRouter Launcher 的配置。

这个项目故意放在 FreeRouter 仓库之外——它只是一层外壳，不碰 FreeRouter 本身
的代码，靠这里的路径去找到真正的 FreeRouter 仓库并驱动它的 docker compose。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# 真正的 FreeRouter 仓库在哪。如果你把它挪了地方，用 FREEROUTER_DIR 环境变量
# 覆盖即可，不用改代码。
FREEROUTER_DIR = Path(
    os.environ.get("FREEROUTER_DIR", "/Users/mark/Cursor/FreeRouter")
).expanduser()

COMPOSE_FILE = FREEROUTER_DIR / "docker-compose.yml"
ENV_FILE = FREEROUTER_DIR / ".env"
PROVIDERS_DIR = FREEROUTER_DIR / "providers"
HEALTH_FILE = FREEROUTER_DIR / "state" / "health.json"

SERVICES = ("db", "litellm", "refresher")
DEFAULT_PORT = "4000"


def read_env_file(path: Path) -> dict[str, str]:
    """解析简单的 KEY=VALUE .env 文件；文件不存在就返回空字典。"""
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def gateway_base_url() -> str:
    port = read_env_file(ENV_FILE).get("FREEROUTER_PORT", DEFAULT_PORT)
    return f"http://127.0.0.1:{port}/v1"


def master_key() -> str | None:
    return read_env_file(ENV_FILE).get("LITELLM_MASTER_KEY") or None


def _format_env_value(value: str) -> str:
    """Quote a value if it has anything that would confuse the simple KEY=VALUE parser."""
    if re.search(r"""[\s#"'\\]""", value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def write_env_value(path: Path, key: str, value: str) -> None:
    """Set ``KEY=value`` inside a .env file in place, keeping everything else untouched.

    Replaces the first existing ``KEY=...`` line; appends a new line if the key
    isn't present yet. `.env` files here are hand-maintained with lots of
    comments (where to sign up, what each variable means), so rewriting the
    whole file from a parsed dict would throw all of that away.
    """
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    new_line = f"{key}={_format_env_value(value)}"
    if pattern.search(text):
        text = pattern.sub(new_line, text, count=1)
    else:
        separator = "" if not text or text.endswith("\n") else "\n"
        text = f"{text}{separator}{new_line}\n"
    path.write_text(text, encoding="utf-8")

"""FreeRouter Launcher —— FreeRouter docker compose 服务的菜单栏外壳。

测试项目：验证"双击打开一个 app 来起停 FreeRouter"这个想法是否可行，以及能不
能把日常最常用的几个操作（起停、刷新模型池、加新平台、看状态）都搬进菜单栏，
不用记命令。真正的业务逻辑都在 FreeRouter 仓库里，这里只是调用
`docker compose` 和读它写在磁盘上的状态文件。
"""

from __future__ import annotations

import json
import shlex
import subprocess
import threading
from typing import TYPE_CHECKING, Final

import rumps

import about
from config import (
    COMPOSE_FILE,
    ENV_FILE,
    FREEROUTER_DIR,
    SERVICES,
    gateway_base_url,
    master_key,
    write_env_value,
)
from health import ModelEntry, group_by_provider, load_models, load_updated_at
from providers import ProviderInfo, missing_credential_providers

if TYPE_CHECKING:
    from collections.abc import Callable

POLL_SECONDS: Final = 5
DOCKER_TIMEOUT: Final = 10
START_TIMEOUT: Final = 180
STOP_TIMEOUT: Final = 60
RESTART_TIMEOUT: Final = 120
REFRESH_TIMEOUT: Final = 300
APPLY_TIMEOUT: Final = 180
GIT_TIMEOUT: Final = 60
UV_SYNC_TIMEOUT: Final = 120

ICONS: Final = {
    "running": "🟢",
    "partial": "🟡",
    "stopped": "⚪️",
    "docker_down": "🔴",
    "unknown": "❔",
}

LABELS: Final = {
    "running": "运行中",
    "partial": "部分运行",
    "stopped": "已停止",
    "docker_down": "Docker 未运行",
    "unknown": "状态未知",
}

STATUS_LABELS: Final = {"healthy": "健康", "quarantined": "隔离中", "unknown": "未知"}


def _run(args: list[str], timeout: int = DOCKER_TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=FREEROUTER_DIR,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _run_compose(args: list[str], timeout: int) -> tuple[bool, str]:
    """跑一条 compose 命令，返回 (是否成功, 出错信息)。"""
    try:
        result = _run(args, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "命令超时"
    except OSError as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, result.stderr[-2000:] or "未知错误"
    return True, ""


def _parse_ps(stdout: str) -> list[dict]:
    """兼容 `docker compose ps --format json` 的两种输出形状：
    一个 JSON 数组，或者一行一个 JSON 对象（JSON Lines）。
    """
    stdout = stdout.strip()
    if not stdout:
        return []
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        pass
    else:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
    items: list[dict] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return items


def docker_available() -> bool:
    try:
        result = _run(["docker", "info"], timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def compose_status() -> str:
    if not COMPOSE_FILE.exists():
        return "unknown"
    if not docker_available():
        return "docker_down"
    try:
        result = _run(["docker", "compose", "ps", "--format", "json"])
    except (subprocess.TimeoutExpired, OSError):
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    containers = _parse_ps(result.stdout)
    if not containers:
        return "stopped"
    states = [c.get("State", "") for c in containers]
    if all(s == "running" for s in states):
        return "running"
    if any(s == "running" for s in states):
        return "partial"
    return "stopped"


def _extract_cycle_summary(log_text: str) -> str | None:
    """从 refresher 的日志里摘出 `cycle complete: ...` 那一行的摘要部分。"""
    marker = "cycle complete: "
    for line in log_text.splitlines():
        index = line.find(marker)
        if index != -1:
            return line[index + len(marker) :].strip()
    return None


def _applescript_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def open_terminal(command: str) -> None:
    script = (
        'tell application "Terminal"\nactivate\ndo script '
        f"{_applescript_string(command)}\nend tell"
    )
    subprocess.run(["osascript", "-e", script], check=False)


def notify(title: str, subtitle: str, message: str) -> None:
    """尽力弹通知；新版 macOS 对未签名 app 的通知权限比较严格，失败就算了。"""
    try:
        rumps.notification(title, subtitle, message)
    except Exception:  # noqa: BLE001 - 通知只是锦上添花，绝不能因为它崩溃整个 app
        pass


def open_url(url: str) -> None:
    subprocess.run(["open", url], check=False)


class FreeRouterLauncher(rumps.App):
    def __init__(self) -> None:
        super().__init__("FreeRouter", title=f"{ICONS['unknown']} FR", quit_button=None)
        self._busy = False
        self._model_menu_ready = False
        self._add_key_menu_ready = False
        self._about_menu_ready = False
        self._pending_update: dict[str, str] | None = None

        self.status_item = rumps.MenuItem("状态：检查中…")
        self.model_menu = rumps.MenuItem("免费模型列表")
        self.add_key_menu = rumps.MenuItem("添加免费 API")
        self.about_menu = rumps.MenuItem("关于")

        self.menu = [
            self.status_item,
            None,
            rumps.MenuItem("启动服务", callback=self.start_stack),
            rumps.MenuItem("停止服务", callback=self.stop_stack),
            rumps.MenuItem("重启服务", callback=self.restart_stack),
            rumps.MenuItem("一键刷新免费模型", callback=self.refresh_models),
            None,
            self.model_menu,
            self.add_key_menu,
            None,
            rumps.MenuItem("查看日志（终端）", callback=self.show_logs),
            rumps.MenuItem("复制 API 地址", callback=self.copy_base_url),
            rumps.MenuItem("复制 Master Key", callback=self.copy_master_key),
            rumps.MenuItem("在 Finder 中显示 FreeRouter", callback=self.reveal_in_finder),
            None,
            self.about_menu,
            None,
            rumps.MenuItem("退出启动器（不停止服务）", callback=self.quit_launcher),
        ]

        self.refresh(None)
        self.rebuild_model_menu()
        self.rebuild_add_key_menu()
        self.rebuild_about_menu()

        self.timer = rumps.Timer(self.refresh, POLL_SECONDS)
        self.timer.start()

        # 启动时静默查一次更新：有新版本才通知，已经是最新就什么都不说，不烦人。
        threading.Thread(
            target=self._run_update_check, kwargs={"announce_if_current": False}, daemon=True
        ).start()

    # ------------------------------------------------------------------ #
    # 状态轮询
    # ------------------------------------------------------------------ #

    def refresh(self, _sender: object) -> None:
        status = compose_status()
        self.title = f"{ICONS[status]} FR"
        self.status_item.title = f"状态：{LABELS[status]}"

    # ------------------------------------------------------------------ #
    # 后台任务：所有耗时的 docker 操作都走这里，避免卡住菜单栏主线程
    # ------------------------------------------------------------------ #

    def _run_in_background(self, label: str, func: Callable[[], None]) -> None:
        if self._busy:
            rumps.alert(title="请稍等", message=f"上一个操作还没完成，等它结束再点「{label}」。")
            return
        self._busy = True

        def worker() -> None:
            try:
                func()
            finally:
                self._busy = False

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------ #
    # 起停
    # ------------------------------------------------------------------ #

    def start_stack(self, _sender: object) -> None:
        if not docker_available():
            rumps.alert(
                title="Docker 没有运行",
                message="先打开 Docker Desktop，等它就绪之后再点启动。已尝试帮你打开。",
            )
            subprocess.run(["open", "-a", "Docker"], check=False)
            return

        def work() -> None:
            notify("FreeRouter", "正在启动…", "docker compose up -d")
            ok, error = _run_compose(["docker", "compose", "up", "-d"], timeout=START_TIMEOUT)
            if ok:
                notify("FreeRouter", "已启动", gateway_base_url())
            else:
                notify("FreeRouter", "启动失败", error[:200] or "未知错误")
            self.refresh(None)

        self._run_in_background("启动服务", work)

    def stop_stack(self, _sender: object) -> None:
        def work() -> None:
            notify("FreeRouter", "正在停止…", "docker compose down")
            ok, error = _run_compose(["docker", "compose", "down"], timeout=STOP_TIMEOUT)
            if not ok:
                notify("FreeRouter", "停止失败", error[:200] or "未知错误")
            self.refresh(None)

        self._run_in_background("停止服务", work)

    def restart_stack(self, _sender: object) -> None:
        def work() -> None:
            notify("FreeRouter", "正在重启…", "docker compose restart")
            ok, error = _run_compose(["docker", "compose", "restart"], timeout=RESTART_TIMEOUT)
            if not ok:
                notify("FreeRouter", "重启失败", error[:200] or "未知错误")
            self.refresh(None)

        self._run_in_background("重启服务", work)

    # ------------------------------------------------------------------ #
    # 一键刷新免费模型池
    # ------------------------------------------------------------------ #

    def refresh_models(self, _sender: object) -> None:
        status = compose_status()
        if status in ("stopped", "docker_down", "unknown"):
            rumps.alert(
                title="服务没在跑",
                message="先点「启动服务」，refresher 容器起来之后才能刷新。",
            )
            return

        def work() -> None:
            notify("FreeRouter", "正在刷新…", "重新探测一轮免费模型，可能要一两分钟")
            try:
                result = _run(
                    [
                        "docker",
                        "compose",
                        "exec",
                        "-T",
                        "refresher",
                        "python",
                        "-m",
                        "freerouter",
                        "refresh",
                    ],
                    timeout=REFRESH_TIMEOUT,
                )
            except subprocess.TimeoutExpired:
                notify("FreeRouter", "刷新超时", "探测时间超过预期，稍后自己去看模型列表")
                return
            except OSError as exc:
                notify("FreeRouter", "刷新失败", str(exc)[:200])
                return

            summary = _extract_cycle_summary(result.stderr)
            if summary:
                notify("FreeRouter", "刷新完成", summary)
            elif result.returncode == 0:
                notify("FreeRouter", "刷新完成", "去「免费模型列表」看最新结果")
            else:
                notify("FreeRouter", "刷新失败", result.stderr[-200:] or "未知错误")
            self.rebuild_model_menu()

        self._run_in_background("一键刷新免费模型", work)

    # ------------------------------------------------------------------ #
    # 免费模型列表（读 state/health.json，不联网）
    # ------------------------------------------------------------------ #

    def rebuild_model_menu(self) -> None:
        # rumps.MenuItem 的子菜单是懒加载的：第一次调用之前它内部还没有真正的
        # NSMenu，这时候 .clear() 会直接崩溃。.update() 只增不删，所以除了
        # 第一次，后面每次重建都必须先 clear 掉上一轮的旧条目。
        if self._model_menu_ready:
            self.model_menu.clear()
        self.model_menu.update(self._build_model_menu_items())
        self._model_menu_ready = True

    def _build_model_menu_items(self) -> list:
        items: list = [
            rumps.MenuItem("刷新列表显示（只重读本地状态，不联网）", callback=self._refresh_model_menu_display),
        ]
        updated_at = load_updated_at()
        if updated_at:
            items.append(rumps.MenuItem(f"最后更新：{updated_at[:19].replace('T', ' ')}"))
        items.append(None)

        entries = load_models()
        if not entries:
            items.append(rumps.MenuItem("（还没有数据：先启动服务，再点一次「一键刷新免费模型」）"))
            return items

        grouped = group_by_provider(entries)
        for provider_id, models in grouped.items():
            healthy = sum(1 for m in models if m.status == "healthy")
            header = f"{provider_id}（{healthy}/{len(models)} 可用）"
            model_items = [
                rumps.MenuItem(
                    f"{'✅' if m.status == 'healthy' else '🚫'} {m.model_id}",
                    callback=lambda _s, entry=m: self._show_model_detail(entry),
                )
                for m in models
            ]
            items.append((header, model_items))
        return items

    def _refresh_model_menu_display(self, _sender: object) -> None:
        self.rebuild_model_menu()

    def _show_model_detail(self, entry: ModelEntry) -> None:
        lines = [
            f"平台：{entry.provider}",
            f"状态：{STATUS_LABELS.get(entry.status, entry.status)}",
        ]
        if entry.last_ok:
            lines.append(f"最近一次成功：{entry.last_ok[:19].replace('T', ' ')}")
        if entry.last_error:
            lines.append(f"最近报错：{entry.last_error}")
        rumps.alert(title=entry.model_id, message="\n".join(lines))

    # ------------------------------------------------------------------ #
    # 添加免费 API
    # ------------------------------------------------------------------ #

    def rebuild_add_key_menu(self) -> None:
        if self._add_key_menu_ready:
            self.add_key_menu.clear()
        missing = missing_credential_providers()
        if not missing:
            self.add_key_menu.update([rumps.MenuItem("都配好了，没有缺 Key 的平台")])
        else:
            items = [
                rumps.MenuItem(
                    f"{provider.name_zh}（{provider.provider_id}）",
                    callback=lambda _s, p=provider: self._prompt_add_key(p),
                )
                for provider in missing
            ]
            self.add_key_menu.update(items)
        self._add_key_menu_ready = True

    def _prompt_add_key(self, provider: ProviderInfo) -> None:
        var_names = [name for name in (provider.credential, *provider.extra_credentials) if name]
        collected: dict[str, str] = {}

        for var in var_names:
            hint = f"\n注册/获取地址：{provider.signup_url}" if provider.signup_url else ""
            window = rumps.Window(
                message=f"{provider.name_zh} 需要 {var}{hint}",
                title=f"添加 {provider.name_zh}",
                ok="保存",
                cancel="取消",
                dimensions=(320, 24),
                secure=True,
            )
            response = window.run()
            if not response.clicked:
                return
            value = response.text.strip()
            if not value:
                rumps.alert(title="没填内容", message="留空不会保存，已取消。")
                return
            collected[var] = value

        for var, value in collected.items():
            write_env_value(ENV_FILE, var, value)

        notify("FreeRouter", "已保存", f"{provider.name_zh} 的 Key 已写入 .env，正在应用…")
        self.rebuild_add_key_menu()

        if not docker_available():
            rumps.alert(
                title="Docker 没有运行",
                message="Key 已经存到 .env 了。打开 Docker Desktop 后点「启动服务」就会用上。",
            )
            subprocess.run(["open", "-a", "Docker"], check=False)
            return

        def work() -> None:
            ok, error = _run_compose(["docker", "compose", "up", "-d"], timeout=APPLY_TIMEOUT)
            if ok:
                notify(
                    "FreeRouter",
                    "已应用",
                    f"{provider.name_zh} 已接入，等它探测一轮后去「免费模型列表」看",
                )
            else:
                notify("FreeRouter", "应用失败", error[:200] or "未知错误")
            self.refresh(None)
            self.rebuild_model_menu()

        self._run_in_background(f"添加 {provider.name_zh}", work)

    # ------------------------------------------------------------------ #
    # 关于 + 检查更新
    # ------------------------------------------------------------------ #

    def rebuild_about_menu(self) -> None:
        if self._about_menu_ready:
            self.about_menu.clear()
        self.about_menu.update(self._build_about_menu_items())
        self._about_menu_ready = True

    def _build_about_menu_items(self) -> list:
        items: list = [rumps.MenuItem(f"FreeRouter Launcher v{about.local_version()}")]

        if self._pending_update:
            items.append(
                rumps.MenuItem(
                    f"⬆️ 立即更新到 {self._pending_update['tag']}",
                    callback=self.apply_update,
                )
            )
        items.append(rumps.MenuItem("检查更新", callback=self.check_for_update))

        links = [
            ("📝 博客", about.BLOG_URL),
            ("🍪 更多免费模型分享", about.MORE_MODELS_URL),
            ("☕ 请我喝杯咖啡", about.COFFEE_URL),
            ("GitHub 仓库", about.GITHUB_URL),
        ]
        visible = [(label, url) for label, url in links if url]
        if visible:
            items.append(None)
            items.extend(
                rumps.MenuItem(label, callback=lambda _s, u=url: open_url(u))
                for label, url in visible
            )
        return items

    def _run_update_check(self, *, announce_if_current: bool) -> None:
        # 只读一个公开的 GitHub API，跟 docker 操作没有资源冲突，不走 _busy 那把
        # 锁——不然启动时自动查一次，正好撞上你手快点了「启动服务」就白白等一下。
        release = about.check_for_update()
        if release is not None:
            self._pending_update = release
            notify("FreeRouter Launcher", f"发现新版本 {release['tag']}", "去「关于」菜单点「立即更新」")
            self.rebuild_about_menu()
        elif announce_if_current:
            notify("FreeRouter Launcher", "已是最新版本", f"当前 v{about.local_version()}")

    def check_for_update(self, _sender: object) -> None:
        threading.Thread(
            target=self._run_update_check, kwargs={"announce_if_current": True}, daemon=True
        ).start()

    def apply_update(self, _sender: object) -> None:
        if not self._pending_update:
            rumps.alert(title="没有待更新的版本", message="先点一次「检查更新」。")
            return

        def work() -> None:
            notify("FreeRouter Launcher", "正在更新…", "git pull + uv sync")
            try:
                pull = subprocess.run(
                    ["git", "pull", "--ff-only"],
                    cwd=about.LAUNCHER_DIR,
                    capture_output=True,
                    text=True,
                    timeout=GIT_TIMEOUT,
                )
            except (subprocess.TimeoutExpired, OSError) as exc:
                notify("FreeRouter Launcher", "更新失败", str(exc)[:200])
                return
            if pull.returncode != 0:
                # --ff-only 在本地有未提交的改动、或者历史分叉时会直接拒绝，而不是
                # 帮你生成一个 merge commit——这是故意的，免得静默改掉你自己在
                # 手改的代码。出这种情况需要你自己去看一眼再决定。
                notify("FreeRouter Launcher", "更新失败（git pull）", pull.stderr[-200:] or pull.stdout[-200:])
                return

            try:
                sync = subprocess.run(
                    ["uv", "sync"],
                    cwd=about.LAUNCHER_DIR,
                    capture_output=True,
                    text=True,
                    timeout=UV_SYNC_TIMEOUT,
                )
            except (subprocess.TimeoutExpired, OSError) as exc:
                notify("FreeRouter Launcher", "更新失败（uv sync）", str(exc)[:200])
                return
            if sync.returncode != 0:
                notify("FreeRouter Launcher", "更新失败（uv sync）", sync.stderr[-200:] or "未知错误")
                return

            notify("FreeRouter Launcher", "更新完成，正在重新打开…", self._pending_update["tag"])
            self._pending_update = None
            self._relaunch()

        self._run_in_background("立即更新", work)

    def _relaunch(self) -> None:
        app_bundle = about.LAUNCHER_DIR / "FreeRouter Launcher.app"
        try:
            if app_bundle.exists():
                subprocess.Popen(["open", str(app_bundle)])
            else:
                subprocess.Popen(
                    ["uv", "run", "--project", str(about.LAUNCHER_DIR), "python", "app.py"],
                    cwd=about.LAUNCHER_DIR,
                )
        except OSError:
            notify("FreeRouter Launcher", "自动重启失败", "手动退出后再双击打开一次就行")
            return
        rumps.quit_application()

    # ------------------------------------------------------------------ #
    # 其它工具菜单
    # ------------------------------------------------------------------ #

    def show_logs(self, _sender: object) -> None:
        services = " ".join(SERVICES)
        command = f"cd {shlex.quote(str(FREEROUTER_DIR))} && docker compose logs -f {services}"
        open_terminal(command)

    def copy_base_url(self, _sender: object) -> None:
        subprocess.run(["pbcopy"], input=gateway_base_url(), text=True, check=False)
        notify("FreeRouter", "已复制", "API 地址已复制到剪贴板")

    def copy_master_key(self, _sender: object) -> None:
        key = master_key()
        if not key:
            rumps.alert(
                title="没找到 Master Key",
                message=f"检查 {FREEROUTER_DIR / '.env'} 里的 LITELLM_MASTER_KEY",
            )
            return
        subprocess.run(["pbcopy"], input=key, text=True, check=False)
        notify("FreeRouter", "已复制", "Master Key 已复制到剪贴板（未显示明文）")

    def reveal_in_finder(self, _sender: object) -> None:
        subprocess.run(["open", str(FREEROUTER_DIR)], check=False)

    def quit_launcher(self, _sender: object) -> None:
        rumps.quit_application()


if __name__ == "__main__":
    FreeRouterLauncher().run()

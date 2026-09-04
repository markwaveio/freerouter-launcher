#!/usr/bin/env bash
# 把 app.py 包成一个能双击打开的 "FreeRouter Launcher.app"。
#
# 不用 py2app：py2app 要求「framework 编译」的 Python，跟 uv 自己下载管理的
# 解释器经常对不上，容易在打包这步莫名其妙失败。这里换成最朴素的办法——手搭
# 一个标准 .app 目录结构，可执行文件是个小 shell 脚本，负责用 uv 跑 app.py。
# 逻辑简单、好排查，缺点是这个 .app 里的路径是写死的，不能拷到别的电脑上用。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="FreeRouter Launcher.app"
APP_DIR="$HERE/$APP_NAME"
CONTENTS="$APP_DIR/Contents"

echo "==> 准备依赖（uv sync）"
cd "$HERE"
uv sync

echo "==> 生成 $APP_NAME"
rm -rf "$APP_DIR"
mkdir -p "$CONTENTS/MacOS" "$CONTENTS/Resources"

cat > "$CONTENTS/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>FreeRouter Launcher</string>
    <key>CFBundleDisplayName</key>
    <string>FreeRouter Launcher</string>
    <key>CFBundleIdentifier</key>
    <string>dev.markwave.freerouter-launcher</string>
    <key>CFBundleVersion</key>
    <string>0.1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>0.1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>launcher</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
</dict>
</plist>
PLIST

cat > "$CONTENTS/MacOS/launcher" <<LAUNCHER
#!/usr/bin/env bash
# Finder 双击启动的 GUI 进程拿到的 PATH 很寒酸，这里手动把常见的 uv 安装位置加回去。
export PATH="/opt/homebrew/bin:/usr/local/bin:\$HOME/.local/bin:\$PATH"
exec uv run --project "$HERE" python "$HERE/app.py"
LAUNCHER
chmod +x "$CONTENTS/MacOS/launcher"

echo "==> 清除隔离标记 + ad-hoc 签名（Apple Silicon 跑未签名二进制需要至少 ad-hoc 签名）"
xattr -cr "$APP_DIR" 2>/dev/null || true
codesign --force --deep --sign - "$APP_DIR" 2>/dev/null || true

echo "==> 完成: $APP_DIR"
echo "双击打开，或者命令行: open \"$APP_DIR\""

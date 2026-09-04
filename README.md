# FreeRouter Launcher（测试项目）

验证一件事：能不能把 [FreeRouter](../FreeRouter) 那套 docker compose 服务包成
一个双击就能开关的 macOS 应用，不用记 `make up` / `make down`、不用开终端。

**这里不改 FreeRouter 一行代码。** 这个目录是一个独立的外壳，通过
[config.py](config.py) 里的路径找到 `../FreeRouter`，调用它的
`docker compose` 来起停。FreeRouter 该怎么跑还怎么跑，这个项目不满意随时删掉，
互不影响。

## 为什么是菜单栏应用，不是普通窗口应用

FreeRouter 本身没有界面——它是个常驻后台的 API 网关（监听
`127.0.0.1:4000`），成功与否体现在"容器有没有在跑"。这种东西塞进一个每次点开
都要出现窗口的 App 里反而别扭，更贴近 Docker Desktop、Ollama 那种**菜单栏图标
+ 下拉菜单**的形态：图标颜色看状态，点一下开关，不用时挂在那里几乎零打扰。

## 怎么跑起来

**方式一：直接跑脚本（改代码时用这个，改完立刻能看到效果）**

```bash
cd freerouter-launcher
uv sync
uv run python app.py
```

菜单栏会出现一个 `FR` 图标。`Ctrl+C` 或者从菜单里点"退出启动器"结束。

**方式二：打包成真正的 .app（验证"双击打开"这个最终形态）**

```bash
./build_app.sh
open "FreeRouter Launcher.app"
```

以后双击 `FreeRouter Launcher.app` 就行，也可以拖进 `/Applications` 或者放
Dock 里。

## 图标含义 & 菜单功能

| 图标 | 含义 |
| --- | --- |
| 🟢 | 三个容器（db / litellm / refresher）都在跑 |
| 🟡 | 部分容器在跑 |
| ⚪️ | 已停止 |
| 🔴 | Docker Desktop 没开 |
| ❔ | 状态未知（比如 FreeRouter 目录找不到） |

菜单项：启动 / 停止 / 重启服务，一键刷新免费模型，免费模型列表，添加免费
API，查看日志（开一个终端跑 `docker compose logs -f`），复制 API 地址、复制
Master Key（从 `.env` 读，只拷到剪贴板，不会明文显示在任何弹窗或通知里），在
Finder 里定位 FreeRouter 目录，退出启动器。

**"退出启动器"不会停止 FreeRouter 服务**——两者故意分开，免得别的 Agent 正在
用着 API，你关个菜单栏小图标却把网关一起干掉了。真要停服务，用"停止服务"。

**启动 / 停止 / 重启 / 刷新 / 添加 API 都在后台线程里跑**，不会卡住菜单栏（有
几个操作因为要等 Docker 健康检查，实际能跑到一两分钟）。同时只允许一个这样的
操作在进行，手快多点几下会提示"请稍等"，不会真的并发跑两条 `docker compose`
命令互相打架。

### 一键刷新免费模型

菜单里点"一键刷新免费模型"，相当于 `make refresh`：让 refresher 容器立刻跑一
轮发现 + 探测，不用等它自己的 6 小时定时器。前提是服务已经在跑（refresher 容
器得存在），没跑会提示先启动。跑完会弹通知，摘要格式类似
`discovered=77 healthy=56 quarantined=21 ...`。

### 免费模型列表

按平台分组的嵌套菜单，每个平台显示"健康/总数"，每个模型前面是 ✅（健康）或
🚫（隔离中），有问题的排在每组前面方便一眼看到。点单个模型能看到它的状态、最
近一次成功时间、最近的报错（如果隔离了）。

这个列表**直接读 [state/health.json](../FreeRouter/state/health.json)**，不
经过 `docker compose exec`——这个文件是 refresher 容器往宿主机的 bind mount
（`docker-compose.yml` 里的 `./state:/app/state`）写的，所以哪怕服务当前是停
着的，也能看到最后一次探测的结果。子菜单顶部有个"刷新列表显示"，只是重新读一
遍这个文件，不联网、不触发新的探测——想要真正重新探测，用上面的"一键刷新免费
模型"。

### 添加免费 API

列出所有还没配 Key 的平台（跟 `freerouter keys` 的逻辑一致：平台是
`active` 状态、且必需的凭证变量在 `.env` 里还是空的）。点一个平台会弹出一个输
入框（密码框样式，输入时不显示明文），如果这个平台需要不止一个变量（比如
Cloudflare 要 `CLOUDFLARE_API_KEY` 和 `CLOUDFLARE_ACCOUNT_ID` 两个），会依次
弹出多个输入框。填完直接写进 `.env`（用正则原地替换那一行，不会把整个文件用
解析后的字典重新生成一遍，所以 `.env` 里那些"去哪注册"的注释都还在）。

**保存后台会自动跑一次 `docker compose up -d`。** 这里有个不直观但很重要的点：
FreeRouter 的 `litellm` 和 `refresher` 容器在创建时就把 `.env` 的内容"烤"进了
容器自己的环境变量里，之后单纯改宿主机上的 `.env` 文件，正在跑的容器是看不见
的——`docker compose exec` 进去执行命令，用的还是创建容器那一刻的旧环境。只有
`docker compose up -d` 会重新计算配置的 hash、发现 `.env` 变了，从而重建
`litellm`/`refresher` 两个容器（`db` 不受影响，因为 `POSTGRES_*` 没变），新容
器一启动，`refresher` 的常驻进程会自动先跑一轮探测再进入定时循环——这就是为什
么添加新 Key 用的是 `up -d` 而不是 `exec refresher ... refresh`。代价是
`litellm` 网关会有几秒到几十秒的中断（等它的健康检查再过一遍），仅在你真的改
了 `.env` 时才会发生；平时没改任何配置，`up -d` 对已经在跑的容器是完全无操作
的。

## 已知限制（毕竟是测试项目）

- **加了 Key 之后模型列表不会马上更新**：`docker compose up -d` 返回之后，容
  器还得先过健康检查、`refresher` 再跑一轮发现 + 探测，新平台的模型才会出现
  在"免费模型列表"里，一般是几十秒到一两分钟。心急的话等一下再点"刷新列表显
  示"，或者干脆再点一次"一键刷新免费模型"确认。
- **API Key 明文存在 `.env` 里**：跟手动编辑 `.env` 完全一样的风险，这个功能
  只是省了你自己找变量名、改文件的功夫，没有引入新的存储方式或加密。
- **路径写死**：`build_app.sh` 生成的 `.app` 里，调用 FreeRouter 的路径是构建
  时电脑上的绝对路径，不能拷给别人用。要分发给别人，得换成
  [py2app](https://py2app.readthedocs.io/) 或 [PyInstaller](https://pyinstaller.org/)
  做成真正独立的包，或者至少把路径改成运行时探测。
- **没有自定义图标**：Dock/Finder 里显示系统默认图标（`LSUIElement` 之下其实
  平时也看不到 Dock 图标）。想要的话找一张 1024×1024 的图，用 `sips` +
  `iconutil` 转成 `.icns`，扔进 `Contents/Resources/` 并在 `Info.plist` 里加
  `CFBundleIconFile` 就行。
- **通知不保证弹出**：新版 macOS 对未签名 App 的通知权限收得很紧，弹不出来时
  功能不受影响，就是少个提示。真出错（比如启动失败）会用弹窗
  （`rumps.alert`）兜底，这个不受通知权限影响。
- **首次打开可能被 Gatekeeper 拦**：`build_app.sh` 已经做了 ad-hoc 签名
  （`codesign --sign -`），但因为不是正规开发者证书签名，Finder 双击时如果提示
  "无法验证开发者"，右键（或按住 Control 点按）→ 打开 → 确认一次，以后就正常
  双击了。
- **活动监视器里进程名是 `Python`，不是 `FreeRouter Launcher`**——因为外壳脚本
  是 `uv run python app.py`，没有做进程改名。想强制结束就按这个名字找。
- 依赖 **Docker Desktop 已安装**；没装的话"启动服务"会尝试 `open -a Docker`
  但打不开会失败，需要先手动装好。

## 如果 FreeRouter 挪了地方

[config.py](config.py) 默认指向 `/Users/mark/Cursor/FreeRouter`。挪了地方就设
环境变量，不用改代码：

```bash
FREEROUTER_DIR=/new/path/to/FreeRouter uv run python app.py
```

打包进 `.app` 的版本要改路径的话，改完 [config.py](config.py) 后重新跑一次
`./build_app.sh` 即可（脚本里的 `$HERE` 是自动探测的，指向这个项目本身的位置，
不用管；`FREEROUTER_DIR` 才是指向 FreeRouter 仓库的那个变量）。

# ReOps 运行说明

公开源码：[magic12222/reops-release](https://github.com/magic12222/reops-release)。
以下命令在 Windows PowerShell 执行。解压或克隆后，先进入含本文件的项目根目录。
目录可以自行选择，含空格时加引号。不要与旧版本共用运行目录或数据库。

## 1. 准备并安装

需要 Windows 10/11、Python 3.11、Node.js 24、pnpm 11.25.0。
业务监控另需 Docker Desktop，使用 Linux containers 并启动引擎。
本次核对版本为 Python 3.11.4、Node.js 24.18.0、pnpm 11.25.0、Docker 29.8.0 / Compose v5.5.1；未验证其他操作系统。
首次安装和镜像下载需要联网。只查看网页样例无需 Docker 或模型 Key。

尚未安装 pnpm 时先执行：

```powershell
npm install --global pnpm@11.25.0
```

在项目根目录安装依赖并构建网页：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

脚本创建项目内 `.venv-nexent`，使用 Python 版本清单和前端锁文件安装。
需要实际模型诊断时，另需 Git，并添加 `-Model` 下载固定提交的 Nexent SDK：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Model
```

## 2. 最快查看网页

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1 -Part sample
```

打开 [样例工作台](http://127.0.0.1:4173/workbench?source=offline_fixture)。
选择“样例数据 / Sample data”浏览工作台、Execution、Knowledge；Agent 选择 OFFLINE FIXTURE。
首页和 Recovery 为可交互模拟，不会停止或恢复真实服务。
此方式不启动监控或模型后台；API 配置需使用第4节。查看完在终端按 Ctrl+C。

## 3. 首次部署 Vikunja

打开 Docker Desktop，确认 `docker info` 正常返回。在项目根目录执行只读检查：

```powershell
.\.venv-nexent\Scripts\python.exe -m scripts.prepare_vikunja_demo
```

已有本版本的演示容器则跳到第4节。若存在其他目录的同名容器或卷，先核对归属，不覆盖或删除。
仅在不存在演示容器和卷时，按顺序下载固定镜像并部署：

```powershell
$images = Get-Content integrations\vikunja\images.lock.json -Raw | ConvertFrom-Json
docker pull $images.images.postgres.digest
docker tag $images.images.postgres.digest $images.images.postgres.tag
docker pull $images.images.app.digest
docker tag $images.images.app.digest $images.images.app.tag
.\.venv-nexent\Scripts\python.exe -m scripts.prepare_vikunja_demo --deploy
```

每条成功后再执行下一条。脚本生成独立配置，无需创建含密码的 `.env`。
打开 [Vikunja](http://127.0.0.1:18110)。数据库及应用数据保留在本机 Docker 卷。

## 4. 启动业务监控版

容器已运行则跳过容器启动。否则先启动数据库并检查就绪：

```powershell
docker start reops-vikunja-demo-postgres-1
docker exec reops-vikunja-demo-postgres-1 pg_isready -U reops_demo -d reops_vikunja_demo
```

显示 `accepting connections` 后启动应用：

```powershell
docker start reops-vikunja-demo-app-1
```

打开三个 PowerShell 终端，各先进入项目根目录，按顺序执行并保持打开：

| 顺序 | 命令 | 用途 |
| --- | --- | --- |
| 终端 A | `powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1 -Part monitor` | 8021，创建独立测试账号及任务，等待网页开始监控 |
| 终端 B | `powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1 -Part api` | 8020，模型配置、对话与证据 |
| 终端 C | `powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1 -Part web` | 5174，网页分别连接8020和8021 |

打开 [ReOps 工作台](http://127.0.0.1:5174/workbench?source=real)，选择 Local connection。
默认监控账号与你手动注册的账号独立。如需使用自己的演示账号，终端 A 改用：

```powershell
.\.venv-nexent\Scripts\python.exe -m scripts.run_vikunja_workbench --serve --paused --login
```

按提示输入账号及密码，密码不回显，不放进命令或文件。
选择 Vikunja，阅读页面范围后，由操作者点击监控批准入口。
统一入口可包含最多8小时、3次事件、60秒间隔的依赖恢复范围，具体以批准详情为准。
执行只针对演示的固定容器，先检查数据库，在退出证据满足时启动应用，再验证业务。
只需观察时使用仅监控入口；普通软件的基础存活监控不提供同等业务恢复能力。
故障演示须先确认健康、范围和批准状态，再操作本演示数据库。

## 5. 配置模型 API

打开 [API 页面](http://127.0.0.1:5174/api)，新增服务，填写名称、提供商、实际模型 ID、公共 HTTPS API base 及自己的 Key。
地址格式示例为 `https://api.example.com/v1`，此占位地址不能直接使用。
接口须兼容 OpenAI chat / models；不接受任意本机或内网地址。
保存后“设为当前”，再点击连接测试。测试只读取模型列表，不代表聊天、恢复或经验写入通过。

Windows 把 Key 保存在当前用户的系统凭据管理器，`runtime/model-services.json` 只存公开元数据。
重启需重新测试；授权、会话及验证状态不恢复。不要搬运 runtime 或凭据。
实际对话需安装 `-Model` 依赖，并满足页面诊断范围及当次批准。
指定恢复的 Execution 显示实际请求、回复、验证及经验；未调用模型时不会生成对话。
模型建议不扩大固定恢复执行权限。新下载包没有作者历史记录、Key 或已批准任务。

本包不含 ResearchLoop-AI 外部应用，并隐藏其运行入口；请使用 Vikunja 工作台。

## 6. 停止与再次启动

网页关闭自动恢复、暂停业务监控，再依次在网页、API、监控终端按 Ctrl+C。
关闭浏览器不会停止后台监控。如需全部停止，再执行：

```powershell
docker stop reops-vikunja-demo-app-1
docker stop reops-vikunja-demo-postgres-1
```

再次使用从第4节启动，重新测试模型并按需批准。保留容器及卷，不要删除卷来停止。

## 7. 检查与排错

在公开源码包根目录执行：

```powershell
.\.venv-nexent\Scripts\python.exe -m scripts.check_release
.\.venv-nexent\Scripts\python.exe scripts\validate_shared.py
pnpm --dir web test
pnpm --dir web run build
```

`check_release` 核对随包 SHA256、敏感路径及常见密钥格式，并用空数据库与隔离接口检查；不访问真实模型或执行恢复。
自行修改源码后，原始清单校验失败属于预期。

| 现象 | 处理 |
| --- | --- |
| 找不到 Python、pnpm 或虚拟环境 | 安装指定工具，在含本文件的目录运行安装脚本 |
| 依赖或镜像下载失败 | 检查联网及代理，保留错误，不擅自换用 latest 镜像 |
| 18110 打不开 | 确认数据库先就绪、应用随后运行，检查对应容器状态 |
| 8020 / 8021 / 5174 占用 | 使用已有同目录服务，或回原终端 Ctrl+C，不结束不明进程 |
| 网页正常，API 或工作台不可用 | 检查终端 A/B；终端 C 使用本包脚本，两个接口地址不同 |
| `existing_demo_no_recreate_or_volume_reuse` | 已有环境，启动原容器，不重复首次部署 |
| 模型列表成功但无对话 | 检查 SDK、模型 ID、诊断范围及实际记录；列表测试不发送推理 |
| 恢复被阻止或失败 | 查看 Execution 证据及原因，未知状态不要反复重放 |

交付检查使用独立解压目录与离线样例，未重新执行真实模型推理、故障注入或真实恢复。
新电脑的首次容器部署与模型可用性须按当次输出确认。

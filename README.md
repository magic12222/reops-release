# ReOps 评审操作指南

ReOps 将软件故障的监测、受限恢复、执行证据和经验关联放在同一个工作台。评审时建议先浏览内置样例，再按需运行 Vikunja 真实业务演示。

源码：[magic12222/reops-release](https://github.com/magic12222/reops-release)。以下操作面向 Windows 10/11，命令在 PowerShell 中执行。解压后先进入包含本文件的项目根目录；路径可自行选择，含空格时加引号。

## 一、先选择体验方式

| 体验方式 | 可以查看什么 | 需要什么 |
| --- | --- | --- |
| 内置样例，建议先看 | 故障记录、执行时间线、样例模型对话、经验图谱、恢复动画 | Python、Node.js、pnpm；无需 Docker 或 API Key |
| 真实业务演示 | 监控 Vikunja，观察数据库停止后的受限恢复与业务验证，查看本轮执行记录 | 上述工具及 Docker Desktop |
| 鸿蒙手机端 | 查看业务健康、故障与历史诊断；体验App专用缓存监测和恢复 | Windows、DevEco Studio、HarmonyOS手机；远端监控另需Docker |
| 真实模型分析 | 在本轮执行记录中查看实际模型请求及回复 | 真实业务环境、可用的模型 API Key、可选 Nexent SDK |

**样例是预置数据，首页与 Recovery 页面是交互模拟。真实演示请使用工作台的“本地连接”。** 新下载包没有作者的历史数据、模型 Key 或已批准任务。

## 二、安装与启动样例

### 1. 首次安装

准备 Python 3.11、Node.js 24 和 pnpm 11.25.0。首次安装需要联网。
本包核对环境为 Python 3.11.4、Node.js 24.18.0、pnpm 11.25.0；未验证其他操作系统。
如没有 pnpm，先执行：

```powershell
npm install --global pnpm@11.25.0
```

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

看到 `Installation complete` 后再启动。脚本会创建项目内 Python 环境、安装锁定依赖并构建网页，不需要手动激活虚拟环境。

### 2. 打开样例工作台

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1 -Part sample
```

保持终端打开，访问 [样例工作台](http://127.0.0.1:4173/workbench?source=offline_fixture)。页面右上角应为“样例预览 / Sample preview”，上方显示 `SAMPLE DATA`。如果误切到“本地连接”，在下拉框切回“样例预览”。

### 3. 按这个顺序体验

| 步骤 | 怎么操作 | 应看到什么 |
| --- | --- | --- |
| ① 选择故障 | 在工作台左侧选择样例应用，再点击一条故障历史 | 中间显示该次故障的结果、记录时间、验证和证据 |
| ② 看处理依据 | 在中间切换“证据”“API 交互”“经验与图谱”等页签，展开需要的条目 | 该次记录的事件、样例请求/回复及经验来源；不是当前真实请求 |
| ③ 看执行过程 | 点击“查看执行记录 / Inspect execution”，进入 Execution | 左侧是同一次故障的时间线，右侧是已记录的模型消息与当前步骤上下文 |
| ④ 查看具体一步 | 点击左侧某个事件；右侧展开消息或底部工具交互 | 对应步骤的依据、工具和验证信息；点击事件会暂停自动跟随，可用“Follow live”恢复 |
| ⑤ 看经验关系 | 点击顶部“知识 / Knowledge”或工作台“全局知识 / Global knowledge” | 全局知识图谱；点击节点查看右侧详情及来源，可拖动图谱，按需使用 Fit 适配全图 |
| ⑥ 看恢复动画 | 点击顶部“恢复 / Recovery”，使用页面主按钮及播放/前后步进控制 | 预设故障传播、定位、恢复、验证的交互动画；不会操作真实容器 |

顶栏 `EN / 中文` 可切换语言。样例中的两条故障可以来回选择比较；是否存在模型消息、经验或验证结果，均以该条记录实际内容为准。

想直接进入页面，也可打开 [样例 Execution](http://127.0.0.1:4173/execution?source=offline_fixture) 和 [样例 Knowledge](http://127.0.0.1:4173/knowledge-retrieval?source=offline_fixture)。Execution 没有选中记录时，先在顶部下拉框选择一条恢复记录。

体验结束，在样例终端按 **Ctrl+C**。只看样例，到这里即可。

## 三、准备真实业务演示环境

真实演示使用独立的 Vikunja 任务管理应用及 PostgreSQL 数据库。需要 Docker Desktop，使用 **Linux containers**，并等待引擎就绪。核对版本为 Docker 29.8.0、Compose v5.5.1。

### 1. 检查是否已有演示环境

在项目根目录执行：

```powershell
.\.venv-nexent\Scripts\python.exe -m scripts.prepare_vikunja_demo
```

这一步只检查。如果已经部署过本版本，保留原容器和卷，跳到下一节启动。其他目录的同名环境须先核对归属，不要覆盖或删除。

### 2. 首次部署，仅做一次

只有不存在演示容器和卷时，才依次执行下面命令。每条成功后再继续：

```powershell
$images = Get-Content integrations\vikunja\images.lock.json -Raw | ConvertFrom-Json
docker pull $images.images.postgres.digest
docker tag $images.images.postgres.digest $images.images.postgres.tag
docker pull $images.images.app.digest
docker tag $images.images.app.digest $images.images.app.tag
.\.venv-nexent\Scripts\python.exe -m scripts.prepare_vikunja_demo --deploy
```

脚本生成独立演示配置，不需要编写含密码的 `.env`。部署后访问 [Vikunja](http://127.0.0.1:18110)，确认应用能打开。

### 3. 启动已有容器

如果两容器已运行，跳过此步。否则先启动数据库并检查：

```powershell
docker start reops-vikunja-demo-postgres-1
docker exec reops-vikunja-demo-postgres-1 pg_isready -U reops_demo -d reops_vikunja_demo
```

显示 `accepting connections` 后再启动应用：

```powershell
docker start reops-vikunja-demo-app-1
```

### 4. 启动 ReOps

打开三个独立 PowerShell 终端，每个都先进入项目根目录，按顺序执行并保持打开：

| 终端 | 执行命令 | 作用 |
| --- | --- | --- |
| A | `powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1 -Part monitor` | 8021：监控及恢复后台 |
| B | `powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1 -Part api` | 8020：模型配置与证据后台 |
| C | `powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1 -Part web` | 5174：评审操作网页 |

终端 A 会创建独立的演示账号和测试任务，先核对真实读写基线，再等待网页操作。默认账号与你在 Vikunja 手动注册的账号独立。
若希望在自己的 Vikunja 演示账号中查看同一批任务，终端 A 改用下面命令，按提示输入已注册的账号及密码：

```powershell
.\.venv-nexent\Scripts\python.exe -m scripts.run_vikunja_workbench --serve --paused --login
```

不要把密码放进命令或文件。两种监控命令二选一。

打开 [真实工作台](http://127.0.0.1:5174/workbench?source=real)，右上角选择“本地连接 / Local connection”。左侧应出现 Vikunja 业务目标。首次使用没有故障历史是正常状态。

## 四、配置真实模型，可选

如需观察实际模型对话，先安装 Git，并在项目根目录补装固定提交的 Nexent SDK：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Model
```

然后在网页操作：

1. 打开顶部 [API](http://127.0.0.1:5174/api) 页面，新增服务。
2. 填写名称、提供商、实际模型 ID、公共 HTTPS API base 和自己的 Key。接口需要兼容 OpenAI chat / models。
3. 保存服务，点击“设为当前”，再点击连接测试，确认当前服务已验证。
4. 返回工作台，准备下一节的演示。

API base 的格式示例是 `https://api.example.com/v1`，此占位地址不能直接使用。本版不接受任意本机或内网地址。
**连接测试只读取模型列表，不发送聊天请求。** 模型是否参与某次处理，请以 Execution 中实际保存的请求、回复和状态为准；没有配置模型时，固定恢复流程也可以独立运行，但不会产生模型回复。

Windows 把 Key 保存在当前用户的系统凭据管理器；项目内只保存公开配置元数据。服务重启后需重新测试，执行批准与会话不会自动恢复。不要向评审人员传递自己的 Key、凭据或 runtime 目录。

## 五、实际演示一次故障与恢复

下面的停库操作由操作者在自己的独立演示环境执行。只查看样例时无需操作。

### 1. 开始监控并确认范围

在工作台选择 Vikunja，展开“授权范围与后果 / Authorization scope & consequences”，阅读页面说明。
点击 **“开始监控与自动处理 / Start monitoring & automatic handling”**，等待准备检查完成。
确认页面显示监控已启用、已授权，并且当前健康为正常。按钮不可用或检查失败时，先核对应用和数据库，不要开始停库。

本次批准针对固定演示目标，最多8小时、3次故障、两次至少间隔60秒；每次按数据库→SQL检查→必要时应用启动→业务验证处理。
当前运行的应用不会被无条件重启。模型分析需要已验证的 API，并按页面范围限制轮次和输出预算。以当次页面显示的范围及剩余额度为准。

### 2. 只停止演示数据库一次

确认健康和授权后，在另一个 PowerShell 终端执行：

```powershell
docker stop reops-vikunja-demo-postgres-1
```

也可以在 Docker Desktop 只停止同名 postgres 容器。**不要停止整个容器分组，不要点 Delete，不要同时停止 ReOps 的三个终端。** 然后回到 ReOps 网页，保持页面可见。

### 3. 观察处理过程

工作台发现新故障后，会出现本轮记录，并按当前分析和阅读进度在 Execution 与 Knowledge 之间衔接：查看分析、检索已有经验、回到同一执行记录、展示最终知识更新。首次运行没有可匹配经验是正常结果。

后台恢复不等待前端动画。若没有自动跳页，点击左侧本轮故障，再点“查看执行记录 / Inspect execution”，手动进入同一条记录即可，不必再停一次数据库。

在 Execution 中重点查看：

| 区域 | 如何操作 | 看什么 |
| --- | --- | --- |
| 顶部恢复记录 | 核对或选择刚才产生的记录 | 目标、时间、结果是否属于本轮 |
| 左侧时间线 | 点击检测、决策、执行、验证等事件 | 各步骤的实际状态和证据；选中历史步骤时可暂停跟随 |
| 右侧对话 | 查看并按需展开消息；向上滚动查看历史 | 实际模型请求、回复及步骤上下文；“回到最新 / Back to latest”可恢复跟随 |
| 底部工具交互 | 展开固定工具、HTTP、SQL等交互 | 执行动作与业务验证；它们与模型聊天分别展示 |
| 最终知识入口 | 记录保存后点击“查看更新后的知识图谱 / View updated knowledge graph” | 本次执行与验证如何关联到原图；只有实际保存的已验证经验才显示为新增经验 |

检索或更新动画默认4倍速，可选2倍、8倍；普通图谱及动画结束后可按原尺寸拖动，点击节点查看来源，按需 Fit 全图。手动切页或查看历史不代表重新执行故障或模型请求。

### 4. 确认演示结果

恢复是否成功，以本轮实际验证结果为准。检查 Execution 的最终状态和验证条目，再打开 [Vikunja](http://127.0.0.1:18110) 确认业务可访问。
使用自己账号启动监控时，可在同一账号下查看测试任务。故障时应用可能因数据库中断自行退出；是否允许启动应用，仍由本轮退出证据和批准范围决定。

失败、阻止或未知状态会保留在记录中，不等同于恢复成功。出现这些状态时先查看原因，不要连续重复停库或重放批准。
没有模型对话时先检查 API 是否验证、SDK是否安装以及本轮是否实际发起分析；模型列表测试通过不等于已经发生聊天。

### 5. 查看全局经验

点击顶部 **知识 / Knowledge**，或工作台 **全局知识 / Global knowledge**。
点击节点查看右侧记录和来源，沿来源链接回到对应事件或执行。
可比较不同故障的已验证经验与适用条件；只有记录中明确存在的复用关系才会展示。新增经验未保存或验证失败时，图谱仍可保留本次执行信息，不会把它当作成功经验。

## 六、结束演示

1. 在工作台点击 **“暂停监控与处理 / Pause monitoring & handling”**，确认监控暂停、自动处理权限关闭。
2. 分别在网页、API、监控终端按 Ctrl+C。只关闭浏览器不会停止后台。
3. 如需关闭 Vikunja，再按顺序停止应用和数据库：

```powershell
docker stop reops-vikunja-demo-app-1
docker stop reops-vikunja-demo-postgres-1
```

保留容器及卷，下次从“三、3”启动，不要重复首次部署。重新启动服务后，需重新测试模型并按需批准监控。

## 七、常见问题

| 现象 | 操作 |
| --- | --- |
| 样例页提示连接不可用 | 右上角切回“样例预览”，或重新打开本指南的样例链接 |
| 没有故障历史 | 新环境是空记录；先看内置样例，或在准备和批准完成后演示一次真实故障 |
| 找不到 Python、pnpm 或虚拟环境 | 检查工具已安装，在含本文件的目录执行安装脚本 |
| 镜像或依赖下载失败 | 检查联网和代理，保留错误；不擅自换用 latest 镜像 |
| `existing_demo_no_recreate_or_volume_reuse` | 已有环境，启动原容器，不重复 `--deploy` |
| 18110 打不开 | 检查演示数据库已就绪、应用已运行 |
| 8020 / 8021 / 5174 占用 | 使用已有同目录服务，或回原终端 Ctrl+C，不结束不明进程 |
| 网页打开，但API或工作台不可用 | 确认终端 A/B 正常；网页使用本包启动脚本，分别连接两个后台 |
| 只看到动画，没有真实恢复记录 | 确认使用5174的工作台“本地连接”，而不是4173样例或Recovery模拟页 |
| API测试通过，但无模型回复 | 核对SDK、模型ID及本轮实际调用状态；模型列表测试不是推理 |
| 恢复被阻止或失败 | 查看本轮Execution证据，排查后再决定下一步，不反复停库 |

需要核对压缩包完整性时，在包根目录执行：

```powershell
.\.venv-nexent\Scripts\python.exe -m scripts.check_release
```

本包不包含 ResearchLoop-AI 外部应用，其运行入口已隐藏。支持的真实演示对象为上述 Vikunja 环境。
交付验证已覆盖干净安装、离线测试、构建及隔离页面；新电脑首次容器部署、可选SDK从零安装、实际供应商聊天和真实恢复，仍须按本次运行结果确认。

## 八、鸿蒙手机端

工程与完整说明见[harmony/README.md](harmony/README.md)，接口见[mobile-v1](shared/harmony-api.md)。DevEco打开harmony目录，用本人的华为开发者账号为已登记设备配置调试签名并运行。源码不含作者签名或可通用安装的签名包。

手机的“本机监控”可独立使用：它实际读写本App的专用缓存，缓存清理后经检测和复查自动重建。页面保留“演示场景”标识，不读取其他应用私有目录。概览、故障、AI诊断从电脑端读取；历史模型回复与本机缓存修复分别展示，缓存恢复不调用AI。

### 连接电脑上的业务监控

先完成上文安装。使用同一私网的Windows电脑与手机，以下地址和子网必须替换为自己的实际网络；不要直接复制作者的地址。首次准备空的业务读模型可执行：

```powershell
.\.venv-nexent\Scripts\python.exe -m pip install -r requirements-mobile-access.txt -r requirements-harmony-pairing.txt
.\.venv-nexent\Scripts\python.exe -c "from workbench.b_store import BStore; from dashboard_api.store import Store; BStore('runtime/vikunja-b/state.sqlite3'); Store('runtime/dashboard-api.sqlite3')"
.\.venv-nexent\Scripts\python.exe -m scripts.configure_mobile_access --lan-ip <电脑私网IPv4>
```

初始化只建立表结构，不填入历史或作者数据。证书命令将专用查询凭据及私钥放入当前Windows账户凭据管理器，仅输出公开根证书位置。把该根证书通过可信方式安装到自己的测试手机；不要关闭证书校验。仅向当前私网授权8443端口，不对公网开放。

在原监控终端停止8021服务后，可选择一种入口：

```powershell
# 仅查看既有历史，不需要Docker；新环境显示空历史
.\.venv-nexent\Scripts\python.exe -m scripts.run_vikunja_workbench --history-read-only --lan-ip <电脑私网IPv4> --lan-cidr <私网CIDR>
# 或者，按上文准备并启动Vikunja后接通当前业务健康
.\.venv-nexent\Scripts\python.exe -m scripts.run_vikunja_workbench --live-monitoring --lan-ip <电脑私网IPv4> --lan-cidr <私网CIDR>
```

两个模式互斥，都不提供远程恢复控制。实时模式创建独立测试任务并持续采样，退出终端即停止监控。手机概览是Vikunja的当前业务健康，历史恢复成功不等于当前健康；数据过期或监控未连接显示未知。

另外打开终端运行私密配对窗口：

```powershell
.\.venv-nexent\Scripts\python.exe -m scripts.show_harmony_connection
```

手机点击“连接”扫码，核对自己的HTTPS地址后选择“连接并读取”。二维码带只读凭据，不录屏、不公开。凭据仅保存在App当前内存会话。首次空库没有故障或模型回复；可先体验本机缓存页，或按指南完成获准的真实业务流程后查看自己产生的记录。

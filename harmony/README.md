# ReOps 鸿蒙原生应用

ReOps 使用 ArkTS / ArkUI Stage 模型，包含概览、故障、AI诊断、本机监控四个页面。Bundle 为 `com.reops.mobile`，仅申请 INTERNET 权限。

## 页面与操作

| 页面 | 内容与操作 |
| --- | --- |
| 概览 | 读取电脑端 Vikunja 的业务健康与采样时间，查看历史故障统计及最近记录 |
| 故障 | 分页查看持久记录，进入详情，展开原 Incident/Trace、事件和来源；缺少 Run 时显示未导入 |
| AI诊断 | 展示同一故障已保存的模型回复、执行来源和业务验证，展开证据、经验与完整标识 |
| 本机监控 | 独立的手机本地缓存演示，无需电脑或Token；仅操作本应用专用演示文件 |

### 手机本地缓存演示

打开“本机监控”，首次点击“准备本机监控”。正常状态下点“清理缓存”，程序实际删除专用缓存，检测异常并在三秒复查后自动重建、重新读回验证。每轮异常最多一次自动重建，失败时不循环重试；离开页面取消待执行操作。

此页面明确标注演示场景，不读取其他应用数据，也不代表AI自主恢复。修复只作用于应用自身 `cacheDir` 中固定的测试文件。

### 连接远端业务

先按仓库根 README 启动受限HTTPS移动查询入口。在App右上角“连接”中填写服务根地址或使用“扫描电脑连接码”，核对地址后点击“连接并读取”。后台持续采样，App通过刷新读取最新缓存。没有新鲜采样时显示未知，历史恢复不代表当前健康。

- 正式产品不预置服务地址或Token；仅接受HTTPS，HTTP只允许回环测试。
- 专用只读凭据至少32字符，只在App当前会话内存；不写文件、Preferences、日志或启动参数。
- 扫码仅导入配置，不自动发请求。电脑连接码只在临时窗口内存，有导入有效期；不要截图、录屏或分享。
- 退出App或鉴权失效会清除会话；普通网络读取失败保留标注的上次数据，401/403清除受保护数据。
- 网络使用HarmonyOS RCP，校验证书、禁止重定向，连接/传输及总体截止为8秒。
- AI页展示已保存的真实诊断记录；浏览历史不会触发新模型调用或恢复操作。

接口契约见 [mobile-v1](../shared/harmony-api.md)。

## 构建与安装

需要 DevEco Studio、配套 HarmonyOS SDK 和本人的开发者调试签名。工程编译/目标版本为 `6.1.1(24)`，最低兼容为API20；已验证设备为Mate80/API26，其他设备须自行验证。

在DevEco打开本目录，选择default产品，配置本人的合法调试签名后运行到已登记设备。源码中的signingConfigs保持为空，发布包不含私钥、签名密码或通用可安装的签名HAP。

命令行构建在仓库根执行，先把 `REOPS_DEVECO_HOME` 设置为自己的DevEco安装目录：

```powershell
& .\harmony\scripts\build.ps1 -Studio $env:REOPS_DEVECO_HOME
```

默认输出未签名HAP到 `entry/build/default/outputs/default/`。未签名HAP不能直接安装到普通真机。`scripts.build_harmony_signed` 可复用已登记到当前Windows凭据管理器的本项目签名配置，正常/失败构建后还原源配置；不要同时在IDE编辑签名配置。

## 验证

在仓库根、已设置 `REOPS_DEVECO_HOME` 时执行：

```powershell
& "$env:REOPS_DEVECO_HOME\tools\node\node.exe" harmony/tests/contracts.cjs
& "$env:REOPS_DEVECO_HOME\tools\node\node.exe" harmony/tests/local-cache.cjs
```

客户端契约样例与文件IO异常测试在 `tests/`；测试数据不打入App资源。可选contractTest产品仅供明确标识的隔离测试，与default产品分开构建。

已安装正式包并连接USB时，设备ID须取自当次 `hdc list targets -v`。`scripts/verify_local_device.py` 在App中操作专用缓存并保存真机结果；`scripts/verify_real_device.py --frontend` 核对已连接的真实业务页面，期间保持App前台且不要同时操作手机。源码包没有作者的真实数据库、模型凭据或故障历史，首次连接空库可正常显示空状态。

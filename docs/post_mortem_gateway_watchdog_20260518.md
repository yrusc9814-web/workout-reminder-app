# Hermes Gateway 假死故障复盘与高可用架构升级

**Date:** 2026-05-17 至 2026-05-18

## 现象描述（Symptom）

Hermes Gateway 在运行过程中出现“Web/API 仍可用，但微信与钉钉不可用”的假死状态。

具体表现为：

- `api_server` 仍监听 `127.0.0.1:8643`，Web/API 层看起来正常。
- 钉钉 Stream WebSocket 与微信 iLink 长轮询在底层网络异常后中断。
- 主 Gateway 进程仍存活，因此进程级健康检查无法发现故障。
- `gateway_state.json` 未及时更新平台真实连接状态，仍保留旧的 `connected` 状态。
- 监控与 `gateway status` 出现“绿灯假死”：状态显示正常，但实际微信/钉钉收发能力已经瘫痪。

典型日志包括：

```text
dingtalk_stream.client: [start] network exception, error=no close frame received or sent
gateway.platforms.weixin: [Weixin] poll error (1/3): Server disconnected
```

## 根因分析（Root Cause）

### 1. 软件代码级：通信协程断连后缺少可靠自愈

钉钉 Stream 与微信 iLink poll 都属于长生命周期通信协程。

在底层网络出现异常时，例如：

- WebSocket 断开
- `no close frame received or sent`
- `Server disconnected`
- 长轮询连接被远端关闭

原有逻辑没有形成完整的“捕获异常 -> 标记断开 -> 指数退避 -> 重连 -> 恢复状态”闭环。

结果是平台通信能力退出或不可用，但主进程没有退出，造成服务部分失效。

### 2. 状态机逻辑级：主调度层越权写入 connected

原有 `gateway/run.py` 在 `adapter.connect()` 返回成功后，会由主调度层统一写入：

```text
platform_state = connected
```

这对同步服务，例如 `api_server`，是合理的。

但对钉钉 Stream 和微信长轮询这类异步通信平台并不准确。`adapter.connect()` 成功只能说明“任务已启动”或“资源初始化完成”，不能证明底层网络握手已经成功。

因此出现了状态机越权问题：

- 主调度层提前写入 `connected`
- Adapter 内部真实网络状态尚未建立
- 底层断连后主调度层无法感知
- `gateway_state.json` 与真实连接状态脱节

钉钉模块进一步暴露出一个生命周期耦合问题：移除 `_mark_connected()` 后，虽然避免了提前写入 `connected`，但也丢失了 `_running = True` 的副作用，导致 `_run_stream()` 协程启动后立即退出。

最终修复方式是显式拆分：

```python
self._running = True
```

用于生命周期控制，而 `connected` 状态只允许由真实连接探活逻辑写入。

### 3. 基础设施级：依赖临时 PowerShell 进程运行

在修复前，Gateway 依赖临时前台 PowerShell 进程链运行：

```text
powershell.exe -> python.exe -> python.exe
```

这带来基础设施级单点风险：

- PowerShell 窗口关闭会导致 Gateway 退出。
- 没有系统级自动重启能力。
- 宿主机重启后无法自动恢复。
- 计划任务失败时缺少稳定托管与接管流程。
- 临时进程与计划任务进程可能争抢 `8643` 端口。

因此，仅修复代码级断连并不足够，还必须将 Gateway 转为系统守护进程。

## 重构与解决路径（Resolution）

### 1. 引入指数退避重连

钉钉 Stream 主循环改造为非阻塞重连模型：

- 捕获 `asyncio.TimeoutError`
- 捕获 `TimeoutError`
- 捕获 `ConnectionError`
- 捕获 `OSError`
- 捕获兜底 `Exception`
- 使用 `asyncio.sleep()` 实现指数退避
- 初始退避 2 秒
- 最大退避 60 秒

断开后立即写入：

```json
"state": "disconnected"
```

重连成功后再写回：

```json
"state": "connected"
```

### 2. 建立 `manages_own_state` 状态边界

在平台 Adapter 上引入状态自理标识：

```python
self.manages_own_state = True
```

主调度层 `gateway/run.py` 修改为：

- 如果 Adapter 未声明 `manages_own_state`，保持原有行为。
- 如果 Adapter 声明 `manages_own_state=True`，主调度层只记录“Adapter 已启动”，不再写入 `connected`。
- `connected/disconnected` 状态完全交由 Adapter 内部真实网络事件驱动。

这避免了异步平台被主调度层提前标绿。

### 3. 为钉钉引入旁路 Watchdog 探活机制

由于当前 `dingtalk_stream` SDK 没有原生 `on_connect` 回调，无法直接依赖 SDK 事件。

通过阅读 SDK 源码确认：底层 WebSocket 成功建立后，SDK 会设置：

```python
self.websocket = websocket
```

因此在 `DingTalkAdapter` 内引入旁路 Watchdog：

- 每 2 秒检查 `self._stream_client.websocket`
- 判断 websocket 是否为 `OPEN`
- 首次确认打开后调用 `_on_stream_connected()`
- 写入 `dingtalk.connected`
- 如果后续 websocket 不再打开，则立即写入 `dingtalk.disconnected`

关键日志验证：

```text
[Dingtalk] Starting DingTalk stream client
[dingtalk] adapter started; runtime state managed by adapter
[Dingtalk] DingTalk stream connected
```

并确认 `gateway_state.json` 中：

```json
"dingtalk": {
  "state": "connected"
}
```

其 `updated_at` 与 Watchdog 连接日志时间毫秒级吻合。

### 4. 通过 Windows 计划任务实现守护与端口接管

为消除临时 PowerShell 单点风险，将 Gateway 注册为 Windows 计划任务：

```text
TaskName: HermesGatewayService
Trigger: AtStartup
Action: D:\hermes-agent\venv\Scripts\python.exe -m hermes_cli.main gateway run
WorkingDirectory: D:\hermes-agent
```

最终切换流程为：

1. 停止临时 Gateway 进程，释放 `127.0.0.1:8643`。
2. 通过 `Start-ScheduledTask -TaskName HermesGatewayService` 拉起后台守护进程。
3. 验证计划任务状态为 `Running`。
4. 验证 `8643` 由新 PID 监听。
5. 验证 `gateway_state.json` 中三平台均恢复 `connected`。

最终接管结果：

```text
HermesGatewayService: Running
127.0.0.1:8643: TcpTestSucceeded=True
OwningProcess: 11404
gateway_state.pid: 11404
api_server: connected
dingtalk: connected
weixin: connected
```

## 防范机制（Prevention）

### 1. 运行时自愈

本次改造后，钉钉模块具备以下自愈能力：

- 网络断开自动识别
- 状态文件立即标记 `disconnected`
- 指数退避重连
- WebSocket 恢复后自动标记 `connected`
- 主进程存活但通信断开的假死状态可被状态文件暴露

### 2. 状态机边界收敛

通过 `manages_own_state` 明确平台状态所有权：

- 同步服务由主调度层管理状态
- 异步长连接平台由 Adapter 自己管理状态
- 避免“任务启动成功”被误判为“网络连接成功”

### 3. 基础设施守护

通过 Windows 计划任务实现：

- 后台运行
- 开机自启
- 脱离临时 PowerShell 窗口
- 端口接管流程标准化
- 降低人为关闭终端导致 Gateway 下线的风险

### 4. 日志轮转

Gateway 转为后台守护后，日志会长期持续写入。

为避免：

- `gateway.log` 无限膨胀
- 磁盘被日志耗尽
- 日志检索变慢
- 故障排查时打开日志卡顿

下一步将把当前日志系统从按大小轮转升级为按天轮转：

```python
TimedRotatingFileHandler(
    when="midnight",
    interval=1,
    backupCount=30,
    encoding="utf-8",
)
```

目标效果：

- 每天自动生成独立日志文件
- 保留最近 30 天
- 自动清理更旧日志
- 保持 UTF-8 编码，兼容中文日志
- Gateway 长期后台运行时日志可控

## 结论

本次故障不是单点 bug，而是三层问题叠加：

1. 通信协程缺少断线自愈。
2. 状态机写入边界不清，导致监控假绿。
3. Gateway 依赖临时 PowerShell 前台进程，缺少系统级守护。

通过本次改造，Hermes Gateway 已完成从“临时前台进程 + 被动状态记录”到“后台守护 + Adapter 自主管理状态 + Watchdog 探活 + 自动重连”的升级。

后续重点是补齐日志轮转，并继续将微信长轮询状态机纳入同样的 `manages_own_state` 边界，确保所有异步平台都具备一致的自愈与可观测能力。

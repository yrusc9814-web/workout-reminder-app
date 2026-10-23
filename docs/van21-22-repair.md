# VAN-21 + VAN-22 合并修复

基线：GitHub `master@7192dcbac9d1517cfe306bbc9ac35e9fc8282b07`。
独立 `van21-22-candidate`，不修改正式数据库，不调用真实 AI 或通知。

## VAN-21 调用链和错误边界

正式 `/` 返回 `static/index.html`；当前聊天按钮调用 `/api/ai/chat`，经
`ai_service.call_ai_messages` 读取供应商响应。先确认对象、非空 `choices` 数组、
`message` 对象及非空字符串 `content`，错误返回 HTTP 502 和明确说明。
聊天文本本身无需是 JSON；字符串 `null` / `[]` 仍是合法聊天文本。

仍可访问的兼容入口：`/api/ai/import-plan` 和 `/api/ai/analyze` 的 prompt 分支
使用 `PlanGenerator`；`/api/ai/suggest-bilibili-video` 使用 `VideoRecommender`。
解析 JSON 后先验证对象，再使用对象方法。草稿校验覆盖模板 ID、动作引用、日期条目、
视频结构及组数/次数/时长类型，避免未校验值进入哈希集合或迭代。
视频建议的关键词、链接必须是字符串数组，不能以错误字段或空结果冒充成功。
非法模型输出返回 HTTP 422；供应商响应/传输错误返回 HTTP 502。

`/api/ai/analyze` 的 session 分支经 `SessionAnalyzer` 验证对象和已出现的
summary/adjustments/score 字段，映射上述业务错误。原有 session summary
接口继续保留本地摘要回退。AI 生成/分析不写入正式计划或触发通知。
未重写 AI provider、模型发现、配置存储或未调用的旧 helper。

## VAN-22 调用链和边界

调度脚本 POST `/api/notifications/send` → `NotificationService` → 通知适配器。
后端兼容提醒/待办 API 仍可访问。首页提醒开关保持 disabled、功能未开放。
成功回执、重试、去重与退出码见 [调度说明](reminder-scheduler.md)。

钉钉待办成功响应形状依据官方 SDK 的
[CreateTodoTaskResponseBody / CreatePersonalTodoTaskResponseBody](https://pkg.go.dev/github.com/alibabacloud-go/dingtalk/todo_1_0#CreateTodoTaskResponseBody)
定义，分别检查顶层非空字符串 `id` / `taskId`；没有调用线上服务验证送达。

## 验证方式与未覆盖项

复用已有 Python、Node/jsdom 依赖和测试 fixture。新用例先在隔离基线复现缺陷，
再由普通执行子代理运行模拟 AI、模拟通知、本机 HTTP fixture、临时 SQLite
和正式首页 JSDOM 定向回归，主代理检查 diff 并复跑关键测试。
不重复全量回归。外部网络由测试 fixture 禁止，key store 和数据库均为临时路径。

不声称真实模型输出质量、通知实际送达、Windows 原生任务计划程序/DPAPI、
真实 Chromium 渲染或浏览器 E2E 已验证。部分成功重试可能重复已成功渠道；
既有按计划去重记录不包含渠道与尝试详情，本轮不迁移或重解释历史活动记录，
历史误记成功时需明确指定 `force` 才会重发。数据库 schema 不变。

## 本轮定向结果

- VAN-21：143 个独立场景通过，1 个原有 Windows DPAPI 平台项跳过。
  新增异常结构测试最终共 96 项；初始 92 项在隔离基线为 64 failed / 28 passed。
  正式首页 AI 工作区 JSDOM、已有模型发现和兼容 API/session 场景一并回归。
  首次 VAN-19 loopback fixture 被沙箱拒绝绑定；仅对该文件在允许绑定的环境
  重跑，23 项通过，没有把环境失败计入产品通过。
- VAN-22：最终定向 60 passed / 116 deselected，退出码 0，覆盖业务回执、
  部分/全部成功、失败重试后成功再去重、兼容 API、tick 子进程与 Windows 包装入口。
  初始缺陷用例在基线为 28 failed / 15 passed；最终成功回执另按官方 SDK 形状校正。

两项分别 PASS；详细原始输出位于 candidate 同级 `van21-22-evidence/`。
后续 Git 收口仍需用户单独授权，本轮不 commit、不 push、不更新 Linear。

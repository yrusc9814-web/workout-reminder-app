# Claude Code + DeepSeek 完整执行计划

## 1. 执行模式

本任务对外是一项完整交付，不拆成需要用户逐轮确认的多个任务。Claude Code 内部按 Gate、清单和测试推进：

1. 建立基线与数据备份。
2. 完成 Gate 0–1 数据和状态机。
3. 完成 Gate 2 训练执行体验。
4. 完成 Gate 3 UI/UX、移动端和无障碍。
5. 完成 Gate 4 AI 闭环和必要架构清理。
6. 运行只读审查、全量测试和视觉验收。
7. 一次性提交最终结果。

规划是内部第一步，不是最终交付。除非命中明确 Stop Conditions，否则主代理必须自动进入下一 Gate。

## 2. 启动前检查

从 `workout-app` 目录启动 Claude Code，使本目录的 `CLAUDE.md` 和 `.claude/agents/` 被加载。

主代理首次操作：

- 读取 `CLAUDE.md`、`AGENTS.md`、最终联合审查报告和本计划。
- 记录 `git status --short`、当前分支和相关 diff。
- 判断工作树是否干净；禁止覆盖已有改动。
- 检查 Python、pytest、FastAPI、SQLAlchemy、Node 和浏览器能力。
- 复制 `workout.db` 到 `.tmp/backups/`，计算 SHA-256。
- 创建 `.tmp/claude-execution-state.md`。
- 检查 DeepSeek 是否真的可用，并记录实际模型 ID；不能只根据配置文件推测。

建议状态文件结构：

```markdown
# Execution State
- Baseline git status:
- Branch:
- DB backup:
- DeepSeek status/model:
- Current gate:
- Completed:
- Tests:
- Open issues:
- Next action:
```

## 3. 代理编排

### 主代理：Claude Code

职责：

- 决定领域模型和 API 契约。
- 维护 Gate 清单和状态文件。
- 只在接口契约稳定后并行派工。
- 检查子代理 diff，解决契约和集成冲突。
- 运行最终测试和视觉验收。
- 负责最终报告，不能把子代理结论直接当成事实。

### 并行工作代理（最多 2 个）

`workout-backend-data`：

- 所有权：`database.py`、`main.py`、`seed.py`、`ai_service.py`、`notification_service.py`、`adapters/`、后端测试和迁移文件。
- 任务：Gate 0–1 后端、Gate 4 AI 持久化和安全。
- 推荐模型：已配置时使用 DeepSeek coding 模型。

`workout-frontend-ux`：

- 所有权：`static/`、前端相关测试和视觉验收脚本。
- 任务：API 接入、错误状态、训练页、Dashboard、主题、移动端、可访问性。
- 推荐模型：Claude 主模型或可用的高质量前端模型。

并行前，主代理必须写出并冻结：

- 资源 ID 规则。
- Plan/WorkoutExercise/SessionRecord 关系。
- session start/update/resume/complete 请求与响应。
- 统计响应格式。
- error payload 规范。
- AI draft/import/feedback schema。

代理不得同时修改同一文件。API 契约变更必须通知主代理，由主代理同步另一侧。

### 顺序审查代理

两名工作代理完成并由主代理集成后，再运行 `workout-reviewer`：

- 只读，不修改文件。
- 优先使用 DeepSeek 做独立对抗审查。
- 检查数据丢失、幂等、外键、XSS、错误态、时区、通知重试和测试假阳性。
- 输出可复现证据和阻断项；主代理修复后重新审查一次。

## 4. Gate 0 — 数据止血与迁移基础

### 目标

任何后续功能都不能再破坏现有用户数据。

### 任务

- 将启动 seed 改成只初始化缺失记录，不覆盖已有用户行。
- 增加显式、可确认的“恢复默认数据”路径；先备份再执行。
- 设计并实现 Exercise、WorkoutExercise、SessionRecord 的正确引用。
- 迁移现有 265 条缺失引用的数据；无法可靠映射时保留快照并记录 migration warning，不能猜测。
- 开启 SQLite 外键并为关键唯一关系加约束。
- 引入可重复执行的 schema migration；优先 Alembic，若阶段性保留自定义 migration，必须有版本表、事务和回滚证据。
- 统一 timezone-aware UTC 时间戳和 Asia/Shanghai 业务日期策略。
- 默认运行地址收敛到 `127.0.0.1`。

### Gate 0 验收

- 在数据库副本中修改种子计划，重启两次后仍保留修改。
- migration 可重复执行且第二次不改数据。
- `PRAGMA foreign_keys=1`。
- 无新孤儿 SessionRecord。
- 正式数据库未被测试修改，备份可验证。

## 5. Gate 1 — 单一事实源与 API

### 后端

- WorkoutSession/SessionRecord 成为训练事实源。
- 同一计划最多一个活动 session。
- start 拒绝休息日、无效计划和重复活动 session。
- update 只接受当前计划动作；完成后拒绝 update。
- complete 幂等；重复请求返回同一结果，不新增日志。
- 提供 current/resume/cancel 接口。
- WorkoutLog 作为由 complete 产生的审计记录，具唯一约束。
- 统计按唯一 plan/session 计算，不能超过 100%。
- 废弃或重写 `/api/training/complete`，不得只把 `template_id` 改成字符串。
- 所有请求模型增加枚举、范围、非空和引用校验。

### 前端

- 删除易失的保存假象；所有 CRUD 调 REST API 并以响应刷新 state。
- JSON/AI 草稿使用单事务导入端点。
- 完成状态从 API/session 读取，不自行初始化为 pending。
- 启动时显示 loading；空库显示 empty；API 失败显示 error/offline。
- 示例数据只能在显式 demo 模式使用。
- 移除硬编码“后端数据源已连接”。
- 所有非 2xx 进入统一错误处理和恢复路径。

### Gate 1 验收

- 动作、模板、计划、视频、JSON/AI 导入刷新和重启后存在。
- 完成训练后刷新，日历和统计一致。
- 对同一 session complete 两次只记一次。
- 断开后端不出现示例计划或假连接状态。
- API 集成测试和浏览器持久化测试通过。

## 6. Gate 2 — 训练执行体验

- 状态机：`ready → active → resting → active → paused → active → completed/cancelled`。
- 计时型动作有可暂停、可恢复的倒计时。
- 每组完成后进入可配置休息倒计时。
- paused/resting 时禁用不合法操作。
- 刷新后从 current session 恢复动作、组数和计时。
- 视频 URL 转换和嵌入要安全处理；失败时明确退回外链。
- 删除永久 `about:blank` 的空播放器。
- 完成摘要由后端 session 生成；失败不得显示成功。
- AI 不可用时训练流程完整可用。

Gate 2 验收：刷新续练、暂停恢复、计时/休息、跳过、取消、完成和视频失败路径全部有测试和真实页面证据。

## 7. Gate 3 — UI/UX、移动端和无障碍

### Dashboard

- 保留今日 Hero、3 个真实指标和一条本周路线。
- 管理中心降级为导航入口。
- 完整月历只保留在月计划页。
- 删除硬编码 23/35/42 仪表盘、假“全部⌄”、WELCOME BACK 和开发术语。
- 1440×900 总高不超过 1350px。

### 主题

- 内容卡实底；背景照片只放 Hero 或降到装饰级。
- 浅色 muted 普通文本对比度 ≥4.5:1。
- 浅深主题只交换语义 token；组件级 dark 覆盖控制在必要范围。
- 品牌色保持同色相。

### 反馈和导航

- 15 个 alert、6 个 confirm、1 个 prompt 全部替换。
- banner/inline error/toast/dialog 各司其职。
- 使用 hash 或轻量路由记录当前页面，支持刷新和后退。
- nav 使用 `aria-current`；切页和 dialog 有焦点管理。

### 移动与无障碍

- 375px 首屏直接显示今日计划和主 CTA。
- 辅助工具和状态在移动端默认折叠。
- 触控目标 ≥44px。
- 日历/周计划有明确移动交互，不依赖无提示横向宽表。
- 图表有文本摘要、角色和非颜色信息。
- JS 平滑滚动也遵守 reduced-motion。

## 8. Gate 4 — AI 闭环与架构

- 前端安全处理 `draft:null`。
- AI import、analysis、feedback 使用 Pydantic schema。
- 畸形模型输出拒绝进入正式数据。
- 草稿导入单事务，部分失败整体回滚。
- feedback、rating、ai_feedback 真正落库。
- 完成训练后异步生成小结，超时/失败不阻塞完成。
- 建议可生成 draft 并应用到下次计划。
- 在契约稳定和全量测试通过后，拆分 main.py 并去除 ai_service 重复校验。
- 通知统一到 NotificationService；失败可重试，成功才去重。

## 9. 安全与数据注意事项

- 修复 JSON 导入预览未转义动作名称的 DOM XSS。
- 所有外部/AI/数据库字符串进入 innerHTML 前转义，优先使用 textContent/DOM API。
- Webhook URL、token 和 API key 在日志、异常和响应中脱敏。
- 不把 `.env`、密钥、正式数据库备份提交到 Git。
- 远程访问必须显式开启并鉴权；默认本地回环。
- 测试不得真实发送通知或调用模型。

## 10. 验证矩阵

### 自动测试

- 全量 pytest。
- JavaScript 语法检查。
- migration up/idempotency/rollback 测试。
- API 模型和状态转换测试。
- 前端持久化、错误态、XSS 测试。

### 视觉与交互

至少覆盖：

- 1440×900：Dashboard 浅色、深色。
- 375×812：Dashboard 浅色、深色。
- 今日训练：计时动作、resting、paused、complete。
- 月计划与设置页。
- 后端离线、空库、AI 未配置、视频失败。
- reduced-motion 和键盘操作。

证据保存到 `.tmp/visual-qa/`，记录视口、主题、页面和时间。没有真实截图不能把视觉标为 PASS。

## 11. 长任务持续运行规则

- 不使用低 `--max-turns` 的 print 模式执行整项任务；优先使用交互会话。
- 每个 Gate 更新 `.tmp/claude-execution-state.md`。
- 上下文压缩或进程中断后，使用同一目录的 `claude --continue` 或 `claude --resume <session-id>` 恢复，并从状态文件继续。
- 不要求用户重新描述任务或逐阶段确认。
- 普通测试失败不构成暂停理由；修复后继续。
- 不使用 `--dangerously-skip-permissions`。写入工作区可使用正常权限或 `acceptEdits`，外部/破坏性动作仍需审批。
- 不使用无限 Stop hook 强迫运行；它可能造成循环。持续性通过状态文件、Gate 清单和 resume 实现。

## 12. 最终交付格式

最终回答必须一次性包含：

- 完成的 Gate 和功能。
- 关键设计决策。
- 修改文件与迁移。
- 测试命令和精确结果。
- 视觉证据路径。
- 数据备份和回滚方法。
- DeepSeek 实际参与的任务与模型；不可用时明确写明。
- 未完成项、原因和风险。
- Git 状态；未获授权不得 push。


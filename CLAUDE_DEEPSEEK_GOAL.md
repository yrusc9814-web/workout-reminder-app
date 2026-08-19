# 可直接交给 Claude Code 的 Goal 指令

你是本任务的主执行代理。请在 `workout-app` 范围内完整修复《运动提醒项目最终联合审查报告》中列出的数据、Session、前端、训练体验、视觉、移动端、无障碍、AI、通知和安全问题。

开始前必须读取并遵守：

- `CLAUDE.md`
- `AGENTS.md`
- `docs/运动提醒项目-最终联合审查报告-2026-07-10.md`
- `docs/CLAUDE_DEEPSEEK_EXECUTION_PLAN.md`
- `docs/DEEPSEEK_INTEGRATION.md`

## 工作方式

这是对外的一次完整 Goal，不是需要用户逐轮指挥的多轮任务。你可以在内部建立计划、Todo 和 Gate 清单，但完成计划后必须立即实施，不要停下来等待用户说“继续”。从 Gate 0 自动推进到 Gate 4，直到 Definition of Done 全部满足，或命中 AGENTS.md 中明确的 Stop Conditions。

主会话由 Claude Code 负责总体设计、API 契约、集成和最终验证。最多同时运行两个工作子代理：

1. `workout-backend-data`：数据库、迁移、Session、API、统计、通知、AI 持久化和后端测试。DeepSeek 已通过兼容网关配置时，优先让该代理使用实际 DeepSeek coding 模型。
2. `workout-frontend-ux`：前端 API 接入、训练页、Dashboard、主题、反馈、移动端、无障碍和前端测试。

两个工作代理完成并由主代理集成后，再顺序运行只读 `workout-reviewer`。最终 reviewer 优先使用 DeepSeek；不要同时运行 reviewer 和修改代理。子代理不得生成更多子代理。主代理 + 两个工作代理是允许的最大并发规模。

如果 DeepSeek 未真实配置或不可调用，不要假装它参与。按照 `docs/DEEPSEEK_INTEGRATION.md` 使用外部 DeepSeek 审查提示，或在最终报告中明确标记 DeepSeek 未执行。DeepSeek 的建议必须由主 Claude 用代码、测试和当前数据库证据复核。

## 强制执行顺序

1. 记录 dirty worktree 基线，保护用户现有改动。
2. 备份正式数据库；所有测试和迁移演练使用 `.tmp` 副本。
3. Gate 0：停止 seed 覆盖、修复引用、启用外键、建立安全迁移和统一时区。
4. Gate 1：建立单一事实源、Session 幂等、真实统计、CRUD/导入落库、明确 loading/empty/error/offline。
5. Gate 2：计时、休息、暂停/恢复、刷新续练、视频失败降级、可信完成摘要。
6. Gate 3：Dashboard 减法、内容卡实底、主题 token、统一反馈、移动端、键盘/ARIA/reduced-motion。
7. Gate 4：AI schema、事务导入、feedback/ai_feedback 落库、训练后小结，以及在契约稳定后进行架构清理。
8. 运行只读对抗审查，修复阻断项，重新跑全量测试和视觉验收。

## 非协商约束

- 禁止 reset、checkout 或覆盖用户已有改动。
- 禁止用正式 `workout.db` 跑测试。
- 禁止真实发送钉钉通知或调用外部 AI。
- 禁止静默吞错、假成功和隐式示例数据 fallback。
- 禁止只把 `template_id` 改成字符串来掩盖完成端点问题。
- 禁止在 Gate 0–1 未通过前优先做视觉或 AI 扩展。
- 禁止安装全局依赖、提交密钥、输出完整 webhook。
- 禁止未经授权 push、开 PR 或修改远端。
- 不使用 `--dangerously-skip-permissions`，不设置可能无限循环的 Stop hook。

## 持续运行

在 `.tmp/claude-execution-state.md` 保存 Gate、Todo、测试和下一步。上下文压缩或进程中断后，读取该文件并继续；恢复会话时使用 `claude --continue` 或原 session ID，不要求用户重新发任务。普通测试失败、实现困难或单次工具失败都不是停止理由。

## 完成定义

只有以下条件全部满足才可结束：

- Gate 0–4 必须项完成。
- 全量测试和新增关键集成/E2E 测试通过。
- seed 不覆盖用户数据，无孤儿 SessionRecord，complete 幂等，统计真实。
- CRUD、JSON/AI 导入和训练状态经刷新/重启保持一致。
- 后端离线、空库、AI 未配置、通知失败有诚实且可恢复的体验。
- 桌面浅/深、375px、训练执行页、键盘和 reduced-motion 有真实验收证据；工具不可用时标记 PARTIAL。
- 最终一次性报告修改、迁移、测试、截图、备份、回滚、DeepSeek 实际参与情况和剩余风险。

不要只输出计划。现在开始执行，并持续到完成定义满足或出现明确阻塞。


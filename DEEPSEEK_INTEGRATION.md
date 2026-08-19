# DeepSeek 与 Claude Code 协作说明

## 1. 关键事实

Claude Code 的项目记忆使用 `CLAUDE.md`，项目自定义子代理放在 `.claude/agents/*.md`。子代理 `model` 默认接受 Claude 别名、完整模型 ID 或 `inherit`。

因此，不能仅在代理文件里写“DeepSeek”就认为 DeepSeek 已接入。要让 Claude Code 内部子代理真正使用 DeepSeek，需要已经配置一个 Claude Code 可访问、兼容 Anthropic Messages API 的模型网关，并让该网关接受对应 DeepSeek 模型 ID。

## 2. 推荐模式

### 模式 A：DeepSeek 已通过兼容网关暴露

在用户环境中配置，不要写入仓库：

- `ANTHROPIC_BASE_URL`：兼容网关地址。
- `ANTHROPIC_AUTH_TOKEN`：网关 token。
- `ANTHROPIC_CUSTOM_MODEL_OPTION`：网关接受的 DeepSeek 模型 ID。
- 可选 `ANTHROPIC_CUSTOM_MODEL_OPTION_NAME`：显示名称。

启动后用 `/model` 或 `/status` 验证模型确实可选，并通过一次最小只读任务核对返回的实际 model ID。不要只看环境变量。

如果希望所有子代理都走 DeepSeek，可以临时设置 `CLAUDE_CODE_SUBAGENT_MODEL`；但本任务更推荐按调用为 backend-data 和 reviewer 指定 DeepSeek，frontend 继续使用 Claude，以避免所有代理被强制路由到同一模型。

仓库内的子代理文件保持 `model: inherit`，保证没有网关时仍可用。主代理在确认网关后，通过当次 Agent 调用的 model 参数或本地未提交配置指定实际 DeepSeek 模型。

注意：若使用 LiteLLM，Anthropic 官方文档特别警告 PyPI 版本 1.82.7 和 1.82.8 曾被植入窃取凭据的恶意代码。不要安装或运行这些版本；如果曾使用，应移除并轮换凭据。

### 模式 B：DeepSeek 作为外部审查器

如果 DeepSeek 不能作为 Claude Code 子代理模型：

1. Claude Code 完成 Gate 0–1 或全部实现后生成精确 diff、测试结果和数据库验证摘要。
2. 把 `docs/DEEPSEEK_REVIEW_PROMPT.md` 与这些证据交给 DeepSeek。
3. DeepSeek 只做只读审查，不直接操作正式数据库或密钥。
4. Claude Code 主代理逐条验证 DeepSeek 结论，修复成立的问题。
5. 最终报告写明 DeepSeek 是“内部子代理”还是“外部只读 reviewer”。

## 3. 模型分工

- Claude Code 主代理：架构决策、契约、集成、冲突解决和最终验收。
- DeepSeek backend-data：数据库、状态机、API 边界、幂等和迁移实现/审查。
- Claude frontend-ux：页面、交互、可访问性、响应式和视觉验收。
- DeepSeek reviewer：对抗审查数据丢失、XSS、时区、通知重试、假阳性测试。

DeepSeek 返回的代码或建议不自动可信；主代理必须结合当前代码、测试和数据库证据复核。

## 4. 凭据与安全

- 不把 DeepSeek、Anthropic 或网关密钥写入 `.env.example`、CLAUDE.md、agent 文件或日志。
- 不在子代理提示中粘贴真实数据库、用户隐私和 webhook。
- 不将网关配置提交到 Git。
- 若网关不可用，使用模式 B，不要修改生产代码来绕过认证。


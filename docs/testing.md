# 测试执行与可信度边界（VAN-25）

## 执行方式

在项目根目录使用 `requirements-runtime.lock` 与 `requirements-test.lock` 对应的 Python
测试环境，以及已有 Node/jsdom。VAN-25 不自动下载或安装任何依赖。本次实际验证环境为
Python 3.12、Node 24、jsdom 26.1；未声称验证其他版本组合或 Windows。
仓库没有托管 CI 配置；本轮工程门禁是本地可重跑检查，不把缺少 CI 配置记为通过。

项目已有 `node_modules/jsdom` 或正常 Node 模块搜索路径可解析 jsdom 时：

```sh
python3 -m pytest -q -ra
```

复用项目外已经准备好的依赖时，设置两个通用入口（以下路径是占位符）：

```sh
NODE_BINARY=/path/to/node \
WORKOUT_NODE_MODULES=/path/to/existing/node_modules \
python3 -m pytest -q -ra
```

`NODE_BINARY` 不设置时从 PATH 找 node；`WORKOUT_NODE_MODULES` 指向 node_modules
目录而非 jsdom 包目录，不设置时采用标准 Node resolution。旧 `VAN13_DOM_DEPS`、
`VAN16_DOM_DEPS`、`VAN18_DOM_DEPS`、`VAN23_NODE` 不再作为依赖入口。
缺少 node/jsdom 会明确失败，不静默跳过、不尝试安装。
本机 fake provider/通知 HTTP fixture 需要允许绑定 loopback 临时端口；若宿主沙箱禁止绑定，
应报告环境错误并在允许本机端口的执行环境重跑这些测试，不改成 skip 或产品失败。

## VAN-26 工程基线门禁

运行依赖的直接版本见 `requirements.txt`，完整运行闭包见 `requirements-runtime.lock`；
pytest/httpx 等测试增量见 `requirements-test.lock`。锁文件对应本机 Python 3.12/macOS
环境，未声称 Windows 或其他平台组合已验证。仓库没有托管 CI，本轮门禁均为本地可重跑检查。

若宿主已配置 Git hook，可通过现有 Lefthook 二进制显式注入，不安装或复制二进制：

```sh
LEFTHOOK_BIN=/path/to/existing/lefthook \
GIT_OPTIONAL_LOCKS=0 \
git hook run pre-commit -- --no-auto-install --no-stage-fixed --skip-lfs --no-tty
```

candidate 没有 Lefthook 配置时，结果应标记为 `NOT_CONFIGURED/NOT_RUN`；hook 返回 0
只说明调用链没有阻塞，不能当作项目检查通过。

可直接运行单个 DOM 场景：

```sh
node tests/van25_current_page_behavior.js skip-failure
```

Python API 测试使用 pytest 临时 SQLite、临时 key store，并清除继承的 AI/通知配置；
套件禁止对外建立 socket 连接（允许本机 fake provider），不连接正式数据库。
DOM 测试使用 fetch fixture，不请求真实 AI 或通知。Node 子进程继承上述隔离设置。
F01、VAN-23 生成日志位于 candidate 的 `.tmp`，其他历史专项日志位于临时目录。

## 当前页面的有效证据

- `test_api.py`：保留原迁移幂等、备份元信息、SQLite backup API integrity 和 seed
  幂等的全部断言；四个函数名称现在各自唯一，均可收集执行。
- `test_test_integrity.py`：防止测试文件顶层/测试类定义重名覆盖，确认 `/` 实际返回
  `static/index.html`，并用临时变异页面禁用跳过处理器、丢失模板绑定或错误绑定，
  证明相应 DOM 门禁会失败。
- `test_frontend_behavior.py` 的六个全页场景：空计划不伪造训练事实；跳过失败不推进且
  原样重试；最后跳过先 update 再 complete；complete 失败保留会话且重试不重复 update；
  连点只发送一次 update，确认后才推进；模板从后端 ID 精确绑定，显式 null 与缺失 ID
  均保持未绑定（即使已有同动作模板）。训练操作来自正式按钮的 click 事件，模板断言
  观察完整页面加载后的日历计划，不复制转换算法。
- 复用 F01 完整页的 loading/data/empty/error 和重试门禁；VAN-17 完整页已有日期归属、
  计划保存失败/延迟、回读失败重试、刷新恢复及会话快照测试，不另造同类训练回归。
- 复用 VAN-18 当前方案/计划流程、VAN-19/20 完整页设置和 AI 工作区 fixture 流程、
  VAN-23 FileReader → 预览 → 确认导入 → 回读/刷新、VAN-24 重复动作身份及次数约束。
- 其他提取当前 index.html 函数的单测仍是局部补充，不能替代完整页事件测试。

原 `test_frontend_behavior.py` 中基于旧 harness 的十个测试不再执行逻辑副本；
适用于当前页面的训练、保存失败、目标日期、模板/动作快照和导入确认断言由上述当前
页面回归承接。旧专属表单、旧 `/api/plans/{id}` 保存流程、旧恢复按钮不再被冒充为
当前 UI 行为。恢复预览/确认/备份与视频失败的后端契约继续由现有 API 回归验证。
旧的 `frontend_behavior_harness.js` 与 `static/app.js` 已移除；当前页面回归只读取并执行正式的
`static/index.html`，避免测试继续把无消费者的旧实现当作产品入口。

## 历史与平台专项（不计入当前页面通过数）

`test_static_contract.py` 只保留正式首页和启动入口的静态契约；已删除针对退休 `app.js`
的源码探针，避免跳过测试继续掩盖无消费者残留。正式首页的无硬编码 YouTube 检查默认执行，
没有降低 URL 规则。

`test_e2e_playwright.py` 是保留的 legacy Playwright 流程，默认 skip，未改写成新的
E2E。`--legacy-e2e` 仅供非 macOS 主机主动运行历史诊断；macOS 始终 skip 此旧入口，
真实 Chromium 验收必须使用已批准的 headed runner，不能从此测试直接启动 headless。
VAN-25 未启动浏览器/服务，不声称浏览器渲染、真实计时或跨平台 E2E 通过。

`test_ai_chat_provider_models_and_dpapi_key_store` 是真实 Windows DPAPI 的存储集成测试，
仅 Windows 执行；macOS/Linux 显式 skip。local-demo 的 provider/chat 断言单独保留为
跨平台测试，VAN-19 fake key-store 契约与保存失败保护继续运行。
未验证 Windows 真实加解密、重启持久化、系统绑定和损坏密文；fake store 通过不能替代它。

本次修改仅做实施验证；独立审核是后续单独步骤，没有启动审核代理。

## 首轮实施验证记录（返工前历史结果）

基线 `0e60c97b48e7ac6d9b3fe96813417aa286d5808e`，独立 `van25-candidate`。
收集 334 项；分组执行合并后 303 个独立测试通过，31 项明确跳过：29 个历史源码探针、
1 个旧 E2E、1 个非 Windows 的原生 DPAPI 集成项。

首次完整执行在受限沙箱中为 284 passed、31 skipped、6 failed、12 errors；
这 18 项均因已有 loopback HTTP fixture 绑定端口被宿主拒绝。
随后仅在允许绑定本机端口的环境中重跑 VAN-19 模型/提醒脚本测试及测试完整性门禁，
33 passed（含重叠复验和新增的缺失依赖报错检查），没有残留测试失败。
原始输出保存在 `.tmp/van25-regression.txt` 与 `.tmp/van25-local-fixtures.txt`，
不把首次环境失败改记为通过，也不把 skip 计入当前页面覆盖。

`git diff --check` 通过；正式前后端实现均无 diff。
原 dirty 工作区和 `van24-candidate` 的 HEAD、status、受保护文件集合与 SHA256 一致。
未安装依赖，未修改正式数据库，未调用真实 AI/通知，未 commit/push/更新 Linear。
该轮 PASS 后在只读核对中发现混合探针被跳过和空模板断言缺口，状态改为
CLOSEOUT BLOCKED；以上是历史执行结果，不能代替本轮最终定向验证。


## 最小返工与最终一致性证据

本轮仅改测试与本说明：拆分正式首页/旧前端 URL 检查；新增完整页模板绑定、
显式 null 与缺失 ID 不猜测绑定的断言；新增两种临时变异页面的负向控制。
没有修改生产实现、安装依赖或新增浏览器 E2E。

定向范围为 `test_static_contract.py`、`test_frontend_behavior.py`、
`test_test_integrity.py`、F01 完整页，以及恢复收集的四个迁移/备份/seed 测试；
另单独运行旧 `app.js` 的 URL 检查，确认拆分后原规则仍生效。
不重跑其他完整回归，前述历史通过数不冒充本轮完整执行结果。

本轮最终定向日志：`.tmp/van25-final-targeted-frozen.txt`、`.tmp/van25-final-legacy-url.txt`。
最终源码清单：`.tmp/van25-final-candidate-sha256.json`，覆盖所有 Git 跟踪文件及非忽略
的新增文件（包括未改的生产代码），不含 `.git` 和忽略的临时运行产物。
该清单在最终定向验证前保存，验证后逐项比对路径集合和 SHA256，保证没有源码漂移。
验证回执 `.tmp/van25-final-validation.json` 记录清单、两个日志的哈希、退出码及工作区
保护比对结果；这些忽略目录中的证据不自动列入 Git 提交。

Windows 原生 DPAPI 及旧浏览器 E2E 的覆盖边界保持上文所述；JSDOM + 模拟请求不能
证明真实浏览器/实际后端连通、布局、真实计时、浏览器刷新持久化或 Windows 加解密。
原 VAN-25 要求未增加完整浏览器 E2E；此次仅恢复和补足有效断言，不以跳过降低要求。
独立审核仍未执行，本轮由主代理检查最终 diff 和定向结果。

## VAN-26 工程清理说明

VAN-26 删除了无生产消费者的 `static/app.js`、旧逻辑副本 harness 及对应默认跳过探针；
当前首页 URL/DOM smoke 与删除结果记录在 `van26-evidence`，不改写上述 VAN-25 历史执行事实。

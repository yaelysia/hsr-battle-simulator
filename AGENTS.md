# AGENTS.md - HSR 工作区入口

每次都用简体中文回复。

本项目构建可审计的《崩坏：星穹铁道》战斗模拟器。目标是基于固定数据来源完成战斗配置、状态转移、快照、结算、replay 和来源审计，最终供外部推演器查询与操作。

## 主线与事实来源

当前主线：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/
```

唯一规则来源链：

```text
turnbasedgamedata-main -> compiler/lowering -> Canonical IR -> Combat Core
```

旧 v7 和 `model_pack_v3_0` 仅可作对照，不是兼容目标，也不能成为 v8 runtime 依赖。优先级固定为：

```text
最终成品完整性 > 内核干净程度 > 来源可追查 > 验证可重复 > 旧版兼容
```

## 按需读取

禁止新线程默认通读全部阶段计划和历史报告。只读当前任务需要的最小集合：

- 新线程定向：`hsr_v075_baseline_clean/hsr/CODEX_HANDOFF.md`
- 架构或共享内核修改：`simulator_v8_clean_core/ARCHITECTURE_BOUNDARY_CONTRACT.md`、`FORBIDDEN.md`
- 阶段实施：当前阶段执行卡及其直接依赖，不读相邻阶段卡
- 规划、验收或验证改造：`simulator_v8_clean_core/docs/AGENT_WORKFLOW_AND_VALIDATION.md`
- 查文档归属：`simulator_v8_clean_core/DOCUMENTATION_INDEX.md`
- 查历史决策：先在计划、报告和 `docs/archive/` 中按关键词搜索，不全量读取

当前状态只在 `CODEX_HANDOFF.md` 维护，本文件不再复制 P1-P8 历史。

## 架构红线

- runtime 只能读取 Canonical IR、数据卡 IR 和已装配的正式输入。
- raw TBGD、TextMap 和机制文本只能进入 compiler/lowering/discovery/审计或 UI 展示层。
- 禁止使用旧 v7、旧 model pack、观测伤害和手工答案补规则。
- 禁止为角色、怪物、光锥、遗器、关卡或路线在核心系统写专属特判。
- 禁止复活 `BattleSimulator`、`SimulatorRuntimeAdapter`、`_legacy_effects`、`action_ctx`。
- 未知、缺来源、缺条件、缺目标、缺公式或缺事件 payload 必须 blocked，并保持 state unchanged。
- `audit_only`、`discovered_only`、`blocked` 和 placeholder 不得产生 mutation。
- `source_trace` 只用于审计，不能作为 runtime 行为输入。
- 每个 mutation 必须能追溯到真实 Canonical IR 节点和 TBGD 来源。
- settlement 必须由执行路径原生生成，不能从日志事后反推。
- UI 只能展示内核事实并提交选择，不能计算技能可用性、目标、资源、伤害或状态规则。
- 外部推演器像玩家一样查询、选择和读取结果，不负责敌方 AI 或第二套战斗逻辑。
- 角色卡、怪物卡、光锥卡、遗器卡是内容来源；构筑装配器负责组合，runtime 不理解 raw 构筑规则。
- 动作归属可行动单位数据卡，目标规则归属 action definition。
- 角色召唤物归属角色卡；怪物召唤物优先复用怪物卡，并额外记录 owner/summoner 和生命周期。
- 不按角色名、怪物名、技能名、固定 ID、固定文件名、固定 hash 或观测答案驱动正式逻辑或主验证选样。

详细禁令以 `FORBIDDEN.md` 为准；发生冲突时选择更严格、来源更真实的解释。

## 工程方式

- 从第一性原理判断问题，不因用户或旧文档已有结论而跳过代码事实。
- 非必要不扫描整个项目。结构问题先用 CodeGraph；字面文本、路径和日志先用 `rg`。
- 修改前检查调用链和影响范围；优先根因修复，不为旧接口污染新内核。
- 信息无法从工作区发现且会改变关键规则时，暂停并询问。
- 新依赖、下载外部代码或创建新 uv 环境必须先取得用户同意。
- 优先复用现有 uv 环境；禁止未经允许覆盖或新建环境。
- 不回滚用户修改，不提交无关文件，不使用破坏性 Git 命令。
- 手工编辑使用 `apply_patch`。
- 运行产物写入 `/tmp`，不提交缓存、`.pyc`、`__pycache__` 或大体积临时输出。

## 阶段协作

- 大型目标拆成严格顺序阶段，一个线程一次只实施一张已确认执行卡。
- 执行卡详细目标、验收、红线和验证只保存在文件中；对话不复述整张卡。
- 执行线程只能提交 `ready_for_review`，不能自称完成、勾 checklist、提交 Git或自动进入下一阶段。
- 验收线程必须检查生产代码、调用链、负例和真实 evidence，不能只看 `ok=true`。
- 验收一次性汇总当前可发现的阻断；修复线程只读差量问题，不重新展开全部背景。
- 验收通过后由验收线程勾选对应项并提交检查点；纯规划和说明文档默认不单独提交。
- 并行只允许依赖明确、写集合互斥且从同一检查点创建独立 worktree 的阶段。

完整阶段协议见 `docs/AGENT_WORKFLOW_AND_VALIDATION.md`。

## 验证成本

验证分四层：

1. `fast`：`compileall`、本阶段聚焦验证、`git diff --check`。
2. `direct`：只跑本次调用链直接触达的现行契约回归。
3. `catalog`：全量来源或目录覆盖；仅在来源、lowering、目录准入变化时运行。
4. `full`：里程碑聚合；只在重大架构修改、阶段聚合或用户明确要求时运行。

默认只跑 `fast + 必要 direct`。历史阶段验证是当时的 evidence，不自动属于活跃回归。旧脚本若携带过时假设，应迁移仍有效的谓词或退役，而不是让新代码兼容旧验收。

重验证必须串行、低优先级、限峰值并输出到 `/tmp`。默认禁止写完整 Canonical IR、RuleBook、coverage、fidelity 或 transition dump；确需大产物时使用显式开关。

- 验证治理改动必须在同一阶段替换并删除真实重复路径，同时量化构建次数、耗时和峰值内存；只新增注册表、调度器、缓存层或“验证验证器”不算治理成果。
- 第一次复用应局限在一个已确认的重调用链内。至少两个独立真实消费者证明边界相同后，才允许提取跨阶段通用框架。
- 聚焦验证直接证明生产契约或真实目录结果，不再为大型验证工具另写同等规模的元验证。验证代码总量默认不得因纯治理而净增长。

## 提交

- 阶段验收成功后提交一个范围干净的检查点。
- 验收未通过或仍有未获用户接受的语义阻断时不提交完成检查点。
- 工作区存在无关修改时忽略并保留，不混入当前提交。
- 文档、报告和 checklist 的状态必须诚实区分 `executable`、各类 gap、`deferred` 与 `not_proven`。

瘦身前的完整入口和历史经验保存在：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/archive/AGENTS_PRE_SLIM_2026-07-24.md
```

只在追溯历史决策时按关键词读取，不能重新作为默认上下文。

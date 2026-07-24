# Agent Workflow and Validation Protocol

本文档定义 v8 的执行、验收和验证成本协议。它按需读取，不进入每个线程的自动上下文。

## 1. 目标

验证必须同时满足：

- 能发现真实代码和语义错误。
- 能证明来源、执行、settlement、replay 和 fail-closed 边界。
- 成本随本次改动范围增长，而不是随历史阶段数量增长。
- 历史 evidence 可追溯，但不会成为永久重跑负担。

严格性来自准确谓词和真实调用链，不来自脚本数量。

## 2. 单一事实位置

- 当前状态：`CODEX_HANDOFF.md`
- 长期架构：`ARCHITECTURE_BOUNDARY_CONTRACT.md`
- 禁止行为：`FORBIDDEN.md`
- 阶段目标：对应 task plan 的唯一 checklist
- 单阶段实施：对应 execution card
- 执行 evidence：`ready_for_review` 报告
- 验收结论：checklist、checkpoint 和 Git 提交

禁止在 `AGENTS.md`、文档索引和多个报告中重复维护当前阶段状态。

## 3. 线程职责

### 规划线程

- 根据当前代码、来源和依赖设计阶段目标。
- 一张卡只覆盖一个阶段。
- 目标写清完成后系统具备的能力、明确不做的相邻范围。
- 验收写清允许通过、必须失败和对应证据。
- 先区分真实 source gap、lowering gap、admission gap、implementation missing 和 validation gap。
- 不要求执行线程为当前来源不存在的机制伪造 executable 正例。

### 执行线程

- 只读核对当前卡和直接代码事实。
- 事实偏差改变目标或验收时停止并交回规划线程。
- 只实施当前卡，不提前进入下一阶段。
- 修改后检查生产代码，不以验证脚本变绿代替自审。
- 最终状态只能是 `ready_for_review`。
- 不勾 checklist、不提交 Git、不复述整张执行卡。

### 验收线程

- 先看 diff、生产调用链和数据边界，再选择验证。
- 检查通用性、扩展性、来源真实性、失败原子性和验证谓词质量。
- 一次性汇总当前可发现的阻断，避免逐轮挤出问题。
- 报告只作为 evidence 索引，不能代替代码复核。
- 通过后更新 checklist，并提交范围干净的检查点。

## 4. 执行卡最低内容

每张执行卡只保留一套完成清单，并包含：

- 阶段背景和前置检查点。
- 详细阶段目标。
- 本阶段只做。
- 本阶段不做。
- 架构归属和禁止做法。
- 目标与证据映射。
- 结构化通过谓词。
- negative matrix。
- gap、blocked、deferred 和 not-proven 口径。
- 拟改生产文件和验证文件。
- `fast`、`direct`、条件触发验证。
- 明确不跑的验证及原因。
- IO、内存和输出体积限制。
- `[ ]` 完成项。

对话发起只需要执行卡路径、基线提交和范围约束，不粘贴卡片全文。

## 5. 缺口分类

任何机制先判断：

1. raw TBGD 是否有结构化来源。
2. lowering 是否完整投影。
3. RuleBook 是否保留执行所需类型字段和审计来源。
4. runtime 是否通过通用系统消费。
5. validation 是否使用准确的结构化谓词选样。

分类：

- `executable`：真实来源、mutation、settlement、source audit 和 replay 闭合。
- `source_gap_blocked`：raw 来源确实不存在，验证 blocked/state unchanged。
- `lowering_gap`：raw 有来源但 IR 未完整投影。
- `admission_gap`：IR 有来源但未准入执行。
- `implementation_missing`：已准入来源缺少正确 runtime consumer。
- `validation_gap`：生产路径可能完整，但当前验证没有正确证明。
- `deferred`：用户明确调整优先级，尚未执行。
- `not_proven`：没有证据，不能解释成通过或失败。

`ok=true` 不得覆盖内部 gap；聚合必须继承分阶段缺口。

## 6. 四层验证

### Fast

每次修改默认运行：

- 触达 Python 包的 `compileall`。
- 当前阶段聚焦验证或最小测试。
- `git diff --check`。

目标是快速发现语法、局部契约和格式错误。

### Direct

只运行与本次生产修改存在调用链或数据契约关系的现行回归：

- reducer 改动：原子提交、before 冲突、replay。
- target 改动：query-submit、目标基数、空集合和失败三态。
- status 改动：生命周期、概率、callback、source audit。
- scheduler/timeline 改动：阶段、队列、行动值和前进保证。
- summon/wave 改动：出生、关系、清理、波次生命周期。
- RNG 改动：事件身份、选择账本和 replay。

执行卡必须说明为什么该回归与当前调用链直接相关。

### Catalog

用于证明完整来源或内容目录：

- 来源清单和指纹变化。
- lowering 或定义目录变化。
- RuleBook 目录索引和冲突处理变化。
- 正式目录 admission 或 startup 变化。

要求：

- 一次读取来源后复用。
- 按批次处理，峰值不随目录线性增长。
- 不默认写完整 Canonical IR 或 RuleBook。
- 输出集合摘要、缺口矩阵和少量样本。
- 未执行时标记 `not_proven`，不能由 fixture 替代。

### Full

只在以下情况运行：

- 里程碑最终聚合。
- 共享内核大规模重构。
- source/lowering 全局语义变化。
- 用户明确要求。

Full 不是小阶段默认提交门。

## 7. 历史验证生命周期

现有阶段脚本必须逐步归类：

- `active_contract`：仍表达当前生产契约，可作为 direct 回归。
- `catalog_audit`：重型来源或目录证明，只按触发条件运行。
- `historical_evidence`：只证明旧检查点，不再默认执行。
- `superseded`：谓词已被新验证完整替代，保留归档说明后退役。
- `invalid`：依赖过时或错误语义，不能通过修改生产代码迁就。

迁移规则：

- 保留仍有效的谓词，不保留旧脚本结构本身。
- 新验证应共享 fixture、source inventory 和 RuleBook 构建。
- 同一轮完整 lowering 最多一次。
- 旧脚本失败时先判断契约是否仍有效，再决定修测试还是修生产。

## 8. 资源约束

- 所有重验证串行执行，使用低 IO/CPU 优先级。
- 输出写入 `/tmp`。
- 默认只写 summary、matrix、负例和抽样审计。
- 大产物必须有显式开关，默认关闭。
- 不并行构建多个完整 RuleBook。
- 来源缓存只能是验证优化，生产代码不能依赖 `/tmp` 或验收产物。
- 缓存键至少包含来源指纹、lowering 版本和影响语义的配置。
- 缓存损坏、键不匹配或来源变化必须 fail-closed 并重建。

## 9. Token 协议

- 常驻 `AGENTS.md` 只保留稳定红线。
- 当前状态只在 `CODEX_HANDOFF.md` 维护。
- 执行卡只写文件一次，对话不重复全文。
- 新线程只读当前卡和直接依赖。
- 执行汇报限制为：状态、变更范围、验证结果、遗留 gap、报告路径。
- 验收汇报限制为：结论、阻断、已验证范围、未验证范围。
- 命令原始日志不粘贴到对话；保存到 `/tmp`，只读取 summary。
- 修复轮只发送差量阻断，不重新讲完整项目背景。
- 历史经验按关键词从 archive 和 checkpoint 检索。

## 10. 并行和模型分工

- 同一工作区不并行写代码。
- 独立阶段只有写集合互斥、依赖图明确且基于同一检查点时才能使用独立 worktree。
- 新共享机制、架构和验收使用强推理模型。
- 现有契约下的数据卡扩面、机械投影和固定矩阵可使用成本更低的模型。
- 低成本模型不能自行修改目标、放宽验收或解释未知机制。

## 11. 提交边界

阶段检查点只包含：

- 本阶段生产代码。
- 本阶段验证。
- 对应 execution card、报告和 checklist 更新。

不混入：

- 无关 UI 草稿。
- 相邻阶段预实现。
- 临时产物。
- 仅为旧接口兼容的污染。

纯规划和说明文档默认随最近一次相关检查点提交，除非用户明确要求独立提交。

## 12. 当前验证治理待办

当前仓库已有大量阶段验证。后续治理按以下顺序推进：

1. 建立机器可读 validator registry，记录分类、触达域、资源等级和替代关系。
2. 提取共享的来源 inventory、紧凑 RuleBook 和 fixture 构建入口。
3. 为目录验证增加批处理和聚合证明。
4. 建立统一 `fast/direct/catalog/full` 命令入口。
5. 迁移现行谓词后，将旧聚合移出默认回归。

治理阶段不能改战斗语义；若迁移时发现生产缺陷，单独记录并按对应机制修复。

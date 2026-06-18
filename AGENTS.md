# AGENTS.md - HSR 工作区入口目录

每次都用简体中文回复。

本工作区目标是构建一个严谨的《崩坏：星穹铁道》战斗模拟器，用于在不打开游戏的情况下设定敌我双方、战斗环境和路线输入，并得到尽可能与游戏一致的完整战斗过程、快照和结算结果。

## 当前主线

当前主线是 v8 clean core：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/
```

v8 是新的 TBGD-first 重写基线。旧 v7 不是兼容目标，只能作为参考、对照和回归验证来源。

v8 事实来源固定为：

```text
turnbasedgamedata-main -> TBGD compiler -> Canonical IR -> Combat Core
```

项目优先级固定为：

```text
最终成品完整性 > 内核干净程度 > 来源可追查 > 验证可重复 > 旧版兼容
```

旧版兼容不是目标。旧 v7、旧 model pack、旧 CLI、旧 JSON、旧 Python API 都不能阻碍 v8 形成干净内核。

## 工作区目录

- `turnbasedgamedata-main/`
  - 星穹铁道 TurnBasedGameData 数据库。
  - v8 规则来源必须能追溯到这里。

- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/`
  - 当前新模拟器主线。
  - 新机制、新框架、新验证优先在这里实现。

- `hsr_v075_baseline_clean/hsr/simulator_v7_7/`
  - 旧模拟器与旧验证基线。
  - 只作参考和数值对照，不作为 v8 runtime 依赖。

- `hsr_v075_baseline_clean/hsr/model_pack_v3_0/`
  - 旧 model pack。
  - v8 不以它为规则事实来源。

- `hsr_v075_baseline_clean/hsr/live_validation_reports/`
  - 阶段检查点报告。
  - 有意义的结构或机制变更需要新增或更新报告。

- `hsr_v075_baseline_clean/hsr/validation_outputs_v*/`
  - 版本化验证输出。
  - 不要把不同阶段输出混到同一个无版本目录。

## 必读文档

v8 当前只保留少数高密度长期文档，避免文档膨胀影响索引和上下文检索。

优先读：

1. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/README.md`
2. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/PROJECT_GOALS.md`
3. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/FORBIDDEN.md`
4. `hsr_v075_baseline_clean/hsr/live_validation_reports/v8_tbgd_first_clean_core_v0_200.md`
5. `hsr_v075_baseline_clean/hsr/live_validation_reports/v8_constraints_checkpoint_v0_202.md`

只在需要对照旧行为时读：

1. `hsr_v075_baseline_clean/hsr/CODEX_HANDOFF.md`
2. `hsr_v075_baseline_clean/hsr/simulator_v7_7/ENGINE_ARCHITECTURE_v7_0.md`
3. `hsr_v075_baseline_clean/hsr/live_validation_reports/foundation_audit_layer_v0_75.md`
4. `hsr_v075_baseline_clean/hsr/live_validation_reports/simulator_workflow_audit_v0_74.md`
5. `hsr_v075_baseline_clean/hsr/model_pack_v3_0/MANIFEST.yaml`

## v8 硬约束摘要

详细红线见：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/FORBIDDEN.md
```

核心约束：

- runtime 只能读取 Canonical IR，不能直接读取 TBGD raw schema。
- TBGD raw schema 只能进入 compiler/lowering/discovery 层。
- 不允许使用 `model_pack_v3_0` 补齐 v8 规则。
- 不允许复活 `BattleSimulator` 作为 v8 核心对象。
- 不允许引入或复活 `SimulatorRuntimeAdapter`、`_legacy_effects`、`action_ctx`。
- 不允许为了旧 CLI、旧 JSON、旧 compiled case、旧 Python API 污染 v8 内核。
- 不允许角色、敌人、遗器、关卡、路线硬编码特判进入核心系统。
- 不允许用观测伤害、旧模拟器输出、手工答案作为规则输入。
- 不允许从日志事后反推 settlement。
- 不允许只记录 applied term，不记录 skipped term。
- 不允许跳过未知 opcode 后仍标记为 supported。
- 不允许 `audit_only` 被当成 executable。

## v8 审查红线

每次例行审查、结构回正或新增机制时，必须按以下红线检查，不能只看验证是否绿：

- 任何 runtime `Mutation` 都必须能反向追溯到 Canonical IR 中的真实 TBGD 机制节点，例如 action definition、ability binding、ability phase、ability task、effect、condition、formula、damage emission、status definition。
- 只有 `source_trace` 不等于来源正确；必须确认 source trace 指向的 IR 节点本身不是为了 runtime 方便伪造出来的占位。
- `derived`、`audit_only`、`discovered_only`、`blocked`、placeholder 只能生成 process-only settlement，不能产生状态 mutation。
- 缺少真实来源时，runtime 必须显式 blocked，并保持 state unchanged；不能为了让 smoke case 可跑而 fallback 到旧推导或默认执行。
- Canonical IR 必须诚实表达 TBGD 中发现的事实；禁止为了补 runtime 输入而制造不存在的规则事实。
- 每个新增可执行机制都必须有 negative validation：证明缺少真实来源、unsupported condition、unsupported target、unsupported formula 时不会假执行。
- 每个新增 mutation 类机制都必须至少抽一条样例，从 mutation metadata 反查到 settlement，再反查到 Canonical IR，再反查到 TBGD source path/evidence。
- 验证样例必须优先按结构化谓词选择，例如 opcode、coverage_status、source_mode、target_mode、payload 可执行性；禁止按角色名、固定 action id、固定文件名、固定 hash 选择主样例。
- 旧验证如果因为来源边界变严而失败，优先升级验证输入到真实来源链路；禁止为了旧 smoke 继续保留假执行路径。
- 审查结论必须区分“字段完整 / replay 通过”和“机制来源真实 / 语义正确”。前者不能替代后者。
- 每个阶段必须要回头检查一遍本次修改是否正确，不要给后续审查纠偏添加压力。
- 每次阶段汇报必须说明：当前做到哪里、距离最小可用战斗纵切还缺什么、距离完整复刻还缺哪些大模块。

## 快照与结算目标摘要

详细目标见：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/PROJECT_GOALS.md
```

每个动作最终必须产生完整 `BattleTransition`，至少包含：

- 动作输入。
- before snapshot。
- after snapshot。
- target resolution。
- trigger windows。
- state mutations。
- process events。
- rng events。
- settlement。
- coverage 状态。

所有状态变化必须通过 `Mutation` 表达。

最终必须满足：

```text
before snapshot + action input + Canonical IR + RNG events + mutations == after snapshot
```

settlement record 必须能追溯到 mutation，或明确标记为 process-only event。

## v8 当前验证命令

在 `hsr_v075_baseline_clean/hsr` 下运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_200 --output-dir validation_outputs_v0_200
```

当前 v0_200/v0_202 期望：

- compileall 通过。
- validation 输出 `ok=true`。
- static checks 通过。
- snapshot replay 通过。
- v8 runtime 不引用旧 simulator、旧 model pack、legacy adapter、`action_ctx`。

## 旧 v7 对照基线

只在需要确认旧数值或旧行为时使用 v7。

旧 C0-C8 参考目标：

- route trace：8
- queued transition：2
- log：172
- settlement：148 / 148 valid
- Tribbie：`4393.00559968331`
- Seele skill：`115919.63539530325`

Seele 旧值已知高于观测 `109262`，不要手工修正数值。差异必须通过来源、公式、buff/debuff、窗口顺序和 ledger 定位。

## 工程规则

- 非必要不要读取整个项目；优先读取与当前任务直接相关的文件。
- 文件查找优先限制在工作区内，不要全盘找同名文件。
- 结构性代码问题优先用 CodeGraph；文字、日志、路径搜索优先用 `rg`。
- 修改要从根源修复；如果小修补会加重结构债，应选择更干净的结构性改动。
- 信息不足且无法从仓库发现时，先提问，不要自行假设关键规则。
- 新依赖必须先征得用户明确同意。
- Python 依赖优先考虑已有 uv 环境；禁止未经允许创建新的 uv 环境。
- `npx`、`npm install`、`pip install`、`curl | sh`、`git clone` 等会下载、安装或执行外部代码的操作，必须先征得用户明确同意。
- 观测战斗伤害只能作为验证数据，不能作为模拟输入。
- 有意义的结构或机制变更要新增或更新 `live_validation_reports/`。
- 验证输出放进版本化 `validation_outputs_v*/` 目录。
- 不要提交 `__pycache__`、`.pyc` 或临时缓存。

## 提交规则

- 每个可验证结构阶段建议提交一次检查点。
- v8 代码检查点不要混入无关文件。
- `AGENTS.md` 只有在用户明确要求维护项目入口说明时才提交。
- 如果工作区里存在用户未提交修改，不要回滚；与当前任务无关则忽略。

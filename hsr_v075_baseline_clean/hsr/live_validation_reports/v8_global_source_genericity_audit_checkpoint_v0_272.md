# v8 v0_272 Global Source And Genericity Audit

## Scope

本阶段做全局机制来源与通用性审查，不新增遗器、光锥、敌方 AI、波次系统或新角色卡。

审查重点：

- runtime 是否读取 raw TBGD、TextMap、旧 v7 或 model pack。
- runtime 是否按角色名、技能名、固定 action id、固定 hash 执行机制。
- 本该共用的机制是否仍被拆成特殊路径。
- engine convention 是否被伪装成 TBGD 来源。
- blocked / audit-only / discovered-only 来源是否可能产生 mutation。
- 每类 mutation 是否有 source audit policy。

## Findings Fixed

- 修复 `validate_v0_258` 普通 DoT 主样例选择器。
  - 旧逻辑要求来源文件等于 `Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json`。
  - 新逻辑按结构化谓词选择：`damage_formula_family=dot`、`event=OnPhase1`、`attack_type=DOT`、emission/callback/task 都 executable、且存在可绑定动态数值。
  - 这避免了普通机制验证依赖固定文件名。

## Source Alignment

新增 `source_alignment_matrix_v0_272.json`。

当前结论：

- `db_backed`: 6 项。
  - buff/debuff 普通状态生命周期。
  - queue priority。
  - damage scaling basis。
  - ordinary DoT formula。
  - event listener alias。
  - target mode resolution。
- `engine_convention_allowed`: 4 项。
  - timeline AV formula。
  - ultimate energy after use。
  - kill energy gain。
  - bounce live-target policy。

这些 engine convention 没有被标成 TBGD 来源。后续如果 TBGD 中 admission 到明确常量或规则来源，需要替换当前 convention。

## Genericity Audit

新增 `genericity_audit_matrix_v0_272.json`。

当前通过项：

- buff/debuff 共享普通 unit status 生命周期。
- damage family 统一走 DamagePacket / DamageSourceFrame / ledger policy。
- event dispatch 使用统一 listener record shape。
- queue window family 使用统一 admission / ordering / blocked dependency。
- dynamic value 只能从 StatusInstance 或 DynamicValueStore 带 trace 进入可信路径。
- runtime 主路径未发现角色名、固定技能 ID、raw TBGD 读取或旧 runtime 依赖。

## Mutation Source Policy

新增 `mutation_source_policy_matrix_v0_272.json`。

当前 source audit policy 覆盖：

- action timeline/resource。
- natural timeline。
- damage/toughness/break/status/effect。
- status callback/event dispatch。
- queue enqueue/dequeue/child action。

静态扫描 runtime `Mutation(` 创建点未发现无 policy source。

## Blocked No-Mutation Samples

新增 `sample_blocked_no_mutation_cases_v0_272.json`。

覆盖：

- `custom.event` 无真实事件来源。
- `wave.monster` 无波次系统。
- unknown event alias。

三类都保持 snapshot unchanged 且 mutation count 为 0。

## Remaining Explicit Dependencies

- `timeline_av_formula`: 仍使用 engine convention，需要 admission 到 TBGD 时间线常量后替换。
- `ultimate_energy_after_use`: 当前 post-use 规则可审计，但仍等待 raw TBGD 常量/规则来源 admission。
- `kill_energy_gain`: 当前击杀回能可审计，但仍等待 raw TBGD 常量/规则来源 admission。
- `bounce_live_target_policy`: 当前由角色卡策略与可 replay RNG 承载；角色文本解释仍在角色卡构建阶段完成。
- `OnCustomEvent`: 等待真实 custom event 来源。
- `OnWaveMonster`: 等待波次系统。

## Minimum Usable Battle Slice

距离最小可用战斗纵切仍缺：

- 完整角色面板装配：晋阶、行迹、装备、光锥、遗器。
- 至少一套稳定队伍/敌人/路线配置格式。
- 敌方 AI 或可替代的敌方路线输入。
- 波次进入/结束。

## Full Replication Gaps

距离完整复刻仍缺：

- 大量角色卡人工解释与验证。
- 光锥、遗器、套装、星魂全量机制。
- 敌方 AI、召唤物、assistant、特殊模式。
- 更完整的事件监听、队列优先级和特殊回合窗口。
- 观测日志只作为对照验证，不能作为规则输入。

## Validation

已单独运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_audit_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_245 --output-dir /tmp/hsr_v8_audit_v0_245
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_257 --output-dir /tmp/hsr_v8_audit_v0_257
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_258 --output-dir /tmp/hsr_v8_audit_v0_258
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_264 --output-dir /tmp/hsr_v8_audit_v0_264
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_266 --output-dir /tmp/hsr_v8_audit_v0_266
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_270 --output-dir /tmp/hsr_v8_audit_v0_270
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_271 --output-dir /tmp/hsr_v8_audit_v0_271
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_272 --output-dir /tmp/hsr_v8_audit_v0_272
git diff --check
```

结果：

- `compileall`: pass
- `validate_v0_225`: `ok=true`
- `validate_v0_245`: `ok=true`
- `validate_v0_257`: `ok=true`
- `validate_v0_258`: `ok=true`
- `validate_v0_264`: `ok=true`
- `validate_v0_266`: `ok=true`
- `validate_v0_270`: `ok=true`
- `validate_v0_271`: `ok=true`
- `validate_v0_272`: `ok=true`
- `git diff --check`: pass

# v8 Full Core Audit Checkpoint v0_239

## Scope

本次是 v8 当前模拟器全量回头审查，不新增新机制。

审查范围：

- runtime 边界：`core/`、`systems/`、`rules/`
- TBGD lowering / coverage 边界：`tbgd/`
- 当前代表性验证：source audit、actionability/trust、break family、event dispatch foundation
- 当前事件分发最新路径：v0_238

## Checks Performed

结构红线扫描：

- runtime 未发现 `simulator_v7_7`、`model_pack_v3_0`、`SimulatorRuntimeAdapter`、`_legacy_effects`、`action_ctx`。
- runtime 未发现 `json.load` / `open()` / `read_text()` 直接读取 TBGD raw。
- runtime 未发现 `ConfigAbility`、`ConfigCharacter`、`ShowStanceList`、`param_list[0]` 等 raw schema 推断主路径。
- runtime 未发现网络、外部命令、时间或随机依赖。
- 固定角色 / action / hash 主要仍存在于早期历史验证和 smoke 工具，不在 `core/`、`systems/`、`rules/` 主路径。

结构路径审查：

- `CombatExecutor` 仍先做 target/resource/plan preflight，失败动作不 open timeline、不扣资源、不执行 damage/status mutation。
- `DamageSystem` / `ToughnessSystem` / `BreakSystem` 的 mutating path 仍经过 executable IR 与 source audit。
- `EventDispatchSystem` 已是 action/status/hit/break listener record 的统一入口。
- `RuleBook` 只索引 Canonical IR，不读取 raw TBGD。
- `QueueSystem` 仍未被 runtime 调用；保持未 admission，不计入当前可信机制。

## Findings Fixed

### listener no-match record lacked audit shape

问题：

`EventDispatchSystem.dispatch_event()` 在 event alias 可解析、但没有匹配 listener 时，会产出 process-only `listener_match` record；该 fallback record 之前没有稳定 `order_key` 和 `event_alias`。

影响：

- 不会污染状态。
- 但违反 v0_238 的“所有 listener match records 都可排序、可审计”约束。
- 后续 global / being-hit / per-hit listener 接入时可能导致 no-match 路径不可追查。

修复：

- fallback no-match record 现在写入：
  - `order_key`
  - `event_alias`
  - `blocked_category`
- `dispatch_blocked()` 也补齐统一 listener metadata。
- `validate_v0_238` 新增 `listener_no_match` 负例，覆盖该路径。

## Current Remaining Boundaries

这些不是本次漏修问题，而是需要后续机制 admission 后才能执行：

- `QueueSystem`
  - 当前无 runtime 调用。
  - 需要 queue opcode / interrupt / immediate / extra-turn 规则来源 admission。

- per-hit / being-hit / global listener mutation
  - v0_238 已有 per-hit event payload 与 alias matrix。
  - 缺少后续 intent 承接：追击、反击、队列、受击监听目标/效果 admission。

- Ability `OnHit`
  - 当前仍按 action damage step 后执行，不声称等价 per-hit trigger。
  - 完整 per-hit task execution 需要后续 hit context 与 task scheduling 收束。

- AOE / blast 数值完整度
  - 仍标记 structural-only / target-group multiplier not implemented。
  - 需要确认多目标倍率、分组、multi-hit 语义。

- early historical validators
  - v0_203-v0_206 等早期 smoke 仍含固定 ID。
  - 它们不作为当前机制 trust 主路径；当前主路径验证使用结构化谓词样例。
  - 若以后要长期保留历史验证，应单独清理或降级为 legacy smoke。

## Validation

运行目录：

```text
hsr_v075_baseline_clean/hsr
```

已运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_audit_v0_225_final
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_227 --output-dir /tmp/hsr_v8_audit_v0_227_final
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_235 --output-dir /tmp/hsr_v8_audit_v0_235_final
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_237 --output-dir /tmp/hsr_v8_audit_v0_237_final
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_238 --output-dir /tmp/hsr_v8_audit_v0_238_final
git diff --check
```

结果：

- compileall passed
- v0_225 `ok=True`
- v0_227 `ok=True`
- v0_235 `ok=True`
- v0_237 `ok=True`
- v0_238 `ok=True`
- v0_238 new `listener_no_match` negative case passed
- `git diff --check` passed

## Conclusion

当前可立即修复的问题已修复。

本次未发现 runtime 主路径存在旧依赖、raw TBGD 读取、观测数值补规则、blocked/audit-only 节点产生 mutation、或失败动作污染状态的问题。

后续继续推进机制时，优先级应是：

1. queue / interrupt / immediate / extra-turn admission。
2. per-hit listener 与追击/反击 intent。
3. enemy AI / enemy action selection。
4. multi-hit / blast / bounce 数值语义。

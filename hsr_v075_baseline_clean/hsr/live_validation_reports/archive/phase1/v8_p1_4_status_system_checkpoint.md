# v8 P1-4 状态系统主体阶段检查点

## 本阶段完成

本检查点按 `P1_4_STATUS_SYSTEM_TASK_PLAN.md` 推进状态系统主体，但不宣称 `P1-4-DONE`。当前完成的是可安全落地的第一批底座能力：

- 定义并落地 `source_stack_key`，让同一来源重复施加、不同来源共存/阻断具备稳定身份。
- `AddModifier` 的 stack admission 从字段读取提升为可执行判定：
  - `MaxLayer` 只 admission 当前 `RuleEvaluator` 可证明的 fixed / dynamic hash / postfix 表达式。
  - `LayerAddWhenStack` 必须是可执行正整数。
  - 缺少或 unsupported stack 来源时 blocked / process-only，不产生 stack mutation。
- 同源重复施加可执行 stack：
  - 只更新目标 `status_details` 中的 stack 字段。
  - 不重复追加 `unit.statuses`。
  - 达到上限时 clamp，并记录 `stack_capped=true`。
- 真实 negative `LayerAddWhenStack` 的 `AddModifier` 接入 stack reduce：
  - 已 admission `LayerAddWhenStack=-1` 的 executable AddModifier。
  - 2 层降到 1 层只更新 status detail stack。
  - 1 层降到 0 层走统一 remove lifecycle，移除 `statuses` 和 `status_details`，并触发 remove callback events。
  - 缺 existing status detail 时 blocked / state unchanged。
- refresh policy admission 已区分 `duration_reset`、`stack_only` 和缺来源的 `stack_duration_reset` coverage gap：
  - `Stacking=Refresh` 的 modifier definition 可作为 duration refresh 来源，重复施加时重置 `remaining_duration`。
  - 真实 stackable AddModifier 的重复施加显式记录 `refresh_policy=stack_only`，只增加 stack，不引入或覆盖 duration。
  - 当前 RuleBook 未发现同时 stackable 且 refresh-admitted 的 AddModifier，`stack+duration refresh` 保持 coverage gap，不制造 synthetic mutation。
- `StatusInstance` 增加 `source_stack_key`、`chance_admission`、`control_kind`，这些字段进入 snapshot / replay 可见状态。
- `StatusApplicationResult`、ability task、status callback、event dispatch 和 executor 全链路透传状态相关 `RNGEvent`。
- 状态命中、抵抗、免疫进入明确分支：
  - base chance 失败产生 `status_apply_failed` process-only record 和可 replay RNG event。
  - effect resistance 成功抵抗产生 `status_resisted` process-only record 和可 replay RNG event。
  - immunity 产生 `status_immunity` process-only record，不产生 RNG，不改变 state。
- unsupported chance / resist admission 走 blocked / state unchanged，不伪装成 executable。
- action availability 接入 control gate：
  - 只读取已 admission 的 status detail metadata。
  - 需要 `control_kind` 或 `status_category=control`，并要求非空 source trace。
  - 不按状态名、显示名、技能文本或固定角色/怪物推断控制。
- scheduler action 执行前和 queue action preflight 复用同一 control gate：
  - 被控制单位不能绕过 availability 直接提交 action。
  - queue action drain preflight 会返回 `status_control_gate:*` blocked reason。
  - 普通 scheduler 执行阻断保持 state unchanged。
- duration admission 增加 `tick_owner_policy=holder`，tick plan 会校验 status holder；非 holder tick blocked，state unchanged。
- `ActionPhaseEnd` duration tick 纳入 scheduler lifecycle sweep：
  - 结构化选择真实 `MoreOneMorePerTurn -> OneMore` AddModifier 来源。
  - action after sweep 只 tick holder-owned `ActionPhaseEnd` status。
  - tick mutation、settlement、source audit 和 replay 均通过。
- `TurnStart` duration tick 完成当前来源边界审查：
  - 当前 RuleBook 未发现 runtime-admitted `TurnStart` duration AddModifier。
  - validation 证明不会为 TurnStart 合成 mutation，state unchanged，并记录 coverage gap。
- wave end status cleanup 接入 WaveSystem remove 路径：
  - 清波移除 unit 前会清空 `statuses` 并移除 `flags.status_details`。
  - wave transition settlement 改为每条 mutation 都有 record，避免后续 source audit 只能追第一条 mutation。
  - RuntimeSourceAuditor 增加 `wave_system` mutation source 审计，cleanup/source audit/replay 均通过。
- Remove / expire 路径改为优先按 `instance_id` 移除 detail，避免同名不同来源状态被误删。
- `DispelStatus` 从 audit-only 推进到 source-admitted 安全子集：
  - lowering 标准化 target、`BuffType`、`Numbers`、`Order`、`OnlyCanDispel` 等字段。
  - runtime 只执行 fixed count=1、`Order=LastAdded`、目标可解析、候选 `can_dispel=true` 的确定性驱散。
  - 不可驱散或无候选产生 `status_dispel_skipped`，动态 count 缺绑定产生 `status_dispel_blocked`。
- 新增 `validate_p1_4_status_system`，覆盖 stack/cap、chance/resist/immunity、deterministic dispel、control gate、blocked negative、source audit 和 replay。

## 当前状态范围

可信 executable：

- 基于真实 Canonical IR `AddModifier` 的同源 stack / cap。
- stack mutation 的 replay 和 source audit。
- 基于真实 negative `LayerAddWhenStack` AddModifier 的 stack reduce 和 stack 到 0 remove，包含 `status_stack_reduce` / `status_stack_reduce_remove` settlement、callback events、source audit 和 replay。
- 基于真实 `Stacking=Refresh` modifier definition 的 duration refresh，重复施加前先降低 `remaining_duration`，再验证 refresh mutation / settlement / source audit / replay。
- 基于真实 stackable AddModifier 的 stack-only refresh，重复施加后 stack 增加、duration 不变，且不重复追加 `unit.statuses`。
- 缺失 chance 按 guaranteed admission，真实来源进入 `chance_admission`。
- 明确 synthetic negative 的 chance failure / resisted / immunity process-only 分支。
- 基于 source-admitted status detail 的 action availability control gate。
- 基于同一 source-admitted control gate 的 scheduler action execution block 和 queue action preflight block。
- holder-owned duration tick，包含 owner policy、mutation、replay 和 source audit；非 holder tick blocked；当前可信 moment 覆盖 `ModifierPhase1End` 与 `ActionPhaseEnd`。
- status detail 的 `Layer` / `layer` / `stacks` 动态绑定可读取当前 stack，公式读取路径随 stack mutation 后的 detail 更新。
- expire mutation 同时移除 `statuses` 和对应 `status_details`，并产生 `OnDestroy` / `OnModifierRemove` lifecycle event。
- wave end cleanup 对被清波移除的 unit 清理 `statuses` 和 `status_details`，并保留 wave transition source trace、settlement 和 replay。
- `OnPhase1` DoT 已接入状态生命周期 sweep：
  - scheduler 先发出 mutation-backed `status.lifecycle` 事件。
  - `EventDispatchSystem` 调用真实 status callback / task。
  - `StatusCallbackSystem` 走 `DotFormula` 和 `DamageSystem` 产生 `damage_source_kind="dot"` mutation。
  - 同一次 sweep 随后执行 holder duration tick，damage mutation 与 status mutation 均可 replay/source audit。
- blocked stack formula / unsupported admission 保持 state unchanged。
- 基于真实 `DispelStatus` + 真实可驱散 Buff status detail 的确定性 dispel，包含 mutation、settlement、replay 和 source audit。

仍是 partial 或 blocked：

- stack + duration refresh 当前没有 source-admitted 样例：当前 RuleBook 中 stackable AddModifier 均不是 refresh source，validation 只记录 coverage gap，不制造 synthetic stack-refresh mutation。
- dispel 只支持 first-phase deterministic fixed count=1；多数量、动态 count 缺绑定、随机 dispel、behavior flag dispel 仍 blocked 或 coverage gap。
- 控制状态已覆盖 availability、普通 scheduler 执行前阻断、queue action preflight；仍未实现 delay/AV change、已排队非 action ability 的完整控制语义。
- duration tick / expire 支持 `ModifierPhase1End` 与 `ActionPhaseEnd` 的当前 admission 范围；`TurnStart` 当前无 runtime-admitted 来源并保持 state unchanged；本阶段未扩展动态 duration 和更多 `LifeStepMoment`。

## 正例与负例

正例选择策略：

- 按结构化谓词选择，不使用固定角色名、怪物名、技能 ID、文件名 hash 或观测伤害。
- 主 stack 正例筛选条件包括：
  - `EffectIR.opcode == AddModifier`
  - 主线 `Avatar` / `Monster` / `Equip` 来源
  - safe target alias
  - `MaxLayer` 为可执行 fixed 值，且 `1 < MaxLayer <= 8`
  - `LayerAddWhenStack` 为可执行正 fixed 值
  - chance 缺失或 guaranteed

负例覆盖：

- 未绑定 dynamic stack 公式 blocked，不产生 mutation，state unchanged。
- chance failure 不产生 mutation，产生 RNG event 和 `status_apply_failed`。
- resist 不产生 mutation，产生 RNG event 和 `status_resisted`。
- immunity 不产生 mutation，不产生 RNG event，产生 `status_immunity`。
- control gate 只产生 action availability blocked reason，不修改 state。
- scheduler 执行前 control block 不产生 action effect mutation，state unchanged。
- queue action preflight 对控制单位返回 `status_control_gate:*`。
- duration owner 负例证明非 holder tick 不产生 mutation。
- action after duration 正例选择真实 `MoreOneMorePerTurn -> OneMore`，证明 `ActionPhaseEnd` sweep 产生 tick mutation、source audit 和 replay。
- TurnStart duration 当前无 runtime-admitted 来源，验证证明不会产生 synthetic mutation。
- wave cleanup 正例使用真实 executable multi-wave `WaveDefinitionIR`，证明 removed unit 不残留 active status detail，cleanup mutation 有 settlement，source audit 和 replay 通过。
- duration refresh 选择真实 `Stacking=Refresh` modifier definition，先 tick 低 `remaining_duration` 再重复施加，验证 refresh record、source audit 和 replay。
- stack-only refresh 选择真实 stackable AddModifier，证明重复施加只改变 stack，`remaining_duration` 保持原值且无 duration source 时不会引入 duration。
- stack + duration refresh 当前无 source-admitted 样例，验证记录 source count 和 coverage gap，不产生 synthetic mutation。
- stack reduce 选择真实 executable negative `LayerAddWhenStack` AddModifier，验证 2 -> 1、1 -> 0 remove、缺 existing detail blocked 三条路径。
- deterministic dispel 选择真实 fixed-count `DispelStatus` 和真实 `CanDispel=true` Buff；不可驱散状态 skipped，动态 count 缺绑定 blocked。
- DoT lifecycle 选择真实 `StatusDamageEmissionIR`、真实 status callback/task、真实同名 `AddModifier` duration admission；不依赖角色名、怪物名、固定技能 ID、文件名或观测伤害。
- 当前 raw/IR 未发现 `Order=Random` 的 `DispelStatus` 来源，随机 dispel 只记录 coverage gap，不产生 synthetic mutation。

## 来源边界

本阶段 runtime 仍只读取 Canonical IR / RuleBook / runtime snapshot 中的 status detail，不读取 raw TBGD、TextMap、旧 v7 或旧 model pack。

新增状态 mutation 必须能从 mutation metadata 反查到 settlement record、Canonical IR effect source、modifier definition 和 TBGD source path/evidence。`blocked`、`audit_only`、`discovered_only`、coverage gap 和 synthetic negative process-only case 不产生状态 mutation。

## 验证结果

在 `hsr_v075_baseline_clean/hsr` 下已通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_0_action_boundary --output-dir /tmp/hsr_v8_p1_0_action_boundary
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_1_unit_lifecycle --output-dir /tmp/hsr_v8_p1_1_unit_lifecycle
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_2_wave_system --output-dir /tmp/hsr_v8_p1_2_wave_system
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_3_summon_assistant_servant --output-dir /tmp/hsr_v8_p1_3_summon_assistant_servant
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_4_status_system --output-dir /tmp/hsr_v8_p1_4_status_system
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_245 --output-dir /tmp/hsr_v8_status_duration_v0_245
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_257 --output-dir /tmp/hsr_v8_damage_family_v0_257
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_264 --output-dir /tmp/hsr_v8_bounce_rng_v0_264
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_284 --output-dir /tmp/hsr_v8_monster_attached_status_v0_284
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_286 --output-dir /tmp/hsr_v8_mutation_events_v0_286
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_287 --output-dir /tmp/hsr_v8_status_target_audit_v0_287
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_288 --output-dir /tmp/hsr_v8_target_expression_v0_288
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_289 --output-dir /tmp/hsr_v8_target_expression_v0_289
git diff --check
```

`validate_p1_4_status_system` 输出 `ok=True`，并生成：

- `/tmp/hsr_v8_p1_4_status_system/validation_summary_p1_4_status_system.json`
- `/tmp/hsr_v8_p1_4_status_system/status_stack_cap_case_p1_4.json`
- `/tmp/hsr_v8_p1_4_status_system/status_refresh_case_p1_4.json`
- `/tmp/hsr_v8_p1_4_status_system/status_stack_only_refresh_case_p1_4.json`
- `/tmp/hsr_v8_p1_4_status_system/status_stack_refresh_case_p1_4.json`
- `/tmp/hsr_v8_p1_4_status_system/status_chance_cases_p1_4.json`
- `/tmp/hsr_v8_p1_4_status_system/status_control_case_p1_4.json`
- `/tmp/hsr_v8_p1_4_status_system/status_blocked_case_p1_4.json`
- `/tmp/hsr_v8_p1_4_status_system/status_dispel_case_p1_4.json`
- `/tmp/hsr_v8_p1_4_status_system/status_duration_owner_case_p1_4.json`
- `/tmp/hsr_v8_p1_4_status_system/status_action_after_duration_case_p1_4.json`
- `/tmp/hsr_v8_p1_4_status_system/status_turn_start_duration_case_p1_4.json`
- `/tmp/hsr_v8_p1_4_status_system/status_wave_cleanup_case_p1_4.json`
- `/tmp/hsr_v8_p1_4_status_system/status_layer_formula_case_p1_4.json`
- `/tmp/hsr_v8_p1_4_status_system/status_expire_remove_case_p1_4.json`
- `/tmp/hsr_v8_p1_4_status_system/status_dot_lifecycle_case_p1_4.json`
- `/tmp/hsr_v8_p1_4_status_system/status_random_dispel_case_p1_4.json`
- `/tmp/hsr_v8_p1_4_status_system/status_stack_reduce_case_p1_4.json`

## 距离最小可用战斗纵切还缺什么

- Dispel 已有确定性 fixed count=1 纵切；还需要多数量、动态 count 绑定、随机选择和 behavior flag dispel。
- Control 已覆盖普通 action 执行前和 queue action preflight；还需要非 action queue ability、delay/AV change、timeline/window 更深语义。
- Refresh 已有 duration-only 和 stack-only 纵切；stack + duration refresh 当前缺 source-admitted 样例，保持 coverage gap。
- RNG 分支需要进一步接入外部推演器可显式选择 / replay 的输入边界。
- Random dispel 仍缺当前 TBGD source-admitted `Order=Random` 样例；runtime 不合成随机驱散 mutation。
- TurnStart 当前没有 runtime-admitted 来源，已作为 blocked boundary 固化；更多 duration owner/moment 尚未接入。

## 距离完整复刻还缺什么

- 完整状态系统：叠层减少、刷新、概率、抵抗、免疫、驱散、控制、DoT tick、动态 duration、全部事件族 admission。
- 全角色数据卡、光锥、内外圈遗器与套装机制。
- 全怪物技能、被动、阶段切换、召唤、波次和关卡倍率。
- 完整目标系统：排序、随机、fetch、相邻目标、唯一实体、召唤物 / servant 目标。
- 完整敌方行动推演、队列窗口、环境与关卡机制。

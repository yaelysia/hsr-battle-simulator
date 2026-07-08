# simulator_v8_clean_core

`simulator_v8_clean_core` 是《崩坏：星穹铁道》战斗模拟器的 v8 主线内核。

v8 是 TBGD-first 的干净重写线，事实来源固定为：

```text
turnbasedgamedata-main -> TBGD compiler/lowering -> Canonical IR -> Combat Core
```

当前检查点：

```text
P3 summon / servant aggregate corrected; AssistantAvatar is out_of_scope and all-executable is still blocked by inherited summon/target gaps
聚合验证入口：python3 -m simulator_v8_clean_core.tools.validate_p3_summon_assistant_servant_complete
```

## 基本规则

- runtime 只读取 Canonical IR / 数据卡 IR，不读取 raw TBGD、TextMap、旧 v7、旧 model pack。
- TBGD raw schema 只能在 compiler/lowering/discovery/审计工具层读取。
- UI、游戏观测值、TextMap 名称、技能说明只能用于展示或验证，不能作为 runtime 规则来源。
- 所有状态变化都必须通过 `Mutation` 表达。
- 每次动作必须输出 `BattleTransition`，包含 before/after snapshot、目标解析、mutation、settlement、source audit、replay 信息。
- `blocked`、`audit_only`、`discovered_only`、placeholder 只能产生 process-only 记录，不能产生 mutation。
- 不允许按角色名、怪物名、技能名、固定 ID、固定文件名、固定 hash 或观测数值驱动规则。

详细红线见：

- `FORBIDDEN.md`
- `PROJECT_GOALS.md`
- `../CODEX_HANDOFF.md`

## 当前已落地范围

- Canonical IR、RuleBook、snapshot/replay、settlement/source audit。
- action/event/ability task/effect/status callback/queue/timeline 等核心骨架。
- direct、DoT、hp loss、break、break DoT、super-break、弹射、目标组、多段、击杀归因等伤害底座的当前可信范围。
- 普通状态生命周期、buff/debuff 共用 unit-attached status lifecycle、动态值绑定、资源、队列、额外行动语义、事件分发。
- 角色数据卡边界、加强版希儿示例卡、行迹/星魂通用接口。
- 怪物卡规范、`MonsterDataCardIR`、普通怪物技能动作、固定序列行动候选、怪物技能附带状态。
- 状态监听事件族矩阵、mutation-backed 事件源、银鬃尉官基础反击纵切。
- P2 状态系统底座与当前来源分类完成：全量状态来源分类、状态机制 family 矩阵、正负例样本、source audit/replay 抽样均由 `validate_p2_status_system_complete` 聚合验收；个体 blocked 来源是明确边界，不是可执行正例。
- 目标表达式 IR 与安全解析子集：简单别名、明确群体、上下文目标列表、`TargetSequence`、`TargetFilter`、确定性 `Retarget`。
- P3 召唤物 / 忆灵底座已有多条 executable 纵切：summoned monster spawn / fixed-sequence action availability、SummonUnitData boundary、servant lifecycle/action/status/BattleSetup、target relation、remove/cleanup、source audit/replay 抽样均可验证。当前状态是 P3 底座闭环验收通过、全正例未完成：P3 最终聚合已修正为继承分步矩阵真实缺口，当前 `validation_gate_ok=true`、`p3_summon_phase_complete=true`、`p3_summon_substrate_complete=true`、`p3_summon_all_executable_complete=false`；AssistantAvatar / `TurnInsertAssistantAbility` 已移出 P3 召唤物/servant验收并记录为 `out_of_scope`，剩余 P3 backlog 是 summoned monster intent admission/source-gap 与 summon/servant target admission，不能误读为 executable。
- P1-0 action availability 查询边界：外部推演器可查询当前普通动作、queue mandatory/selectable、pending turn end、enemy fixed-sequence candidate 和 summon blocked。
- 本地 UI 测试台 `simulator_v8_ui/`，作为测试编排与审计展示层，不作为规则系统。

## 当前仍未完整落地的大块

- 完整角色面板装配：晋阶、全量角色行迹、光锥、内圈/外圈遗器及套装效果。
- 大量角色卡人工解释、结构化 admission 与验证。
- 状态系统 P2 底座已完成；后续仍需按 P4+ 扩面特殊模式、新事件源、新 target/opcode、未来数据库新增机制，不能把 boundary/process-only 项伪装成全正例，也不能把 P2 完成误读成全角色、全怪物、装备和关卡机制已经复刻。
- 完整目标系统：排序、随机、fetch、相邻目标、唯一实体、召唤物/servant 目标、特殊玩法目标。
- 全怪物技能、被动、阶段切换、召唤、波次、关卡倍率。
- 完整敌方行动推演策略、波次系统、P3 inherited gap 清理、servant damage formula、特殊战斗模式；AssistantAvatar / avatar assistant ability 属于独立后续，不纳入 P3 召唤物/忆灵验收。
- 光锥、遗器、环境、关卡机制。

## 推荐验证

在 `hsr_v075_baseline_clean/hsr` 下运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p3_summon_assistant_servant_complete --output-dir /tmp/hsr_v8_p3_complete
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p2_status_system_complete --output-dir /tmp/hsr_v8_p2_status_system_complete
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p2_s11_full_status_source_closure --output-dir /tmp/hsr_v8_p2_s11_full_status_source_closure
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p2_s10_status_callback_coverage --output-dir /tmp/hsr_v8_p2_s10_status_callback_coverage
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_0_action_boundary --output-dir /tmp/hsr_v8_p1_0_action_boundary
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_289 --output-dir /tmp/hsr_v8_target_expression_v0_289
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_288 --output-dir /tmp/hsr_v8_target_expression_v0_288
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_287 --output-dir /tmp/hsr_v8_status_target_audit_v0_287
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_286 --output-dir /tmp/hsr_v8_mutation_events_v0_286
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_284 --output-dir /tmp/hsr_v8_monster_attached_status_v0_284
git diff --check
```

当前期望：

- `compileall` 通过。
- 相关验证输出 `ok=true`。
- P3 聚合当前期望是底座闭环通过、全正例未完成：`ok=true`、`validation_gate_ok=true`、`p3_summon_phase_complete=true`、`p3_summon_substrate_complete=true`、`p3_summon_all_executable_complete=false`、`p3_summon_sources_classified=true`、`p3_summon_admission_gap_count=2123`、`p3_summon_source_gap_blocked_count=27`、`p3_summon_scope_exclusion_count=1`、`p3_summon_implementation_missing_count=0`、`p3_summon_lowering_gap_count=0`、`p3_summon_unclassified_count=0`。这些 gap 来自 `p3_summon_inherited_gap_matrix.json`，并且已投影到 source/mechanism 主矩阵子行和 allowed-gap evidence matrix，不能被宽域 executable 正例掩盖；AssistantAvatar 出现在 `p3_summon_scope_exclusions.json`，不计入 P3 gap。
- P2 聚合 summary 包含 `p2_status_substrate_complete=true`、`p2_all_status_sources_classified=true`、gap/unclassified 均为 0；blocked 个体来源必须有边界证据并保持 state unchanged。
- replay/source audit/settlement traceability 通过。
- unsupported、blocked、audit-only、discovered-only 不产生 mutation。
- runtime/core/systems 不引用 UI，不读取 raw TBGD/TextMap/旧 v7/旧 model pack。

## 下一阶段建议

当前 P3 召唤物 / 忆灵是“底座闭环验收通过，全正例未完成”。下一步可以进入 P4+ 扩面，但 P3 backlog 应持续收敛：

1. 修 S0 `summoned_monster_intent` admission / source-gap blocked 缺口，优先寻找 custom value hash / dynamic monster id 的真实结构化绑定来源。
2. 修 S0 target 子项 admission gap，按子行归类，不能用一个 executable 正例代表整个来源域。
3. AssistantAvatar / avatar assistant ability 若要实现，应另立独立目标，不作为 P3 召唤物/忆灵 backlog。
4. 只有 `p3_summon_all_executable_complete=true` 且 inherited gap 为 0 后，才能宣称 P3 全正例完成。

每个新增机制仍必须满足：真实来源、通用接口、正例可审计、负例 state unchanged。

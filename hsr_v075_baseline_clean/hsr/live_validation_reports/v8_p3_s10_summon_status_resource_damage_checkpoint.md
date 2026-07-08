# v8 P3-S10 summon status / resource / damage checkpoint

## 结论

P3-S10 已完成当前可执行范围。

本阶段把召唤实体接入状态、资源、伤害和击杀归因边界：

- executable：servant 作为 actor / target / status holder 对自身施加状态，走统一 `status_system`，settlement、replay、source audit 均通过。
- blocked：servant hp-damage action IR 已存在，但当前没有 servant damage stat admission，executor 会 blocked，不默认套用 owner 或 copied attack。
- boundary：kill attribution source frame 能区分 servant attacker、owner credit、source id/source kind。
- negative：removed servant 不能继续承受 damage mutation。

## 本次修改

- `core/executor.py`
  - 增加 summon damage stat gate。
  - summon actor 的 HP damage action 需要真实 `summon_damage_stat_admission` / `servant_damage_stat_admission`。
  - summoned monster 只在 combatant profile source executable 且 source trace 存在时允许 damage stat source。
  - blocked reason 写入 `action_preflight` 和 transition coverage：`summon_damage_stat_blocked_reason`。
- 新增 `tools/validate_p3_s10_summon_status_resource_damage.py`
  - 覆盖 servant self-status 正例、servant damage stat blocked、resource ownership boundary、kill attribution source-frame boundary、removed summon damage negative 和 source matrix。
  - 输出 summary / matrix / compact audit，不写完整 Canonical IR 或全量 transition dump。

## 正例

S10 主验证使用结构化谓词选择 executable servant definition 和 executable servant self-target status action：

- selected action: `servant_skill:1140205`
- servant 作为 action actor。
- servant 作为 action target。
- servant 成为 status holder。
- 产生 `status_system` mutation。
- settlement 中有 status records。
- replay ok。
- source audit ok。
- action 不产生 damage mutation，符合当前 damage stat admission 边界。

## 边界与负例

- servant hp-damage action IR count: 120。
- 直接绕过 availability 执行 servant hp-damage action 时：
  - `action_enabled=false`
  - `summon_damage_stat_blocked_reason=summon_damage_stat_binding_not_admitted`
  - no mutation
  - state unchanged
  - process-only blocked record
- 当前 executable servant action 无正向 skill point cost：
  - resource ownership mutation 不合成。
  - 不默认把 owner 当作 resource owner。
- kill attribution source-frame boundary：
  - `attacker_id=summon:servant:*`
  - `kill_credit_owner_id=ally:servant_owner`
  - `kill_credit_source_id=summon_action:servant_definition:11402`
  - `kill_credit_source_kind=summon_damage_source_frame_boundary`
  - 该 case 只验证 source-frame 归因语义，不声称 servant damage formula 已 executable。
- removed servant damage negative：
  - removed servant target -> `damage_source_target_removed`
  - no damage mutation
  - no hit/defeat event

## 剩余边界

- servant damage formula executable 正例尚未开放；必须等 owner/stat binding source admission 完整后再从 blocked 升级。
- servant DoT / control / immunity / dispel / duration tick 当前依赖 P2 通用状态底座；本阶段只证明 summon unit 可作为 status holder 并通过 P1-4 状态回归。
- resource ownership 当前没有正向 resource-costing servant action 样例；保持 `source_absent_not_required`，不做 synthetic resource mutation。

## 验证

所有验证均串行运行，输出到 `/tmp`。构建型验证用 `nice` / `ionice` 降低 CPU 和磁盘 IO 优先级；未并行运行重验证，未写完整 Canonical IR 或全量 transition dump。

```bash
python3 -B -c "import py_compile; files=['simulator_v8_clean_core/core/executor.py','simulator_v8_clean_core/tools/validate_p3_s10_summon_status_resource_damage.py']; [py_compile.compile(path, cfile=f'/tmp/hsr_v8_s10_compile_{index}.pyc', doraise=True) for index, path in enumerate(files)]"
ionice -c2 -n7 nice -n 10 python3 -B -m simulator_v8_clean_core.tools.validate_p3_s10_summon_status_resource_damage --output-dir /tmp/hsr_v8_p3_s10_status_resource_damage
ionice -c2 -n7 nice -n 10 python3 -B -m simulator_v8_clean_core.tools.validate_p3_s6_summon_action_execution --output-dir /tmp/hsr_v8_p3_s6_summon_action_s10_regression
ionice -c2 -n7 nice -n 10 python3 -B -m simulator_v8_clean_core.tools.validate_p1_4_status_system --output-dir /tmp/hsr_v8_p1_4_status_s10_regression
ionice -c2 -n7 nice -n 10 python3 -B -m compileall -q simulator_v8_clean_core/core/executor.py simulator_v8_clean_core/tools/validate_p3_s10_summon_status_resource_damage.py
git diff --check
```

结果：

- P3-S10 main: `ok=True`
- P3-S6 summon action regression: `ok=True`
- P1-4 status system regression: `ok=True`
- targeted compileall: pass
- git diff --check: pass

未运行全量 P1 aggregate / P2 full status / v0_209 等重验证；本次只触达 executor gate 和 S10 定向 validator，全量验证留到 P3-S12 或用户明确要求时串行执行。

## 下一步

进入 P3-S11：BattleSetup、scenario、外部推演器接口和端到端样例。

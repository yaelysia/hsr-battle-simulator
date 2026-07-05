# P1-2 WaveSystem 最小骨架检查点

## 本阶段完成

- 新增 `WaveMonsterEntryIR` / `WaveDefinitionIR`，并纳入 `CanonicalIR` 与 `RuleBook` 查询 API。
- `TBGDLowering` 从 `ExcelOutput/StageConfig.json` 降出 wave definition：
  - `StageID`
  - `StageConfigData` 中的 `_Wave`
  - `MonsterList` 的 `Monster0..` entry
  - `StageAbilityConfig` 引用
- runtime 不读取 raw `StageConfig.json`；WaveSystem 只读 `RuleBook`、`WaveDefinitionIR` 和 scenario/setup 已写入的 `wave_runtime`。
- `ScenarioSpec` 增加可选 `wave_definition_ref` / `stage_ref`，loader 也支持 `wave_setup.kind=tbgd_stage`。
- 有 wave setup 的 scenario 只生成当前 wave 敌人；后续 wave 不提前进入 active target/timeline。
- 新增 `systems/wave.py`：
  - `WaveRuntimeView`
  - `WaveTransitionPlan`
  - `WaveTransitionResult`
  - `WaveSystem.view / plan_transition / apply_transition`
- wave transition 通过 mutation 推进：
  - old wave enemy `UnitRemove`
  - `wave_index` mutation
  - next wave enemy `UnitSpawn`
  - `global_flags["wave_runtime"]` mutation
  - battle victory/defeat outcome mutation
- `ActionAvailabilitySystem` 暴露 `wave_transition_available` 和 battle ended 状态。
- `CombatScheduler.step` 在无 queue/pending turn-end 时优先执行 wave transition，避免清波后只报 `no_admitted_actor`。
- `wave.monster` 成为 `OnWaveMonster` 的真实 runtime event source；fake/incomplete `wave.monster` 仍 blocked。

## WaveDefinition 来源

WaveDefinition 来源固定为：

```text
turnbasedgamedata-main/ExcelOutput/StageConfig.json
-> TBGD lowering
-> WaveDefinitionIR / WaveMonsterEntryIR
-> RuleBook
-> WaveSystem
```

每个 entry source evidence 记录：

- `StageID`
- StageConfig row index
- `_Wave` 解析结果
- `MonsterList` wave index
- `Monster0..` key
- monster id

entry admission 策略：

- 缺 monster id / 0：blocked。
- 缺 `monster:<id>` entity：blocked。
- 缺 executable `CombatantProfileIR`：blocked。
- 缺 `MonsterDataCardIR`：blocked。
- data card 因敌方 AI 未 admission 而 coverage blocked 时，不阻塞 spawn；P1-2 只要求存在 profile/card/source，不执行敌方 AI。

## Wave runtime schema

当前以 `global_flags["wave_runtime"]` 保存，schema version：

```text
p1_2_wave_runtime_v1
```

核心字段：

- `wave_definition_id`
- `stage_id`
- `current_wave_index`
- `total_waves`
- `started_wave_indices`
- `cleared_wave_indices`
- `current_wave_unit_ids`
- `spawned_unit_ids_by_wave`
- `removed_unit_ids_by_wave`
- `status`
- `blocked_reason`
- `source_trace`

选择 `global_flags` 是为了控制 P1-2 改动面；所有运行期变更仍必须通过 `Mutation`。

## Wave transition 行为

当前 wave 清空且存在下一波时：

1. 对旧 wave enemy 生成 UnitRemove mutations。
2. 写入 wave_runtime cleared/between_waves。
3. 生成 `wave_index` mutation。
4. 对下一 wave entries 生成 UnitSpawn mutations。
5. 写入 wave_runtime active/current ids。
6. 产生 `wave.cleared`、`wave.started`、`wave.monster` events。

最后一波清空时：

- 不再 spawn。
- 设置 `battle_outcome="victory"`。
- 设置 `phase="ended"`、`current_window="battle_end"`。
- 产生 `battle.victory` event。

我方 active unit 为 0 时：

- 设置 `battle_outcome="defeat"`。
- 设置 `phase="ended"`、`current_window="battle_end"`。
- 产生 `battle.defeat` event。

## 跨波保留策略

P1-2 不做无来源清理：

- 保留 ally HP。
- 保留 ally energy。
- 保留 skill points / max skill points。
- 保留 ally statuses/modifiers/resources。
- 保留 global AV / turn sequence。
- 不清理 queue；pending queue 阻塞 wave transition。
- 不清理 summon；active enemy summon 默认阻塞 wave clear，除非有明确 `wave_clear_policy="ignore"`。

## OnWaveMonster 范围

`OnWaveMonster` 的 status event family 现在可映射到 runtime event source：

```text
wave.monster
```

WaveSystem 生成的 event payload 必须包含：

- `wave_definition_id`
- `wave_index`
- `unit_id`
- `entry_id`
- `position`
- `source_trace`

缺 payload 或缺 source trace 的 fake `wave.monster` 会 blocked/state unchanged。下游 callback 是否产生 mutation 仍由 status callback / ability task admission 决定。

## 验证结果

已通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_2_wave_system --output-dir /tmp/hsr_v8_p1_2_wave_system
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_285 --output-dir /tmp/hsr_v8_v0_285_after_p1_2
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_286 --output-dir /tmp/hsr_v8_v0_286_after_p1_2
```

`validate_p1_2_wave_system` 覆盖：

- WaveDefinition lowering 正例。
- 结构化选择 `wave_count >= 2` 的 executable stage，不按固定 StageID。
- 初始 current wave setup。
- pure query state unchanged。
- current wave 未清不推进。
- current wave clear -> next wave UnitSpawn。
- old wave UnitRemove replay。
- `wave_index` replay。
- final wave clear -> victory。
- all allies defeated -> defeat。
- missing wave definition blocked/state unchanged。
- active unknown enemy blocks clear。
- active enemy summon blocks clear。
- pending queue blocks wave transition。
- `wave.monster` payload 完整。
- fake/incomplete `wave.monster` blocked。
- source audit。
- scheduler/action availability 接入。

## 距离最小可用战斗纵切还缺什么

- P1-3 summon/assistant/servant：复用 wave membership 和 clear policy，补 owner/lifetime/clear admission。
- P1-4 状态系统：基于 `wave.started` / `wave.cleared` / `battle.end` 补 duration/tick/cleanup。
- P1-5 queue/window：把 wave transition 放进正式窗口顺序，处理 pending queue drain/cancel。
- P1-8 scenario/UI：让 UI 选择 stage/wave setup 并展示 wave audit。

## 距离完整复刻还缺什么

- 完整关卡倍率、StageAbility、环境机制。
- 全怪物技能、全怪物被动、阶段切换、召唤、特殊实体。
- 外部推演器侧的敌方动作控制策略；v8 core 仍不实现敌方 AI。
- 完整状态系统、光锥、遗器、角色面板装配。

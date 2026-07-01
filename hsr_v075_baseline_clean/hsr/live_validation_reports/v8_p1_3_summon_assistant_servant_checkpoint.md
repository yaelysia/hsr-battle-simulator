# v8 P1-3 Summon / Assistant / Servant checkpoint

## 范围

本阶段把 summon / assistant / servant 从预留字段推进到可审计的分类、来源 admission 和最小 runtime 纵切。

已支持的可执行纵切：

- `SummonMonster` ability task 从 TBGD mainline monster ability 来源 lowering 为 `SummonMonsterIntentIR`。
- intent 中每个 summon entry 必须有固定 `MonsterID`、可执行 combatant profile、monster card、明确 location source。
- intent 必须结构化表达 `SummonMonster.DelayRatio` admission；只有缺失或固定 0 才执行，动态或非零 DelayRatio blocked。
- enemy summoned monster 使用 `side="enemy"`，并通过 flags 标记 `summon_kind="summoned_monster"`、owner/summoner、intent/entry source trace、wave clear policy。
- spawn 复用 P1-1 `UnitSpawn` mutation 和 reducer replay。
- summon runtime view 写入 `global_flags["summon_runtime"]`，schema 为 `p1_3_summon_runtime_v1`。

已分类但不执行的范围：

- `SummonUnitData` 和 `ConfigSummonUnit` 只进入 `SummonUnitDefinitionIR` discovery。`IsClient`、`DestroyOnEnterBattle`、视觉/场景 summon 不触发 runtime spawn。
- `MonsterConfig.SummonIDList` 只保留为 monster card catalog ref，不作为触发来源。
- summon remove / expire 需要真实 remove source；直接调用 remove API 或只有 spawn source trace 时 blocked，不产生 `UnitRemove`。
- `TurnInsertAssistantAbility` 进入 `AssistantAbilityResolutionIR`，但因 assistant actor / stats source 未 admission，保持 blocked，不 fake ability execution。
- `ConfigAbility/Servant` 进入 `ServantDefinitionIR`，但 servant 独立 unit / owner-bound component 来源未 admission，保持 blocked，不创建假 UnitState。

## 实现落点

- `rules/ir.py`
  - 新增 `SummonUnitDefinitionIR`、`SummonMonsterIntentIR`、`SummonMonsterEntryIR`、`AssistantAbilityResolutionIR`、`ServantDefinitionIR`。
  - `CanonicalIR` 输出上述 IR 集合。
- `rules/rulebook.py`
  - 新增 summon unit、summon monster intent、assistant resolution、servant definition 索引和查询 API。
- `tbgd/lowering.py`
  - lowering `SummonUnitData` / `ConfigSummonUnit` discovery。
  - lowering admitted `SummonMonster` task 为可执行或 blocked intent。
  - lowering `SummonMonster.DelayRatio` 为 `delay_policy`；非零或动态 DelayRatio 会阻塞 intent。
  - lowering `TurnInsertAssistantAbility` 为具体 blocked resolution。
  - lowering `ConfigAbility/Servant` discovery。
  - 新增 `CasterSummonedMinions`、`LastSummonMonsters` 目标别名 admission。
- `systems/summon.py`
  - 新增 `SummonSystem`，覆盖 runtime view、spawn plan、remove plan、owner cleanup blocked。
- `systems/unit_relation.py`
  - 统一 ally/enemy/summon 的 combat team 判定，`side="summon"` 通过 `flags["team_side"]` 归队。
- `systems/target.py`
  - group alias、bounce adjacent 和 explicit target relation 改用 combat team helper。
  - 支持从 summon runtime 解析 `LastSummonMonsters`、`CasterSummonedMinions`。
- `systems/action_availability.py`
  - `side="summon"` 不再暴露默认 action；缺 admission 时返回 `summon_timeline_not_admitted` / `summon_action_admission_missing`。
  - `summon_action_admitted=True` 不能单独打开行动；还必须绑定 summon runtime entity、可执行 action admission 和 source trace。
- `systems/queue.py`
  - queue target relation 使用 combat team helper，不再直接比较 raw `side`。
- `tools/validate_p1_3_summon_assistant_servant.py`
  - 新增 P1-3 专项验证。
- `tools/validate_v0_247.py`
  - 更新旧验证口径：manual ultimate enqueue 只要求 present ActionEvent，不要求 ActionEvent 执行 admission。
  - 当前 TBGD queue windows 中没有 `ultimate/counter` family 时，不伪造 IR；manual ultimate route 由 runtime route 样例验证。
  - extra-turn synthetic case 没有真实触发时，验证不产生假队列/假执行。

## Source / Replay / Blocked 口径

- runtime 只读取 Canonical IR / RuleBook / scenario 已构造 state，不读取 raw TBGD、TextMap、旧 v7 或旧 model pack。
- `SummonMonster` spawn 的 `UnitSpawn` mutation 可反查到 intent、entry、monster card、combatant profile、timeline/profile source trace。
- summon 初始 AV source trace 包含 `delay_policy`；当前可执行子集只承认固定 0 或缺失 DelayRatio，不沉默跳过该字段。
- `SummonSystem.view()` 是纯查询，验证 state unchanged。
- blocked summon intent、assistant resolution、servant definition 只产生 process-only 或 validation record，不产生 mutation。
- `SummonSystem.plan_remove()` 缺少真实 remove source admission 时 blocked，不能复用 spawn source trace 产生 remove mutation。
- owner cleanup 缺少真实 `owner_death_policy=remove` 时 blocked，不移除 summon。
- `wave_clear_policy=counts` 阻塞 wave clear；`ignore` 不阻塞；缺 policy 保守阻塞。

## 验证结果

本次在 `hsr_v075_baseline_clean/hsr` 下已通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_0_action_boundary --output-dir /tmp/hsr_v8_p1_0_after_p1_3
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_1_unit_lifecycle --output-dir /tmp/hsr_v8_p1_1_after_p1_3
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_2_wave_system --output-dir /tmp/hsr_v8_p1_2_after_p1_3
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_3_summon_assistant_servant --output-dir /tmp/hsr_v8_p1_3_summon_assistant_servant
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_240 --output-dir /tmp/hsr_v8_v0_240_after_p1_3
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_242 --output-dir /tmp/hsr_v8_v0_242_after_p1_3
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_246 --output-dir /tmp/hsr_v8_v0_246_after_p1_3
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_247 --output-dir /tmp/hsr_v8_v0_247_after_p1_3
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_283 --output-dir /tmp/hsr_v8_v0_283_after_p1_3
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_287 --output-dir /tmp/hsr_v8_v0_287_after_p1_3
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_289 --output-dir /tmp/hsr_v8_v0_289_after_p1_3
git diff --check
```

结果：

- compileall：通过。
- P1-0 / P1-1 / P1-2 / P1-3：`ok=True`。
- v0_240 / v0_242 / v0_246 / v0_247 / v0_283 / v0_287 / v0_289：`ok=True`。
- `git diff --check`：通过。

`validate_v0_283` 曾在并行验证批次中被系统以 code 137 结束；单独重跑后 `ok=True`。

审查修复后又补跑：

- `validate_p1_0_action_boundary --output-dir /tmp/hsr_v8_p1_0_after_review_fix`：`ok=True`
- `validate_p1_1_unit_lifecycle --output-dir /tmp/hsr_v8_p1_1_after_review_fix`：`ok=True`
- `validate_p1_2_wave_system --output-dir /tmp/hsr_v8_p1_2_after_review_fix`：`ok=True`
- `validate_p1_3_summon_assistant_servant --output-dir /tmp/hsr_v8_p1_3_after_review_fix`：`ok=True`
- `validate_v0_240 --output-dir /tmp/hsr_v8_v0_240_after_review_fix`：`ok=True`
- `validate_v0_242 --output-dir /tmp/hsr_v8_v0_242_after_review_fix`：`ok=True`
- `validate_v0_246 --output-dir /tmp/hsr_v8_v0_246_after_review_fix`：`ok=True`
- `validate_v0_247 --output-dir /tmp/hsr_v8_v0_247_after_review_fix`：`ok=True`
- `validate_v0_283 --output-dir /tmp/hsr_v8_v0_283_after_review_fix`：`ok=True`
- `validate_v0_287 --output-dir /tmp/hsr_v8_v0_287_after_review_fix`：`ok=True`
- `validate_v0_289 --output-dir /tmp/hsr_v8_v0_289_after_review_fix`：`ok=True`
- `git diff --check`：通过。

其中 `validate_v0_242` 在并行批次中曾被系统以 code 137 结束；单独重跑后 `ok=True`。

P1-3 专项验证覆盖：

- `SummonUnitDefinitionIR` discovery blocked。
- monster `summon_refs` 只作为 catalog，不触发 spawn。
- `SummonMonster.DelayRatio` 已结构化 admission；可执行 intent 均为缺失或固定 0，非零/动态 DelayRatio blocked。
- `SummonMonsterIntentIR` 可执行正例。
- summon spawn 产生 `UnitSpawn` 和 summon runtime mutation，并通过 replay/source trace 检查。
- 直接 summon remove 无真实来源时 blocked、无 mutation、state unchanged。
- ally summon / enemy summoned monster target relation。
- `LastSummonMonsters`、`CasterSummonedMinions` runtime alias resolution。
- summon timeline/action 缺 admission blocked；flag-only `summon_action_admitted=True` 不会暴露行动。
- enemy summon wave clear counts / ignore / missing policy。
- blocked intent 无 mutation。
- owner death 缺 policy 不假 remove。
- assistant resolution blocked 且无 fake execution。
- servant definitions blocked 且无 fake UnitState。
- static checks 通过。

## 当前做到哪里

P1-3 已完成第一条真实 summon 纵切：

```text
TBGD SummonMonster task
-> SummonMonsterIntentIR
-> RuleBook lookup
-> SummonSystem spawn plan
-> UnitSpawn mutation + summon runtime mutation
-> replay/source audit
```

assistant 和 servant 当前只完成分类、source trace、blocked reason 和 negative validation，没有被伪装成 executable。

summon remove / expire 当前也只完成 admission gate 和 negative validation；要变成 executable 必须先有真实 remove/expire source。

## 距离最小可用战斗纵切还缺什么

- P1-4：状态系统主体，尤其 stack、refresh、duration、tick、chance/resist/immunity、dispel、control gating。
- P1-5：queue/window 顺序，尤其 follow-up/counter/assistant/extra-turn/ultimate window 的统一 drain 语义。
- P1-6：目标系统剩余关键子集，包括 sort、fetch、adjacent、random、unique、servant target。
- P1-7：RNG ledger 和 deterministic branch input。
- P1-8：最小 BattleSetup 入口，表达 waves、initial status、initial summon、deterministic RNG。
- P1-9：第一阶段聚合 validation 和验收报告。

## 距离完整复刻还缺什么

- 完整角色面板装配：晋阶、全量行迹、光锥、内外圈遗器及套装。
- 全角色、全怪物、全 servant/assistant/summon 的人工解释、数据卡和来源验证。
- 完整状态生命周期、DoT tick、控制、抵抗、免疫、驱散。
- 完整目标表达式系统和特殊玩法目标。
- 全怪物技能、被动、阶段切换、召唤、波次、关卡倍率。
- 光锥、遗器、环境、关卡机制。
- 外部推演器策略层和完整战斗配置入口。

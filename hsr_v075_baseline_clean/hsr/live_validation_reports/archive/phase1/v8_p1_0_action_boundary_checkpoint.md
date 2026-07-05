# v8 P1-0 Action Boundary Checkpoint

## 结论

P1-0 已新增稳定的纯查询入口：

```python
ActionAvailabilitySystem(rules).view(state)
CombatScheduler(rules).action_availability(state)
```

输出 schema version：

```text
p1_0_action_availability_v1
```

该查询只读 `BattleState` / `RuleBook` / 数据卡 IR，不调用 executor，不 dequeue queue，不推进 timeline，不消耗 RNG，不写 mutation。

## 当前做到哪里

- 新增 `systems/action_availability.py`，输出 `ActionAvailabilityView`、`ActionChoice`、`QueueAvailability`、`ActorAvailability`、`SelectableWindow`、`BlockedActionReason`。
- 新增 `systems/action_preflight.py`，把 action target/resource/source admission 的纯派生逻辑从 executor 私有 helper 中抽出，供 executor、enemy candidate 和 availability 共用。
- availability mode 当前覆盖：
  - `external_selectable`
  - `queued_mandatory`
  - `queued_selectable`
  - `scheduler_required`
  - `blocked`
  - `idle` 预留，当前未作为主路径使用。
- queue 选择使用 scheduler 同一个 `select_next_queue_drain_plan` helper。
- mandatory queue 会阻塞普通 external command，返回 process-only blocked transition。
- selectable queue 缺少外部 command 时返回 `queue_selectable_command_missing`，不自动执行。
- enemy fixed-sequence candidate 作为 `choice_kind="enemy_fixed_sequence"` 暴露，`control="external"`，不推进 cursor，不自动选目标，不自动执行。
- summon active actor 缺 admission 时 blocked，reason 为 `summon_action_admission_missing`。
- pending turn end 时输出 `scheduler_required`，不暴露普通 action choices。

## 敌方 AI 边界

P1-0 不实现敌方 AI。`EnemyActionSystem.next_candidate` 仍只把 `MonsterDataCardIR.action_sequence` 降为规则候选。

历史命名债务仍保留：

- `ActionCommand.source` 的 Literal 仍包含 `"ai"`，未在 P1-0 静默改接口。
- `EnemyActionSystem.command_from_candidate` 仍会生成 `source="ai"`，这是 legacy compatibility path。
- 新增 availability API 不使用 `"ai"` 表达策略选择；enemy choice 的 command template 使用 `source="manual"` 加 metadata：
  - `selection_controller="external"`
  - `candidate_kind="fixed_sequence_candidate"`

后续如要移除 `source="ai"`，需要单独做接口兼容决策。

## Ultimate Window 状态

manual ultimate queue 现在作为 selectable window 暴露。由于当前 lowered 数据里没有满足 action event/binding 全 admission 的 ultimate 正例，P1-0 验证覆盖的是：

- selectable window 可观测。
- 缺外部 command 不自动执行。
- action event source 不完整时 blocked 且 state unchanged。

可执行 ultimate selectable 正例留给后续 queue/window 与 ultimate admission 扩面。

## 验证

新增验证命令：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_0_action_boundary --output-dir /tmp/hsr_v8_p1_0_action_boundary
```

本次运行结果：

```text
v8 p1_0_action_boundary validation ok=True
```

覆盖 case：

- empty/no actor state blocked。
- no active turn state preview next actor。
- active ally turn 暴露 action set choices。
- ally executable command 经 scheduler/executor 执行并 replay/source audit 通过。
- ally SP 不足或 target empty 时 blocked/state unchanged。
- active enemy turn 暴露 fixed-sequence candidate。
- enemy explicit command 执行通过，cursor 只在成功执行后推进。
- enemy mismatched action / target blocked/state unchanged。
- enemy missing monster data card blocked。
- mandatory counter queue 优先于普通输入，普通 command blocked/state unchanged。
- selectable manual ultimate window 可观测，缺 command 不执行，source incomplete blocked。
- pending turn end 不暴露普通 action。
- summon actor 缺 admission blocked。
- availability 查询前后 snapshot hash 一致，JSON 输出稳定。

## 本次触碰文件

- `simulator_v8_clean_core/systems/action_availability.py`
- `simulator_v8_clean_core/systems/action_preflight.py`
- `simulator_v8_clean_core/systems/scheduler.py`
- `simulator_v8_clean_core/systems/enemy_action.py`
- `simulator_v8_clean_core/core/executor.py`
- `simulator_v8_clean_core/systems/__init__.py`
- `simulator_v8_clean_core/tools/validate_p1_0_action_boundary.py`
- `simulator_v8_clean_core/README.md`
- `simulator_v8_clean_core/FIRST_PHASE_TASK_CHECKLIST.md`
- `live_validation_reports/v8_p1_0_action_boundary_checkpoint.md`

未读取或依赖旧 v7、旧 model pack、TextMap；未新增依赖。

## 距离最小可用战斗纵切还缺什么

- P1-1 UnitLifecycle：死亡、退场、不可行动、targetability 需要统一进入 availability gating。
- P1-2 WaveSystem：battle end / next wave / no actor idle 需要真实 runtime 化。
- P1-3 Summon/Assistant/Servant：当前 summon action 只 blocked 预留，没有真实行动 admission。
- P1-5 Queue/Window：ultimate 正例、extra_turn action choice、更多 selectable window 还需扩面。
- P1-7 RNG：随机目标和概率选择还未进入可枚举分支输出。

## 距离完整复刻还缺哪些大模块

- 完整状态系统：叠层、刷新、概率、持续时间、tick、DoT tick、控制、抵抗、免疫、驱散。
- 完整目标系统：sort/fetch/random/adjacent/unique/summon/servant 目标。
- 完整角色面板、光锥、遗器、环境、关卡机制。
- 全怪物技能、被动、阶段切换、召唤、波次、关卡倍率。

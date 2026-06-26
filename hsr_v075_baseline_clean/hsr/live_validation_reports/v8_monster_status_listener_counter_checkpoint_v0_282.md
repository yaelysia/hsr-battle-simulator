# v8 怪物状态监听反击 checkpoint v0_282

## 本阶段完成

- 纠正怪物“被动”边界：
  - `MonsterConfig.AbilityNameList` 仍是怪物卡被动入口之一。
  - `ConfigCharacter/Monster.SkillList` 中的 `UseType=Passive`、技能挂出的 modifier、modifier 自身 `_CallbackList` 也会形成战斗机制入口。
  - `MonsterSkill.ModifierList` 仍不作为被动来源。
- 接通状态监听触发底座：
  - 状态实例挂载后保留 `trigger_ids_by_event`。
  - `damage.hit` 事件通过 `EventDispatchSystem` 映射到 `OnAfterBeingAttacked`。
  - `StatusCallbackSystem` 只执行 `coverage_status=executable` 的 callback 和 task。
  - 队列插入仍走 `QueueIntentIR -> QueueWindowIR -> QueueResolutionIR -> CombatScheduler`。
- 打通银鬃尉官基础反击纵切：
  - `monster_skill:100301003`（盾反）通过 `AddModifier` 给自身挂监听状态。
  - 监听状态 `OnCreate` 初始化反击计数。
  - 我方攻击后触发 `OnAfterBeingAttacked`，条件通过时设置计数，并入队 `TurnInsertAbility`。
  - 插入 ability 为 `Monster_W1_Soldier03_00_Skill06_Insert_Phase01`，目标为攻击者，优先级来自 `MonsterInsertAttackSelf`。
  - scheduler drain 后执行 standalone ability，并通过通用 ability/damage 链路造成反击伤害。
- 修正 standalone ability 伤害 lowering：
  - 从具体 ability task 降出的 hit profile 只绑定回同一个 task。
  - 避免多段反击的 damage task 与所有 hit profile 笛卡尔组合。
- runtime 不再按 `DamageByAttackProperty` 字面分流 standalone 伤害；改为只看 `DamageEmissionIR` 是否已 admission。

## 样例结果

`validate_v0_282` 结构化选中：

- 中文名：`银鬃尉官`
- 英文名：`Silvermane Lieutenant`
- `entity_ref=monster:1003010`
- `Rank=Elite`
- setup 动作：`monster_skill:100301003`
- 监听状态：`MMonster_W1_Soldier03_00_ListenBeingAttacked`
- 插队 ability：`Monster_W1_Soldier03_00_Skill06_Insert_Phase01`
- 插队优先级：`MonsterInsertAttackSelf`
- 反击伤害 emission：5 条 executable。

执行结果：

- setup 后敌方状态列表出现监听状态。
- 状态详情中存在 `OnAfterBeingAttacked` listener 来源。
- 我方攻击后产生 `queue_enqueue`。
- scheduler drain 后产生 `queue_dequeue` 和反击伤害记录。
- 5 条反击 damage emission 对应 5 条 damage record。
- 样例中我方 HP 从 `1000000` 降到 `997075`。

上述 ID 只作为报告展示；样例选择按结构化谓词筛选，不以固定 MonsterID、技能 ID、文件名或展示名驱动 runtime。

## 已 admission 的范围

- 事件：`damage.hit -> OnAfterBeingAttacked`。
- 条件：我方攻击者、owner 未控制、未破韧、反击计数未用、非假攻击、非后台目标等当前链路所需条件。
- task：`DefineDynamicValue`、`SetDynamicValueByAddValue`、`TurnInsertAbility`。
- 队列：`TurnInsertAbility`，优先级来源为 `PriorityConfig.InsertAbilityPriority`。
- standalone ability：Phase01 触发 Phase02，Phase02 走通用 `DamageEmissionIR` 造成直接伤害。

## 负例与边界

`validate_v0_282` 覆盖：

- 未挂监听状态时不入队。
- 攻击者不是我方时不入队。
- 监听 owner 已破韧时不入队。
- 监听 owner 被控制时不入队。
- 反击计数已用时不入队。
- 攻击者目标缺失时不入队。
- 队列 admission 缺优先级时 listener blocked，state unchanged。
- 表现类 task 只作为 coverage gap，不产生伤害或队列 mutation。

## 验证结果

命令：

```bash
cd hsr_v075_baseline_clean/hsr
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_282 --output-dir /tmp/hsr_v8_monster_counter_v0_282
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_277 --output-dir /tmp/hsr_v8_monster_cards_v0_277_regress
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_278 --output-dir /tmp/hsr_v8_monster_cards_v0_278_regress
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_280 --output-dir /tmp/hsr_v8_monster_executable_v0_280_regress
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_281 --output-dir /tmp/hsr_v8_monster_passive_v0_281_regress
```

结果：

- `compileall` 通过。
- `validate_v0_282` 通过，`ok=true`。
- `validate_v0_277` 通过，`ok=true`。
- `validate_v0_278` 通过，`ok=true`。
- `validate_v0_280` 通过，`ok=true`。
- `validate_v0_281` 通过，`ok=true`。
- v0_282 正例的 setup、attack、drain 三段 source audit 和 replay 均通过。

## 未完成

- 不覆盖 `MonsterID=1003011` 等同模板变体的额外持盾/多动分支。
- 不执行镜头、动画、UI、音效、表现等待类 task。
- 反击 standalone damage 当前不继续分发新的 `damage.hit` listener。
- 怪物完整 AI、固定序列自动出手、波次、召唤、关卡倍率仍未接。

## 距离最小敌方行动纵切还缺

- scheduler 读取怪物卡固定序列，生成敌方动作候选。
- route/推演器枚举敌方目标，不做复杂 AI 目标选择。
- 敌方行动后的队列、反击、死亡、破韧等事件窗口继续扩大 admission。

## 距离完整复刻还缺

- 全怪物技能 ability graph 和状态 callback admission。
- 复杂 AI、阶段内/跨阶段序列、随机、冷却、目标选择策略。
- 波次系统、关卡面板装配、HardLevelGroup/Level 公式。
- 召唤物、assistant、特殊玩法怪物、环境机制。
- 光锥、内外圈遗器及套装机制。

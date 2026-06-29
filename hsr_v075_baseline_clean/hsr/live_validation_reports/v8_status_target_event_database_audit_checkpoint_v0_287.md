# v0_287 状态/目标/事件数据库审计矩阵

## 本阶段完成

- 新增 `simulator_v8_clean_core.tools.validate_v0_287`，只做数据库事实审计，不改变 runtime 行为。
- 构建 Canonical IR / RuleBook 后，工具层读取 TBGD raw JSON，输出以下矩阵到 `/tmp/hsr_v8_status_target_audit_v0_287`：
  - `status_catalog_matrix_v0_287.json`
  - `modifier_add_matrix_v0_287.json`
  - `target_expression_matrix_v0_287.json`
  - `status_callback_task_matrix_v0_287.json`
  - `status_system_gap_matrix_v0_287.json`
  - `implementation_priority_v0_287.json`
  - `validation_summary_v0_287.json`
- 审计范围明确区分主线来源 `Avatar`、`Monster`、`Equip` 与暂不作为下一批 admission 主路径的 `Level`、`BattleEvent`、`Activity`、`GridFight`、`ElationBattle`、`Servant` 等区域。
- 样例选择按结构化字段分类，例如 opcode、target expression kind、callback event、source area；没有按固定角色名、怪物名、技能 ID、文件名或观测值选择。
- 本阶段没有读取 TextMap，没有把 UI 展示名或技能文本用于规则解释。

## 数据库事实摘要

状态表审计：

- 共统计 4 张状态表，3711 条状态记录。
- 聚合类型分布：`Buff=2202`、`Debuff=811`、`Other=698`。
- `StatusConfig`、`AvatarStatusConfig`、`MonsterStatusConfig`、`ILBattleStatusConfig` 均已进入矩阵。
- 矩阵记录了 `StatusType`、`CanDispel`、`ReadParamList`、`TagList`、`ModifierName` 映射和样例来源。

`AddModifier` 审计：

- 共统计 27572 个 `RPG.GameCore.AddModifier`。
- 主线区域数量：`Monster=7855`、`Avatar=3093`、`Equip=1018`。
- 其他高频区域：`Level=7867`、`BattleEvent=5578`、`Activity=986`、`GridFight=686`。
- 当前目标 admission 粗分类：
  - 已在有限上下文支持的单体别名：23175
  - 已在 AddModifier 群体路径支持的群体别名：941
  - 需要目标表达式层：125
  - 常见但还需要目标表达式层的别名：64
  - 召唤物/servant 相关目标：411
  - 其他未 admission 目标：2855
  - 缺目标：1

目标表达式审计：

- 共统计 328206 个目标表达式节点。
- 高频目标别名包括 `Caster`、`ParamEntity`、`ModifierOwnerEntity`、`AbilityTargetEntity`、`LevelEntity`、`AllDarkTeam`、`AllEnemy`、`AllLightTeam`、`SkillTargetEntityList`、`TeamFormation`。
- 建议 admission 批次统计：
  - 当前有限上下文已支持：244108
  - `v0_288_target_expression_core`：8192
  - `v0_288_target_expression_core_aliases`：8575
  - 召唤物或唯一实体系统之后：12516
  - 排序类目标之后：230
  - 更后续目标表达式 admission：54585

状态 callback 审计：

- 共统计 28374 个 callback，覆盖 193 种 callback event。
- 来源区域高频为 `Level=8508`、`BattleEvent=6750`、`Monster=6231`、`Avatar=3517`、`Equip=1116`。
- 高频事件包括 `OnStack`、`OnListenCharacterCreate`、`OnCreate`、`OnDestroy`、`OnEnterBattle`、`OnBeforeHitAll`、`OnAfterAttack`、`OnAfterSkillUse`、`OnBeingBreak`、`OnAfterBeingAttacked`。
- 每个 event 都记录了当前 `StatusEventFamilyIR` 覆盖状态、runtime event source、blocked reason 和样例 source path。

## 当前 v8 已支持什么

- 状态基础生命周期、AddModifier/RemoveModifier 的安全子集、状态详情和来源追踪。
- 已 admission 的状态监听事件族路由，以及 v0_286 中已有底层 mutation 支撑的事件源。
- 行动级目标解析：`single`、`blast`、`bounce`、`aoe`、`self_or_team`。
- AddModifier 里有限目标别名：`Caster`、`ModifierOwnerEntity`、`ParamEntity`、`CurrentActionTarget`、`AbilityTargetEntity`，以及已明确枚举的部分群体目标。
- 状态 callback 可完整进入审计矩阵；runtime 只执行事件源、目标、条件和 task 全链路已 admission 的 listener。

## 确实缺什么

- 通用目标表达式层仍缺失。`TargetSequence`、`TargetFilter`、`Retarget`、`TargetFetch*`、`TargetSort*`、`SkillTargetEntityList`、`TeamFormation`、`ParamEntityList` 等还不能作为通用底层能力安全解析。
- 状态 stack/refresh/chance/失败分支仍是 partial。数据库里 `MaxLayer`、`LayerAddWhenStack`、`Chance`、`SuccessTaskList`、`FailTaskList`、`ResistedTaskList` 都有实际分布。
- duration/tick/expire 和 DoT tick 还没有完整接成状态生命周期主干。
- 控制、抵抗、免疫、驱散仍缺完整判定来源、目标选择和事件 payload。
- 锁血阈值需要 HP pending mutation 重算 ledger，目前不能直接放开。
- 破韧结束、进入/离开战斗等生命周期事件需要单独补真实时机。

## 建议下一阶段顺序

`implementation_priority_v0_287.json` 给出的排序：

1. `target_expression_core`
2. `status_stack_refresh_chance`
3. `duration_tick_expire_and_dot_tick`
4. `break_end_and_common_event_sources`
5. `control_resist_dispel_immunity`

建议 v0_288 先做目标表达式系统。理由是状态附加、callback task、怪物技能和后续角色机制都会依赖目标表达式；这一层可先做只读解析和安全子集 admission，收益大且不会强行造 mutation。

## 验证结果

在 `hsr_v075_baseline_clean/hsr` 下已通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_287 --output-dir /tmp/hsr_v8_status_target_audit_v0_287
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_286 --output-dir /tmp/hsr_v8_regression_v0_286_after_v0_287
git diff --check
```

`validate_v0_287` 输出 `ok=True`，核心断言包括：

- 所有状态表都被统计。
- 所有 `AddModifier` 都按来源区域和目标表达式分类。
- 所有目标表达式记录都进入分类，不静默丢失。
- callback event 都进入事件矩阵，并带当前 event family 覆盖状态。
- 矩阵样例带 source path/evidence。
- blocked/missing 分类带原因或明确 runtime source。
- runtime/core/systems 没有新增 raw TBGD、TextMap、旧 v7、旧 model pack 引用。

## 距离最小可用战斗纵切还缺什么

- 怪物固定序列动作、普通伤害、技能附带状态、反击类状态监听和 mutation-backed 事件源已经能支撑基础敌方行动测试。
- 还需要目标表达式层，才能更可靠地执行复杂附带状态、callback task 和目标重定向。
- 还需要状态 stack/refresh/chance、duration/tick/expire、DoT tick，才能让状态类机制从“能挂上”走向“能按回合正确运转”。
- 控制、抵抗、免疫、驱散、锁血阈值仍不能进入正式执行。

## 距离完整复刻还缺什么

- 全角色数据卡、光锥、内外圈遗器与套装机制。
- 全怪物技能、被动、阶段切换、召唤、波次和关卡倍率。
- 完整状态系统：目标表达式、控制、抵抗、命中、刷新、叠层、驱散、免疫、持续时间、DoT tick 和全部事件族 admission。
- 完整敌方行动推演、波次和关卡环境。
- 资源、护盾、治疗、伤害修改、行动条、队列插队等跨系统监听的更多正负例和来源审计。

# P8-S18 Final Panel And Birth Order

状态：`ready_for_review`

验收结论：通过

## 基线与范围

- 基线：`6b1b6242aab64b201adb23bdd1083365cf4eabae`
- 仅实施并验收 P8-S18；未实施后续阶段。
- 用户已有的 `ARCHITECTURE_BOUNDARY_CONTRACT.md` 和两个 UI 草稿未修改、未纳入本阶段。

## 生产改动

- `build_types.py`：集中定义 base/ratio/flat/resource 类型关系和唯一 Decimal 聚合器。
- `builds/character_assembler.py`、`builds/models.py`、`equipment/models.py`：角色与装备共用类型化属性映射；最终面板必须等于贡献账本重算结果。
- `scenarios/build_state.py`、`scenarios/identity.py`：正式场景入口只装配一次角色构筑；身份校验与出生计划复用同一结果。在任何正式 `UnitState` 生成前完成准入；保留最终展示 panel 与可重算 `stat_pools`；按静态面板与初始资源、provider、startup、OnEnterBattle、完整性校验、timeline 的顺序出生。
- `scenarios/schema.py`、`scenarios/loader.py`：初始 servant 可选择定义中已存在且唯一的出生来源；缺失、未知或歧义时 fail closed。
- `systems/timeline.py`、`systems/scheduler.py`：timeline 在出生阶段按最终 `effective_unit_stat(speed)` 初始化并写一次性标记；Scheduler 识别有效标记后不再初始化。

生产调用链：

```text
ScenarioStateBuilder.build
  -> assemble_character_build
  -> assemble_equipment_build
  -> aggregate_static_stat_contributions
  -> IdentityResolver.validate(reuse assembly)
  -> _plan_formal_character_birth(reuse assembly)
  -> UnitState(final panel + stat_pools + initial HP/resources)
  -> register_dynamic_ability_providers
  -> _apply_startup_ability_effects
  -> _apply_battle_setup
  -> _dispatch_battle_setup_event(OnEnterBattle)
  -> CommittedStateIntegrityGate.require_full
  -> _apply_timeline_setup
  -> TimelineSystem.initialize_action_values(final effective speed)
  -> CombatScheduler.initialize_timeline(valid marker => no-op)
```

任一 selected graph blocked 时，出生计划在 `units = {}` 之前失败；验证证明未调用正式 `UnitState` 构造、provider 注册或 timeline 初始化。召唤物默认不继承装备，只有已装配 owner-binding 可提供对应属性。

## 验收修正

执行层最初的“单次装备装配”谓词只包围了场景外的独立角色装配调用，没有计量正式场景。代码审查发现身份校验、出生规划和 admission 审计会重复重建同一构筑，原证据是假阳性。

验收线程将正式入口改为先生成唯一角色装配结果，身份校验和出生规划只消费该结果；审计用 canonical rebuild 函数继续保留给外部结果校验，不进入内部出生热路径。最终验证直接包围 `ScenarioStateBuilder.build()`，实测角色装配 1 次、装备装配 1 次。

## 验证

- 主验证：`ok=true`，`ready_for_review=true`，28/28 生产契约谓词通过。
- 验收最终运行：退出码 0；内部墙钟 `12.353175s`，峰值 RSS `450252 KiB`，1 GiB 限制内。
- 诊断运行：退出码 1；墙钟 `4.31s`，峰值 RSS `270924 KiB`。失败仅因复用 helper 默认要求历史 blocked sample；改为显式关闭该无关要求后，仅运行失败切片并完成最终运行。
- 执行线程最终运行约 `9.86s`；验收因修复错误计量谓词额外运行一次。没有恢复旧聚合。
- 最终产物：`/tmp/hsr_v8_p8_s18_final_panel_and_birth_order`，4 个 JSON，共 `1768210` bytes；来源 walkback 读取 6 个文件、`1399488` bytes。
- `compileall`：通过。
- `git diff --check`：通过。
- direct：0；S18 主验证已直接贯穿本次修改的装配、出生、事件、timeline 和 Scheduler 路径。
- 未运行：S8/S17 聚合、完整 lowering、S2/P6/P7 完整验证、历史聚合、`validate_v0_209`。

## 未覆盖

- runtime 不读取 build/raw、无内容 ID/名称特判由定向 CodeGraph 生产边界审查确认，不在验证器中制造第二套 gameplay mutation。
- 查询、UI、replay compact、示例内容和养成过程不属于 P8-S18；未读取、未实施。
- P8-S19 未开展。

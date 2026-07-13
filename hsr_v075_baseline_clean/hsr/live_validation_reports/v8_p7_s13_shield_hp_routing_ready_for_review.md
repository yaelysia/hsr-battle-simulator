# P7-S13 一等护盾与 HP 路由待验收报告

状态：`ready_for_review=true`。本报告仅作为统一验收证据索引，不宣告阶段完成，不修改 P7 checklist。

## 本阶段结果

- `UnitState` 新增显式 `shield_instances`；每个实例以 `(shield_id, source_id, source_actor_id)` 派生稳定 `instance_id`，并保存剩余/容量、结构化 stack policy、吸收家族、优先级及其来源、创建事件序号和 source trace。snapshot 顶层 `shield` 仅作为实例汇总视图。
- 新增 `ShieldSystem`。`InitShield/Shield`、`StackShield`、`ModifyShield` 分别映射为 replace-same-source、stack-same-source、modify-same-source，不再把所有 opcode 无条件累加。缺来源、缺策略、修改不存在实例时 blocked、无 Mutation。
- normal damage 由统一 HP route 先遍历已排序护盾实例，再把余量写入 HP；完全吸收时不生成伪 HP Mutation，部分吸收同时生成 shield 与 HP Mutation。每个 damage family 的 absorb/bypass 与护盾优先级均由版本化 Canonical engine rule 决定，runtime metadata 不允许覆盖。
- damage settlement 同时记录 incoming、absorbed、HP damage、逐实例消费、优先级证据及耗尽 id；source frame、击杀归因和 replay 使用路由后的 HP。
- 实例耗尽产生 mutation-backed `shield.exhausted`，并保留 `shield.change`/既有监听别名。事件 payload 可反查 shield Mutation id。
- reducer/unit birth/snapshot codec 已纳入完整 shield instance schema；不完整实例无法进入可信状态。旧 `resources["shield"]` 若存在但没有实例来源，可吸收伤害会原子阻断。
- UI 继续显示 `unit.shield` 汇总，但已改为只读，不再优先读取或提交旧 aggregate resource。

## 结构化验证证据

主验证：

```text
python3 -m simulator_v8_clean_core.tools.validate_p7_s13_shield_hp_routing --output-dir /tmp/p7_review2_s13
```

结果：`ok=true`、`ready_for_review=true`、`rows=13`。

实际覆盖：完全吸收、部分吸收、多实例优先级、replace/stack/modify opcode 策略、耗尽事件、hp-loss 明确绕过、旧 aggregate 无来源阻断、runtime override 阻断，以及同一 effect/source 由两个施放者创建时保持两个独立实例。新增伪造 route rule、伪造 priority rule、Canonical route rule 缺失三个负例，均 blocked、无 Mutation、state unchanged。

输出：

- `/tmp/p7_review2_s13/validation_summary_p7_s13_shield_hp_routing.json`
- `/tmp/p7_review2_s13/p7_s13_shield_hp_routing_matrix.json`
- `/tmp/p7_review2_s13/p7_s13_shield_hp_routing_evidence.json`

## 直接回归与边界

- P7-S12 damage/toughness：`ok=true`、11 rows。
- v0_286 mutation-backed 状态事件：`ok=true`；旧 aggregate shield path 的事件兼容读取仍可审计，但正式护盾事实已迁移到实例字段。
- v0_215 全量真实来源验证总体仍为 `ok=false`，不能作为 S13 通过声明。其真实动态护盾子样例已结构化选出 `InitShield`，确认生成实例 Mutation、shield record、replay 与 source trace；该次运行暴露 shield record 缺 `numeric_evaluation`，随后已补回。该旧脚本其余失败还包括 S12 后未迁移的 amount-stage 断言、S1 后 diagnostic transition 构造以及状态 ledger 旧口径，留待 S19 统一迁移，未为其恢复旧行为。
- `compileall`、`git diff --check`：通过。

## 明确未做

- 未实现角色专属护盾特例，未从技能文本推断叠加或穿透。
- 未让 UI 推导吸收，也未保留双写 aggregate shield 作为第二事实源。
- 未修改 P7 checklist，未提交 Git 检查点。

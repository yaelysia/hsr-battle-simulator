# v8 P1 gap attribution audit checkpoint

日期：2026-07-03

## 结论

本次审计重新检查 P1-9 暴露的未完成项。结论是：之前的 `source_gap_blocked` 口径过粗，不能继续把所有未完成项都叫 source gap。

当前应改成以下分层：

- 真 source gap：raw TBGD 中当前没有对应结构化来源，不能造正例。
- lowering gap：raw TBGD 有来源，但没有完整投影到 Canonical IR / 数据卡 IR。
- admission gap：IR 有来源或候选，但 runtime / RuleBook admission 没有承认可执行。
- validation gap：runtime 可能已能表达，但验证谓词过窄或样例选择不完整。
- implementation missing：真实来源已清楚，但 mutation / settlement / replay / source audit 没实现或不正确。

## 当前 P1-9 结果

重新运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_gap_attribution_p1_9
```

结果：

```text
ok=true
phase1_full_acceptance=false
failed=0
implementation_missing=0
```

P1-9 的底座仍然可验收；本报告只修正“未完成项到底卡在哪一层”的归因。

## 缺口归因

| 项目 | 旧归类 | 本次归因 | 依据 | 下一步 |
|---|---|---|---|---|
| P1-4 stack + duration refresh | source gap | validation gap + lowering/admission gap 待确认 | 当前检查只看 AddModifier task 级 `MaxLayer` / `LayerAddWhenStack` / `IsRefresh` 和 modifier `Stacking=Refresh`。统计显示标准化 AddModifier 46191 条，task 级 stackish 44 条，其中 duration 2 条、refresh source 0 条。但 modifier definition 层存在 `Stacking=Multiple/Refresh/Merge/Prolong` 和大量 `StackProperty`，raw 层还存在 `Count`/`LifeTime` 组合，当前检查没有完整覆盖这些语义。 | 先做 status stacking/refresh raw -> IR 矩阵，确认 `Stacking`、`Count`、`LifeTime`、`StackProperty` 哪些代表状态层数和刷新，再改 lowering/admission/验证。不能继续断言 raw 无来源。 |
| P1-4 random dispel Order=Random | source gap | 真 source gap | raw 扫描 `DispelStatus` 727 条：`Order=LastAdded` 64，`Order=None` 663，`Order=Random` 0。IR 中 `DispelStatus` 1547 条：`LastAdded` 376，`None` 1171，未见 Random。 | 保持 blocked/no mutation。runtime guarded path 可保留，但不能写 positive case。 |
| P1-6 formation sort | source gap | lowering/admission gap | raw 扫描有 `TargetSortByFormation` 151 条；当前 RuleBook/验证按 `AllEnemy.SortByFormation` executable alias 找不到正例。说明 raw 有来源，但目标表达式 lowering/admission 或验证谓词没有接上。 | lower/admit `TargetSortByFormation`，定义 formation order 与 runtime sort record，再补 positive/negative validation。 |
| P1-6 toughness sort | source gap | 当前仍按真 source gap 处理，但需保留复查口 | raw 精确扫描未发现 `TargetSortByStance` / `TargetSortByStanceRatio`，当前 RuleBook 也无 `AllEnemy.SortByStance` / `AllEnemy.SortByStanceRatio` executable alias。 | 先保持 source gap。若后续发现 toughness sort 通过别的 raw 结构表达，再改归因为 lowering/admission gap。 |
| P1-6 owner fetch | source gap | lowering gap | raw 扫描有 `TargetFetchModifierOwner` 6 条，主要来自 `TargetAliasConfig` / level graph；当前 RuleBook target expression 中 `TargetFetchModifierOwner` / `TargetFetchOwner` 为 0。 | lower/admit owner fetch，补 owner context 缺失负例，不能默认 caster/holder。 |
| P1-6 servant target | source gap | admission gap / implementation missing | raw 层含 servant target alias 2266 条。IR 中 servant 相关 target expression 5665 条，其中 blocked 5314、executable 351，但 P1-6 runtime 没有可执行 servant target registry。 | 先建立 servant runtime registry 与 owner/summoner/servant identity，再逐类 admit `GetServant`、`RemoveServant`、`ServantOrSummoner` 等 alias。 |
| P1-7 random source paths | source gap | 需要拆分 | 该 umbrella row 实际包含至少两个面：`random_dispel` 是真 source gap；`control_resist` 是 control metadata 存在但完整 control resist formula/admission 未成形。 | 拆成独立矩阵项。random dispel 保持 source gap；control resist 进入 status/control admission 审计。 |
| P1-8 servant initial setup | source gap | lowering/admission gap | raw 有 `AvatarServantConfig`、servant ability files、NPC/Servant 配置。IR 有 12 个 `ServantDefinitionIR`，全部 blocked，原因是 `servant_owner_stat_timeline_action_source_missing`。 | lower servant stat/source、timeline/source、lifecycle/source、action set，再接 UnitSpawn 或 owner-bound component。 |
| P1-8 battle_unit_summon initial setup | source gap | admission gap + scope split | raw 有 `SummonUnitData`，IR 有 36 个 `SummonUnitDefinitionIR`，全部 blocked。样例原因包括 `summon_unit_destroy_on_enter_battle_not_battle_spawn`、`summon_unit_client_only_not_combat_runtime`，说明当前只有 catalog/visual/adventure 边界，未分清 combat battle unit summon。 | 先区分 adventure/visual summon unit 与 combat battle summon unit；只有 combat admission 清楚后，才能做 initial setup positive case。 |

## 额外未完成项

P1-5 `P1-5-DONE` 仍未勾，不是因为当前聚合验证失败，而是因为当前 P1-9 只把 queue/window 作为 direct contract case 检查，没有强制 route transition 触发真实 follow-up / counter / extra turn / assistant / ultimate window 的跨系统正例。

归因：

```text
validation coverage gap + 部分 admission gap
```

下一步应做 queue family 矩阵：每个 family 分别确认 raw source、IR queue intent、runtime drain、settlement/replay/source audit，而不是用一个聚合 route no-op 代表完整队列系统。

P1-7 `P1-7-DONE` 也仍未勾。当前 RNG 底座可用，但 `control_resist`、`random_dispel` 等应拆开归因，不能继续放在同一个 `random_source_paths` 行里。

## 对第一阶段验收的修正

第一阶段底座仍可验收：

- 有来源的 executable 路径通过。
- blocked/no mutation 约束通过。
- snapshot replay/source audit/settlement traceability 通过。
- runtime 边界检查通过。

但第一阶段 full acceptance 不能验收，且阻塞原因不应再统一写成 source gap。当前更准确的阻塞摘要是：

- 真 source gap：`DispelStatus(Order=Random)`、当前精确 `TargetSortByStance/StanceRatio`。
- lowering/admission/validation gap：stack+duration refresh、formation sort、owner fetch、servant target、servant initial setup、battle_unit_summon initial setup、control resist。
- coverage gap：queue/window 跨系统 route 正例、P1-7 umbrella RNG source matrix 拆分。

## 建议下一步

下一阶段先做“缺口归因收敛”，不要直接扩 runtime 特例。

优先顺序：

1. `P1-GAP-0`：把 P1-9 source gap matrix 改成 gap attribution matrix，字段包含 `raw_source_state`、`lowering_state`、`ir_state`、`runtime_admission_state`、`validation_state`。
2. `P1-GAP-1`：状态 stacking/refresh 专项审计，建立 raw modifier/AddModifier/status instance 语义矩阵。
3. `P1-GAP-2`：目标 system 专项审计，先接 formation sort 和 owner fetch，因为 raw 来源已确认存在。
4. `P1-GAP-3`：servant / battle_unit_summon admission 审计，拆清楚 servant、battle unit summon、summoned monster、adventure summon unit。
5. `P1-GAP-4`：RNG source matrix 拆分，把 random dispel 和 control resist 分开验收。

高 IO 脚本没有运行。本次只运行 P1-9 聚合和轻量 raw/IR 统计脚本。

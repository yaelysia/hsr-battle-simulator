# P8-S14 遗器静态贡献 ready-for-review

## 状态

- 基线检查点：`4bc8dd2`。
- 实施状态：`ready_for_review`，只实施 P8-S14，未勾清单、未提交 Git、未进入 S15。
- 生产代码状态：静态装配、模型不变量和原子阻断已实现，静态检查通过。
- 验证状态：`passed`。规划线程明确授权一次替代最终主验证；修正后的验证器全部谓词满足，进程退出码为 0。

## 生产改动

- `build_types.py`
  - 为真实 raw 属性 `HPDelta`、`AttackDelta`、`DefenceDelta` 增加通用 flat 绑定。
- `builds/relic_set_assembler.py`
  - activation decision 固化 threshold 的静态项索引和 ability source。
- `builds/equipment_assembler.py`
  - 主词条、副词条、active threshold 的每个静态项分别生成 `StaticStatContribution` 和 `EquipmentSourceLedgerEntry`。
  - term ID 稳定编码 relic instance、affix 或 activation decision/property index。
  - unknown property、threshold 身份/来源冲突使整个 assembly blocked，正式通道全空。
  - active ability 仅生成 S15 blocker；inactive ability 不阻断，不创建 dynamic mechanism。
  - 光锥和遗器 contribution、ledger、blocker 独立组装。
- `equipment/models.py`
  - 按 definition/source channel 严格验证 light cone 与 relic。
  - 拒绝额外、缺失、重复、挂错 selection/affix/active threshold 的静态 term 和 ledger。
  - 保留原光锥不变量，并允许无光锥+遗器、光锥+遗器、空遗器。
  - blocked assembly 继续要求所有正式结果通道为空；canonical rebuild 保持更强边界。
- `equipment/__init__.py`
  - 导出遗器套装动态 ability blocker reason。
- `builds/character_assembler.py`
  - 未修改。现有 `assemble_character_build -> assemble_equipment_build -> _panel_from_ledger` 已消费统一账本。

未扩展 `StaticStatContribution`，未修改共享面板聚合器，未引入遗器专用账本。

## Raw 属性核对

| 来源 | 记录数 | property 类型数 |
|---|---:|---:|
| main affix | 117 | 19 |
| sub affix | 48 | 12 |
| set static property | 90 | 19 |
| 去重并集 | - | 23 |

23 个真实类型均有 `static_property_binding`；本阶段补齐的三项是
`HPDelta -> max_hp`、`AttackDelta -> attack`、`DefenceDelta -> defense`，均为 flat。
未从描述文本补值。

## 业务谓词

授权替代最终主验证包含 20 个谓词项：19 项为 `true`，
`dynamic_runtime_effects_started=false` 为预期负值，全部满足。覆盖 main/sub/set
一一对应、inactive 零贡献、高档保留低档、static/dynamic 分离、同属性不预合并、
Decimal 重建、重复消费拒绝、unknown property 原子阻断、精确来源闭合、确定性和零提前
runtime。

修正后的 LC+relic fixture 在替代最终前先由定向切片确认：

```text
ok=true
assembly=assembled
battle=admitted
light_cone=6
relic_main_affix=6
relic_sub_affix=6
static ledger: light_cone=6, relic_main_affix=6, relic_sub_affix=6
diagnostics=[]
```

当前验证器为 793 个非空行，低于执行卡 800 行上限。walkback 只读取 assembly result、
现有 `static_property_binding` 和 RuleBook definition，不重算主副词条或复制生产聚合公式。

## 来源反查

`_walkback` 对选中构筑中的全部 main 6、sub 6、set 1 项逐项验证，结果均为 `ok=true`：

- main：term ID、instance、template/slot/group/affix、level、raw property、exact value、
  canonical affix definition/source 和 static ledger 全部一致。
- sub：term ID、instance/template/group/affix、count/step、definition 的 base/step/step-count、
  raw property、exact value、source 和 static ledger 全部一致。
- set：term ID、active decision、matched/required/contributors、canonical threshold/property
  index、raw property、exact value、threshold/property source 和 static ledger 全部一致。

代表性精确路径：

- main：`relic_main_affix:p8-s14-scattered:0:affix:21:1 -> instance
  p8-s14-scattered:0 -> template 31011 -> affix 21:1 -> level 0 -> HPDelta
  45.1584 -> ExcelOutput/RelicMainAffixConfig.json $[0]`。
- sub：`relic_sub_affix:p8-s14-scattered:0:affix:2:10 -> instance
  p8-s14-scattered:0 -> template 31011 -> affix 2:10 -> count 1/step 0 ->
  StatusProbabilityBase 0.013824001 -> ExcelOutput/RelicSubAffixConfig.json $[9]`。
- set：`relic_set_static:relic_set_activation:outer:101:101:2:property:0 ->
  active 2/2 -> threshold 101:2 -> property 0 -> HealRatioBase 0.1 ->
  ExcelOutput/RelicSetSkillConfig.json
  $[0].PropertyList[0].MNDFOPKBHKP.Value`。

## 资源

| 运行 | 墙钟 | 最大 RSS | 结果 |
|---|---:|---:|---|
| 完整诊断 | 0.50 s | 64,068 KiB | fixture 的 unknown threshold 破坏 RuleBook closure，业务谓词前退出 |
| 完整最终 | 0.50 s | 63,848 KiB | 19/20 预期满足，退出码 1 |
| LC+relic 定向切片 | 0.75 s | 72,932 KiB | 贡献与 static ledger 分区全绿 |
| walkback 定向切片 | 0.72 s | 71,468 KiB | main 6、sub 6、set 1 精确反查全绿 |
| 授权替代最终 | 0.76 s | 72,352 KiB | 全部谓词满足，退出码 0 |

前两次完整运行遵循原执行额度。随后主线程生产审查确认无新生产阻断，并由规划线程明确
授权一次额外替代最终，以验证修正后的 LC fixture 和加强后的 walkback；未进行其他完整
业务重跑。

授权替代最终产物 10,560 bytes；读取 21 个来源文件、1,893,153 bytes；构建 1 次 catalog
和 1 次聚焦 RuleBook；未写完整 Canonical IR/RuleBook，未构建 runtime state。所有运行均
低于 5 分钟、768 MiB、3 MiB 单次预算。

精确 evidence 路径：

- 第一次诊断时间：`/tmp/hsr_v8_p8_s14_time_v_diag.txt`
- 第一次诊断目录：`/tmp/hsr_v8_p8_s14_relic_static_contributions_diag`
- 原最终时间：`/tmp/hsr_v8_p8_s14_time_v.txt`
- 原最终摘要：`/tmp/hsr_v8_p8_s14_relic_static_contributions/summary.json`
- LC+relic 切片：`/tmp/hsr_v8_p8_s14_acceptance_lc_relic_slice.json`
- LC+relic 时间：`/tmp/hsr_v8_p8_s14_acceptance_lc_relic_slice_time_v.txt`
- walkback 切片：`/tmp/hsr_v8_p8_s14_acceptance_walkback_slice.json`
- walkback 时间：`/tmp/hsr_v8_p8_s14_acceptance_walkback_slice_time_v.txt`
- 授权替代最终摘要：`/tmp/hsr_v8_p8_s14_relic_static_contributions_acceptance_final/summary.json`
- 授权替代最终时间：`/tmp/hsr_v8_p8_s14_time_v_acceptance_final.txt`

## Direct 与未运行

- S5 direct：未运行。共享贡献类型和聚合器未改。
- S2 direct：未运行。角色面板求值器未改。
- 未运行 S11-S13、历史阶段聚合、`validate_v0_209`、全 affix property tests、
  scenario、出生顺序、runtime 或套装 ability。
- `compileall`：通过。
- `git diff --check`：通过。

## 剩余阻断

P8-S14 生产静态贡献通道和阶段 evidence 均无已知 blocker。active threshold 的动态
ability 仍按设计保留结构化 S15 blocker，不属于本阶段剩余缺口。

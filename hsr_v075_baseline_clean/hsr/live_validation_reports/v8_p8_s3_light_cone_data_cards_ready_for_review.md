# P8-S3 光锥数据卡与来源关联验收检查点

## 状态

- 执行线程状态：`ready_for_review`
- 验收线程状态：`accepted`（2026-07-15）
- 开工基线：`088b393 feat(v8): complete P8-S2 character build assembly`
- Checklist：P8-S3 已由验收线程标记 `[x]`
- Git：本报告随 P8-S3 检查点提交
- 后续阶段：未开始 P8-S4

本报告只是当前代码、验证谓词和缺口的证据索引，不替代验收线程对真实源码与负例的独立复核。

## 本阶段产物

### 精确光锥定义

- `LightConeDefinitionIR` 已从 S1 占位引用迁移为类型化定义，保存发布状态、显示哈希、命途、稀有度、最大晋阶、最大叠影、SkillID、完整晋阶档、完整叠影档和唯一能力记录来源。
- `LightConePromotionTierIR` 保存晋阶编号、`Promotion` 原字段是否存在、等级上限及六类成长值。缺字段只允许投影为零阶；重复、冲突、缺档或不连续会阻止目录接入。
- `LightConeParameterIR` 和 `LightConeStaticPropertyIR` 分别保存原始项目序号、精确值与字段级 JSON 路径。静态属性不按属性类型合并，重复类型不会被覆盖。
- 每个叠影档保存技能名称哈希、描述哈希、AbilityName、有序参数和有序静态属性，无需后续重新读取 raw 文本表。
- 新增模型的 `from_json` 接受普通 JSON 字典和数组，拒绝未知字段及旧占位字段；解析结果递归不可变，修改原始输入不会改变对象或序列化结果。

### Decimal 与双 fingerprint

- 三张光锥表使用专用 JSON 路径并通过 `parse_float=Decimal` 解析。成长、参数和静态属性投影拒绝 Python `float`，最终以规范十进制字符串进入 IR。
- `source_content_fingerprint` 基于 24 个主来源文件的路径和完整原始字节，文件内容或物理行序改变会改变该指纹。
- `catalog_definition_fingerprint` 基于稳定排序后的规范光锥定义；审计 evidence、JSON 行位置和输入遍历顺序不参与目录语义指纹。
- 两种指纹使用独立字段和独立算法，均进入 lowering metadata；不存在复用目录指纹冒充来源指纹的路径。

### 来源闭环与能力边界

- 正式构建一次读取全部主来源原始字节计算来源指纹，仅对三张光锥表和 15 个装备能力文件进行语义解析。
- 每个 AbilityName 必须在所有装备能力文件的 `AbilityList` 中唯一命中，卡片只保存能力名称、真实文件路径、记录序号和具体 JSON 路径。
- P8-S3 不创建 graph ID、`EquipmentMechanismRefIR` 或第二套装备效果 payload。正式光锥目录的 `mechanism_ref_ids` 全部为空，能力图接通仍属于 P8-S6。
- 生产构建器不读取 S0 summary、`/tmp` 文件、审查状态或固定 hash。S0 summary 仅由验证器 fail-closed 读取，并与实时来源指纹比较。

### 完整目录与原子接入

- 当前 162 张已发布光锥全部为 `lowered`，已发布 blocked 数为 0；该数量只作为当前来源观察值，不是固定通过条件。
- `LightConeCatalogBuildResult.canonical_definitions` 仅在全部已发布卡闭合时返回正式目录。任一已发布卡失败时，诊断定义和问题清单仍保留，但正式目录为空。
- `TBGDLowering.build()` 在其他 lowering 工作开始前构建并强制通过完整目录门；失败抛出携带构建结果的问题，不会产出部分成功 CanonicalIR。
- 通用 `LoweringLimits` 不包含光锥目录限制。截断 EquipmentConfig 的内存负例会因孤立成长和技能记录失败，不能冒充完整目录。

## 主要生产证据

| 目标 | 生产实现 | 失败条件 |
|---|---|---|
| Decimal 精确投影 | `load_light_cone_catalog_sources`、`exact_decimal_text` | 任一投影值经过 float、非有限或非规范十进制时失败 |
| 晋阶闭环 | `_build_promotion_tiers`、`LightConePromotionTierIR` | 重复、缺档、不连续、错误零阶或成长字段损坏时 blocked |
| 叠影闭环 | `_build_superimposition_levels` | rank 重复、缺档、SkillID / AbilityName 冲突或参数 schema 损坏时 blocked |
| 能力记录唯一 | `LightConeAbilitySourceIR`、全局 AbilityList 索引 | 缺失、多候选、错误记录身份时 blocked |
| 双指纹 | `build_primary_equipment_source_fingerprint`、`_catalog_definition_fingerprint` | 来源字节与规范目录语义混用时失败 |
| 原子目录 | `LightConeCatalogBuildResult.canonical_definitions`、`require_complete_light_cone_catalog` | 已发布卡存在 blocked 时正式目录必须为空 |
| RuleBook 查询 | `RuleBook.light_cone_definition` | 非唯一、错误类型、非 lowered 或来源损坏时结构化 blocked |

## 聚焦验证

```text
ionice -c 2 -n 7 nice -n 10 \
env PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
python3 -m simulator_v8_clean_core.tools.validate_p8_s3_light_cone_data_cards \
  --tbgd-root turnbasedgamedata-main \
  --s0-summary /tmp/hsr_v8_p8_s0_equipment_source_inventory/validation_summary_p8_s0_equipment_source_inventory.json \
  --output-dir /tmp/hsr_v8_p8_s3_light_cone_data_cards
```

结果：`ok=true`。五个分区全部通过：正式目录、独立 raw oracle、模型契约、双指纹确定性、原始内存快照负例。

关键结果：

```text
published_cards_all_lowered=true
published_card_blocked_count=0
numeric_values_never_pass_through_float=true
production_does_not_depend_on_validation_artifact=true
ability_source_record_unique=true
equipment_graph_reference_created=false
limited_catalog_cannot_masquerade_as_complete=true
```

负例直接修改 Decimal 解析后的原始内存数据并重新经过完整目录构建，覆盖：重复 EquipmentID、晋阶缺档、重复叠影、float 参数、损坏静态属性、能力记录缺失或重复、限量目录、已发布卡失败后的原子拒绝、陈旧及损坏 S0 summary。重复静态属性类型正例证明项目按序保留而未合并。

验收补强后新增覆盖：

- 无法归属的晋阶身份、叠影身份和缺少 Name 的能力记录均成为目录级 blocker。
- 能力文档路径必须位于 `Config/ConfigAbility/Equip/`、全局唯一、存在于来源指纹且与指纹中的能力文件集合完全一致；伪装成 EquipmentConfig 或未指纹化能力路径均失败。
- raw 数值边界分别拒绝字符串、布尔、对象、Python float、NaN 和 Infinity；规范十进制字符串只允许进入 IR JSON 反序列化。
- `definition_key`、source、source evidence 和 source fingerprint 的未知字段、损坏 stable ID、发布状态与 Release 字段矛盾、晋阶六项属性重排均被模型层拒绝。
- RuleBook 会递归解析光锥携带的机制引用；引用缺失、类型错误、未 lower 或图不存在时，光锥查询结构化 blocked。
- 独立 raw oracle 直接读取 Decimal 源表和能力记录，逐项核对定义、晋阶、成长值、叠影、参数、静态属性、哈希及字段级 JSON 路径；不读取生产 IR 作为期望值，当前完成 42911 项比较、差异为 0。

资源记录：主来源扫描 1 次、三张语义表各解析 1 次、能力文件 15 个、完整 TBGD lowering 0、最小 RuleBook 2、runtime transition 0；matrix 约 5 KB，没有写完整 CanonicalIR、RuleBook 或能力图。

## S1 直接回归

```text
ionice -c 2 -n 7 nice -n 10 \
env PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
python3 -m simulator_v8_clean_core.tools.validate_p8_s1_equipment_type_contract \
  --s0-summary /tmp/hsr_v8_p8_s0_equipment_source_inventory/validation_summary_p8_s0_equipment_source_inventory.json \
  --output-dir /tmp/hsr_v8_p8_s3_s1_regression
```

结果：`ok=true`。S1 fixture 已迁移到新光锥模型，类型化 RuleBook resolution、递归不可变性、来源边界、构筑与装配结果、P4 装备边界行及运行时 `get_type_hints()` 均通过。该脚本顶层的 `real_equipment_directory_lowered=false` 描述 S1 验证自身不读取真实目录，不用于否定 S3 结果。

## 验收线程复核

验收线程没有只采信执行报告，重新审查了生产模型、目录构建、来源指纹、lowering 原子接入和 RuleBook 引用闭合，并独立复现五类历史阻断。复核结果如下：

- 无法归属的晋阶 / 叠影记录、缺少 Name 的能力记录均会阻断完整目录。
- 伪造、重复、越界或未纳入来源指纹的能力文件路径均会阻断目录或模型解析。
- raw 数值字符串、Python float、布尔、对象及非有限 Decimal 均不能进入精确数值投影。
- 嵌套未知字段、损坏稳定身份、发布状态矛盾和晋阶属性重排均被关闭 schema 拒绝。
- 光锥携带不存在的机制引用时，RuleBook 返回结构化 blocked，不再把卡片解析为可用定义。

验收复跑输出位于 `/tmp/hsr_v8_p8_s3_acceptance_fix2/` 和 `/tmp/hsr_v8_p8_s3_acceptance_fix2_s1/`。S3 五个分区全部通过；独立 raw oracle 完成 42911 项比较且差异为 0。另以限量角色 / 怪物 / ability lowering 直接构建 Canonical IR，完整 162 张光锥目录仍被保留并可由 RuleBook 全部唯一解析。`compileall` 与 `git diff --check` 均通过。

## 未运行与资源边界

- 未运行完整 `TBGDLowering.build()`；它会展开与 S3 无关的角色、怪物和能力图 lowering，聚焦验证已直接覆盖目录构建、原子 gate 和最小 RuleBook 查询。
- 未运行 P1-P7 聚合、P4/P6 重验证、`validate_v0_209`、scenario、runtime 或 UI 验证。
- 未写完整 CanonicalIR、完整 RuleBook、能力图或 transition dump。
- 所有验证串行执行，没有并行 source scan 或 lowering。

## 当前 gap 与阶段边界

- 当前光锥卡只完成定义与真实能力记录来源闭合，不代表光锥效果 executable。
- 玩家光锥实例、等级 / 晋阶 / 叠影选择及合法性属于 P8-S4。
- 指定等级静态数值贡献属于 P8-S5。
- 能力图引用、参数绑定、机制 admission 与 runtime 执行属于 P8-S6 及后续阶段。
- 本阶段没有修改角色卡、角色装配器、scenario、runtime 或 UI，也没有进入 P8-S4。

距离最小装备战斗纵切：当前已具备完整光锥定义目录和可审计查询，但尚不能创建玩家实例、计算所选等级贡献或执行光锥能力。距离完整复刻仍缺光锥实例与数值装配、遗器模板 / 词条 / 套装、装备能力图 admission、战斗执行、审计 replay 以及最终端到端构筑验证。

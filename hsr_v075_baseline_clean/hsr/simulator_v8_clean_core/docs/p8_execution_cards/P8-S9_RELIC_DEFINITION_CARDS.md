# P8-S9 遗器模板、部位、域与套装定义执行卡

## 执行配置

- 对应问题：P8-I08 定义部分。
- 硬前置：P8-S4 已验收并形成共同基线；遗器轨从该检查点创建独立 worktree，不依赖 S5-S8。
- 推荐模型：5.6 Terra；若 discovery 发现能力/套装 schema 冲突，升级 5.6 Sol。
- 推荐推理等级：`xhigh`。
- 推荐模式：Goal 模式，目标严格限定为本卡。
- 选择理由：工作量主要是完整数据投影、引用闭合和大量负例，适合长任务；本阶段不进入 runtime，Terra 足够，但不能降到 medium。

## 当前事实与阶段结果

S1 只有遗器、词条、套装的类型占位和 RuleBook 窄查询边界，真实目录仍为空。当前 raw 事实来自 `RelicConfig`、`RelicBaseType`、`RelicMainAffixConfig`、`RelicSubAffixConfig`、`RelicSetConfig`、`RelicSetSkillConfig` 与装备能力文件。计划中的数量仅是历史观察，正式构建必须按当前 source fingerprint 动态发现。

完成后，Canonical IR 拥有完整、类型化、递归不可变的遗器模板、六个实际部位、主副词条分组、套装、套装档位、静态属性和真实 ability 来源目录。每个模板由结构关系确定外圈/内圈域；`BASIC` 与 `CUSTOM` 明确分类；未知模式、缺组、跨域、重复档位或能力歧义 fail-closed。本阶段所有定义状态只能是 `lowered` 或 `blocked`，不创建玩家实例、不激活任何套装效果。

## 本阶段只做

- 建立类型化 `RelicSlot/Domain/Template/MainAffix/SubAffix/Set/Threshold/AbilitySource` 定义；成员使用明确字段，不保存任意 payload。
- 用专用 Decimal JSON 读取器解析数值表，原始数值全程不经过 float。
- 从模板部位与套装成员关系推导 outer/planar domain，不使用 SetID 数段、中文名或 UI 顺序。
- 保留 `SetSkillList/RequireNum` 的数据驱动阈值，不把模型限制为 2/4。
- 完整保存套装档位的静态属性、有序参数和真实 ability record 来源，但不生成 graph ref。
- 区分 `BASIC`、`CUSTOM` 和未知模式；CUSTOM 保留真实结构和用途证据，不静默按 BASIC 准入。
- 将完整目录接入 Canonical IR、JSON round-trip 和 RuleBook 唯一查询。

## 本阶段不做

- 不创建 `RelicInstanceInput` 的正式合法实例，不验证强化等级或占用槽位。
- 不计算主副词条数值，不统计套装，不应用属性，不启动 ability。
- 不读取评分、推荐、TextMap 或攻略作为规则来源。
- 不把 `RelicBaseType` 无部位筛选行当作第七槽位。
- 不固定当前模板、套装、档位或词条数量作为通过条件。

## 类型与来源不变量

1. 定义身份和玩家实例身份严格分离；定义 key 使用命名空间，跨类型同值不能冲突或误解析。
2. 六槽集合由有部位类型的真实记录得出且非空；无部位筛选行单独分类。
3. 每个模板唯一关联 set、slot、rarity、level limit、main/sub group、mode 和真实来源。
4. 套装 domain 由其模板部位集合推导；同一套装跨不兼容域时 blocked。
5. 同一档位的静态属性和动态 ability 可并存，必须分别保留，不能二选一。
6. ability 只证明唯一真实记录来源；本阶段不得伪造 graph identity 或 executable mechanism ref。
7. 输入顺序变化不影响目录排序、fingerprint 或序列化；外部容器修改不影响模型。

## 目标与证据映射

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 完整来源发现 | 六张核心表和全装备能力候选均进入实时指纹，集合防空 | source inventory |
| 六槽正确 | 恰由有部位结构记录投影；无部位行被分类而非槽位 | slot matrix |
| 模板闭合 | 已发布模板一一对应，引用 set/group/slot 均唯一 | template closure matrix |
| 域推导正确 | outer/planar 来自成员 slot 集合，无 ID/名称规则 | domain matrix + renumber negative |
| 套装档位完整 | 阈值、静态属性、参数、ability source 均保留 | threshold matrix |
| 特殊模式诚实 | BASIC/CUSTOM/unknown 分类，unknown blocked | mode matrix |
| 查询与序列化可靠 | RuleBook 唯一类型查询、重复/跨类型冲突 blocked，round-trip 稳定 | query/codec matrix |
| 无提前执行 | graph refs、mechanism refs、runtime mutation 均为空 | boundary probe |

## 拟改文件与关键符号

- `equipment/models.py`、`equipment/__init__.py`：替换 S1 遗器占位模型为正式类型化定义。
- 新增 `tbgd/relic_cards.py`：精确读取、构建、引用闭合和问题分类。
- `tbgd/equipment_inventory_contract.py`：复用生产 source fingerprint，不依赖 S0 `/tmp`。
- `tbgd/lowering.py`、`rules/ir.py`、`rules/rulebook.py`：接入完整目录和窄查询。
- `tools/validate_p8_s9_relic_definition_cards.py` 与阶段报告。
- 原子迁移 S1 fixture；不修改装配器、scenario 或 runtime。

修改前使用 CodeGraph 审查 `RelicTemplateDefinitionIR`、Canonical IR 集合和 RuleBook 查询的调用者。若 S1 类型无法无歧义迁移，删除弱占位而非保留双轨兼容。

## 结构化验收谓词

```text
current_relic_sources_fingerprinted=true
published_relic_templates_all_lowered=true
published_relic_template_blocked_count=0
real_slot_count_derived_from_source=true
filter_row_is_not_slot=true
template_references_unique=true
set_domain_derived_from_membership=true
set_domain_does_not_use_numeric_id_range=true
set_thresholds_data_driven=true
static_and_dynamic_threshold_payloads_both_preserved=true
basic_custom_unknown_modes_classified=true
unknown_mode_fails_closed=true
ability_source_unique=true
equipment_graph_reference_created=false
canonical_round_trip_deterministic=true
rulebook_queries_fail_closed=true
numeric_values_never_pass_through_float=true
```

## Gap 与停止条件

- raw 引用存在但类型模型或 lowering 缺失：`lowering_gap`，本阶段必须修。
- 当前已发布普通模板、套装或档位 blocked：阻断 S9，不得推迟到实例阶段。
- CUSTOM 是否可进入普通玩家构筑由后续阶段 admission 判断；S9 必须完整分类其结构，不能过滤。
- ability record 无唯一候选：来源关联 blocker，禁止伪造图引用。
- 若同一套装真实跨域或出现新 slot/mode，不能硬套当前六槽假设；停止并提交数据事实和设计影响。

## 验证命令与资源

```bash
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p8_s9_relic_definition_cards --tbgd-root ../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s9_relic_definition_cards
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p8_s0_equipment_source_inventory --tbgd-root ../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s9_fresh_s0_inventory
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p8_s1_equipment_type_contract --s0-summary /tmp/hsr_v8_p8_s9_fresh_s0_inventory/validation_summary_p8_s0_equipment_source_inventory.json --output-dir /tmp/hsr_v8_p8_s9_s1_contract_regression
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/hsr_v8_p8_s9_pycache python3 -m compileall -q hsr/simulator_v8_clean_core
git diff --check
```

S1 回归只允许消费本轮刚生成的 S0 summary；生产 S9 lowering 不得读取该 artifact。若 S1 仍把验证 artifact 混入生产边界，应在本阶段迁移为当前生产指纹与验证 artifact 分离契约，不能固定 hash。六张表只做一次 Decimal 解析，能力文件只建立一次身份索引；负例复用内存快照。不得构建完整战斗 RuleBook、执行 ability 或写完整 Canonical IR。

## Ready-for-review 产物

- 当前来源清单、指纹、目录统计和 published/unknown 分类。
- slot/domain/template/group/set/threshold/mode/reference 矩阵。
- 重复、缺引用、跨域、未知模式、伪 ability、陈旧指纹和 codec 负例。
- RuleBook 查询样本、资源统计和明确未执行边界。

## 唯一执行清单（仅验收线程可勾）

- [ ] 当前遗器相关来源完整发现并绑定实时指纹。
- [ ] 模板、六槽、词条组、套装与档位已完整类型化，已发布普通目录零 blocked。
- [ ] 内外圈由结构关系推导，无编号/名称硬编码。
- [ ] BASIC/CUSTOM/unknown 分类及失败边界诚实。
- [ ] 静态与动态档位成员均保留，未伪造 graph 或提前执行。
- [ ] Canonical IR、RuleBook、codec、不可变性和负例经审查通过。
- [ ] `ready_for_review` evidence 完整，阶段无未关闭定义 blocker。

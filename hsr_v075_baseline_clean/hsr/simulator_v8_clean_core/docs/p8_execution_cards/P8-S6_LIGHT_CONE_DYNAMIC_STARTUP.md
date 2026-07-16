# P8-S6 光锥动态能力绑定与启动生命周期执行卡

## 执行配置

- 对应问题：P8-I06、P8-I07 能力入口。
- 硬前置：P8-S5 已验收并形成光锥轨检查点。
- 推荐模型：5.6 Sol。
- 推荐推理等级：`max`。
- 推荐模式：普通聚焦模式，继续使用光锥轨独立 worktree。
- 选择理由：本阶段决定装备内容如何进入通用能力图、原子提交和战斗生命周期，是高风险架构接口；范围应保持聚焦，不适合 Goal 模式顺手扩机制族。

## 当前事实与阶段结果

S3 只建立 `AbilityName -> 真实能力记录`，明确没有伪造 graph identity；S4/S5 只选择实例、叠影参数和静态贡献。开始前必须审查当前 standalone ability lowering 为什么未接纳装备能力，以及 P5 参数绑定、P7 selected graph 原子提交、UnitState 出生和事件注册的真实调用链。

完成后，命途匹配且所选光锥 gameplay 图完整准入时，装配结果包含引用现有 Canonical IR 图的类型化动态机制选择；叠影参数绑定到图中的装备参数读取；UnitState 完成静态出生后只注册一次能力提供者。命途失配、图缺失、候选歧义、参数不闭合或图中任一 gameplay 节点未准入时，正式 battle admission blocked，零注册、零 status、零 mutation。

S6 只建立真实能力图引用、参数绑定和启动生命周期，不承诺图内所有 opcode 已可执行；S7-S8 负责 gameplay family 闭合。

## 本阶段只做

- 扩展通用 ability lowering，使 S3 记录的装备能力来源可以生成真实、稳定、可查询的 Canonical IR 图；不得从名称计算图 ID。
- 将被选叠影的有序参数绑定到图中真实的装备参数读取节点，参数身份包括实例和叠影档位。
- 在 `EquipmentAssemblyResult.dynamic_mechanisms` 中保存图引用、owner/wearer、来源与 admission 结果，不复制能力 payload。
- 明确启动顺序：静态装配完成 -> UnitState 建立 -> 注册 provider/listener -> 按 P7 阶段派发事件。
- 建立 startup idempotency，snapshot、query、rebuild 或 replay 不得重复注册。
- 对命途失配、缺图、重复图、参数越界、partial graph、重复启动和 owner 错绑建立负例。

## 本阶段不做

- 不逐件实现光锥效果，不关闭 S7/S8 family gap。
- 不建立 equipment runtime、装备专用 callback loop 或 ScenarioStateBuilder task 解释器。
- 不执行 unsupported graph 的“已支持部分”。
- 不让 source path、AbilityName、描述文本或日志充当 runtime 行为。
- 不接遗器套装能力。

## 设计与失败不变量

1. 动态选择只引用 Canonical IR 中实际存在的图；来源记录本身不能冒充图。
2. 参数从 S3 叠影行经类型化 binding 进入 P5 ValueResolver，全程不读 raw、不转 float、不靠参数位置猜测缺项。
3. 一个实例的一个激活能力最多注册一次；相同光锥的两个不同 wearer 必须拥有不同 provider identity。
4. 命途失配是 inactive，不是 graph blocked；其基础贡献保留，动态注册为零。
5. 命途匹配后，只要选中 gameplay 图存在 unsupported、歧义或来源断裂，正式 unit 整体不得进入战斗。
6. 启动失败必须遵守 P7 原子提交：state unchanged，不留下半个 modifier/listener。
7. runtime 只消费动态机制选择和 Canonical IR，不读取构筑输入、S3 ability source 或 TBGD。

## 目标与证据映射

| 目标 | 必须成立 | 证据 |
|---|---|---|
| 真实图关联 | 每个 admitted graph identity 在 Canonical IR 唯一存在并回到 S3 ability record | graph linkage matrix |
| 叠影参数绑定 | 同一图在不同叠影只改变绑定值，不改变图身份 | rank pair oracle |
| startup once | 首次启动注册一次，再构建/查询/回放不增量注册 | idempotency matrix |
| 命途失配零动态 | 零 provider、listener、status、mutation，基础贡献保持 | mismatch transition |
| partial graph fail-closed | 任一选中 gameplay 节点不准入，battle blocked、state unchanged | atomic negative |
| owner 隔离 | 两个 wearer 的 provider、参数和 settlement 不串线 | multi-owner fixture |
| 来源闭合 | provider/settlement -> graph -> ability record -> raw path | source walkback |

## 拟改文件与关键符号

- `tbgd/lowering.py` 及现有通用 ability lowering 模块：接纳装备 ability 来源并产生真实图。
- `rules/ir.py`、`rules/rulebook.py`：只补通用图查询和来源关联所缺的类型化边界。
- `builds/equipment_assembler.py`、`equipment/models.py`：产生动态机制选择和 battle admission blocker。
- `builds/character_assembler.py`、`scenarios/build_state.py`：只消费装配结果并在正确阶段注册。
- P5 ValueResolver、P7 executor/event 注册模块：仅在确认通用缺口时修改，必须补直接回归。
- `tools/validate_p8_s6_light_cone_dynamic_startup.py` 和对应报告。

必须先用 CodeGraph 获取实际调用链和 blast radius；若需要新增第二套 ability graph 或事件循环，设计即不合格，应停止。

## 结构化验收谓词

```text
equipment_ability_graphs_are_canonical=true
graph_identity_not_derived_from_name=true
superimposition_parameters_bound_exactly=true
rank_changes_values_not_graph_identity=true
startup_registers_once=true
path_mismatch_registers_zero_dynamic_mechanisms=true
selected_partial_graph_blocks_battle=true
blocked_startup_state_unchanged=true
multi_wearer_provider_identity_isolated=true
runtime_reads_raw_equipment=false
equipment_specific_event_loop_created=false
all_dynamic_sources_walk_back=true
```

注意：`graph registered=true` 不能替代实际来源闭合和原子失败证据，也不表示 S7/S8 完成。

## Gap 与停止条件

- raw 能力记录存在但未 lower 为通用图：`lowering_gap`，本阶段修复。
- 图存在但装备装配器未选择或参数未绑定：`admission_gap`，本阶段修复。
- 图节点语义尚未支持：记录到 S7/S8 family 矩阵，但当前构筑必须 blocked；不得部分执行。
- 检查器按角色/装备名才找到图：`validation_gap`，修正谓词。
- 如果能力来源无法唯一对应通用图，禁止构造占位 graph ref；报告 blocker 并停止提交“可执行入口”。

## 验证命令与资源

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p8_s6_light_cone_dynamic_startup --tbgd-root ../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s6_light_cone_dynamic_startup
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p5_s1_value_binding_contract --tbgd-root ../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s6_p5_value_regression
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p7_s3_selected_graph_atomic_commit --output-dir /tmp/hsr_v8_p8_s6_p7_atomic_regression
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p7_s9_explicit_turn_event_phase_machine --output-dir /tmp/hsr_v8_p8_s6_p7_phase_regression
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/hsr_v8_p8_s6_pycache python3 -m compileall -q hsr/simulator_v8_clean_core
git diff --check
```

若未修改 P7 event/executor，可用 S6 主验证内的 focused 原子矩阵替代其中一个重回归，但报告必须说明覆盖等价关系。只建立一次 focused ability index/RuleBook；不运行全光锥 transition、阶段聚合或 `validate_v0_209`。

## Ready-for-review 产物

- graph 来源关联和参数绑定矩阵。
- startup once、命途失配、partial graph、multi-owner 负例。
- 一条 provider/settlement 到 raw ability record 的来源反查。
- 当前仍由 S7/S8 承接的 family gap 总表，不得写成 source gap。
- 代码 blast radius、验证结果、资源统计和未运行验证说明。

## 唯一执行清单（仅验收线程可勾）

- [x] 装备能力已引用真实 Canonical IR 图，未伪造 graph identity 或复制 payload。
- [x] 叠影参数通过通用 ValueResolver 精确绑定且来源完整。
- [x] 静态出生后只注册一次，owner 与多 wearer 隔离正确。
- [x] 命途失配和所有 partial/伪来源路径均零动态、state unchanged。
- [x] S7/S8 未支持 family 被诚实保留为 battle blocker，没有部分执行。
- [x] P5/P7 直接回归和人工代码审查通过。
- [x] `ready_for_review` evidence 完整，阶段无入口层 blocker。

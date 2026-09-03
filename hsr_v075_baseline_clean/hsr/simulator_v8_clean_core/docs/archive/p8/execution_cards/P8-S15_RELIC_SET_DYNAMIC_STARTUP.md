# P8-S15 套装动态能力绑定与启动生命周期执行卡

## 执行配置

- 对应问题：P8-I13 能力入口。
- 硬前置：P8-S14 已验收并形成遗器轨检查点。
- 推荐模型：5.6 Sol。
- 推荐推理等级：`max`。
- 推荐模式：普通聚焦模式，遗器轨独立 worktree。
- 选择理由：与 S6 相同，这是内容进入通用能力图和战斗生命周期的高风险边界；必须聚焦完成入口，禁止顺手做 S16/S17 效果覆盖。

## 当前事实与阶段结果

S9 保存套装档位的 `AbilityName`、有序参数和真实能力记录，S13 选择激活档位，S14 装配静态属性；动态档位仍不应产生机制。开始前应复用 S6 已验收的通用装备 ability graph 与 startup provider 模型，审查是否能以套装 threshold 作为 provider source，而不是创建第二套 relic callback 系统。

完成后，每个满足门槛且图完整准入的动态档位产生一个引用 Canonical IR 图的机制选择，参数来自档位行，owner 为 wearer，作用目标仍由图定义。二件/四件分别注册一次，2+2 的两个二件能力分别注册。静态面板完成后、战斗事件前注册 provider；未达门槛、替换失活、参数缺失、图歧义或 partial graph 时零部分效果，正式 battle admission blocked。

## 本阶段只做

- 将套装档位 ability source 关联到 S6 建立的通用 Canonical IR 图；不复制图 payload。
- 将档位有序参数绑定到真实 dynamic value 节点，参数 identity 包含 set/threshold/wearer。
- 从 S13 activation decisions 选择 provider；不得在战斗中重新统计套装。
- 确保同套低/高档、两个 2-piece、多个 wearer 的 provider identity 独立且启动一次。
- 按统一顺序注册：静态装配完成 -> UnitState 建立 -> provider 注册 -> P7 OnStart/OnEnterBattle 派发。
- 对未达阈值、替换后失活、重复启动、缺参数、伪图、partial graph 和 target owner 错绑建立负例。

## 本阶段不做

- 不承诺全部套装 gameplay family 可执行；S16/S17 闭合。
- 不在 set counter/assembler 直接执行 modifier、资源或行动效果。
- 不创建 relic/set 专用事件循环、callback registry 或 ID switch。
- 不在最终面板形成前派发入场事件。

## 设计与失败不变量

1. provider 只由已激活 threshold 产生；未激活 threshold 连 blocked graph 都不应注册。
2. 档位参数来自 S9 定义，禁止从描述、source path 或 fixture metadata 提取。
3. 同一 threshold 对同一 wearer 只注册一次；snapshot/query/replay 不重复添加永久 modifier。
4. 图中任一选中 gameplay 节点未准入时，整个正式构筑 battle blocked，静态只读装配结果可保留但不能生成可战斗 UnitState。
5. 多 wearer 的 provider、owner、target attribution 和参数绑定隔离；队伍效果仍由图执行。
6. 替换遗器导致 threshold 失活时，新装配结果不含旧 provider；战斗中禁止换装。
7. runtime 只读取装配选择和 Canonical IR，不读取 set count、raw 或描述。

## 目标与证据映射

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 三类档位来源 | static-only、dynamic-only、both 均按结构选出并行为正确 | payload class matrix |
| threshold 控制注册 | active 一次、inactive 零次，低/高档互不覆盖 | registration matrix |
| 2+2 正确 | 两个不同二件 provider 均唯一注册 | two-plus-two case |
| 参数精确绑定 | 值与档位 Decimal 参数一致，图身份不随值变化 | parameter oracle |
| startup 时序/幂等 | 面板后注册，事件阶段触发，重放不重复 | phase/idempotency matrix |
| partial fail-closed | unsupported graph 导致 battle blocked、state unchanged | atomic negative |
| 来源闭合 | provider -> threshold -> ability graph/record -> raw | source walkback |

## 拟改文件与关键符号

- 复用 S6 的通用 equipment ability lowering、mechanism selection 和 provider registry。
- `builds/equipment_assembler.py`：由 set activation 生成动态选择和 blocker。
- `equipment/models.py`：仅补 set threshold source/binding basis 所缺类型。
- `builds/character_assembler.py`、`scenarios/build_state.py`：消费统一 provider，不增加 relic 分支。
- `tools/validate_p8_s15_relic_set_dynamic_startup.py` 和阶段报告。
- S6、S13、S14 fixture/codec 原子迁移。

开始前用 CodeGraph 比较光锥 provider 与预期套装 provider 调用链。如果实现要求复制 S6 逻辑，应先抽取通用机制提供者，而不是平行实现。

## 结构化验收谓词

```text
set_abilities_reference_canonical_graphs=true
set_parameters_bound_from_threshold_rows=true
inactive_threshold_registers_zero=true
active_threshold_registers_once=true
lower_and_higher_threshold_providers_distinct=true
two_plus_two_providers_distinct=true
multi_wearer_providers_isolated=true
startup_after_static_panel=true
startup_replay_idempotent=true
selected_partial_graph_blocks_battle=true
blocked_startup_state_unchanged=true
runtime_recounts_sets=false
relic_specific_event_loop_created=false
all_provider_sources_walk_back=true
```

## Gap 与停止条件

- ability record 有来源但无 Canonical graph：`lowering_gap`，复用/扩展 S6 通用 lowering。
- 图有但 threshold 未绑定/参数未接：`admission_gap`，本阶段修。
- 图节点 unsupported：归 S16/S17 family 矩阵，完整构筑继续 blocked；不得部分执行。
- 若多个 threshold 共享 ability name 但参数/来源无法唯一绑定，禁止按文件顺序取第一项。
- 发现 S6 provider 模型只适用于光锥名称/实例，必须先通用化并跑 S6 回归。

## 验证命令与资源

生产边界先保证：正式装配器/provider 只接纳已激活、完整且来源唯一的套装档位；部分图、参数错绑、重复注册或身份不一致必须在启动事件前 blocked。幂等性由生产注册表和事件阶段契约保证，不能靠验证器去重。

本阶段固定只运行一个业务主验证：

```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/time -v -o /tmp/hsr_v8_p8_s15_time_v.txt timeout --signal=TERM 8m ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p8_s15_relic_set_dynamic_startup --tbgd-root ../../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s15_relic_set_dynamic_startup
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/hsr_v8_p8_s15_pycache python3 -m compileall -q simulator_v8_clean_core
git diff --check
```

- 主验证只建立一次聚焦套装 ability index/RuleBook，证明来源绑定、provider 注册、阶段顺序和幂等性；不执行全套装 transition。
- 已验收的 S6、S13 和 P7 阶段机结论直接继承。只有实际修改共享 equipment provider/graph lowering 时追加一个 S6 provider direct；只有修改通用事件阶段机时追加一个 P7 phase direct。direct 总数最多 2。
- 完整主验证最多一次诊断运行和一次最终运行；中间修复只跑失败的 provider/phase 切片。
- 单次主验证预算：墙钟 8 分钟、峰值 RSS 1 GiB；阶段累计验证预算 15 分钟；默认产物不超过 5 MiB。超限立即暂停。
- 不运行 S13 整体验证、全套装 transition、P7 聚合、旧九族聚合或 `validate_v0_209`，不写完整能力图/RuleBook dump。

## Ready-for-review 产物

- payload class、threshold/provider、2+2、多 wearer 和参数绑定矩阵。
- startup phase/idempotency、partial graph 和替换失活负例。
- provider 到 raw threshold/ability 的来源反查。
- S16/S17 接手的准确 family blocker 总账。
- 通用化 diff、S6/P7 回归与资源统计。

## 唯一执行清单（仅验收线程可勾）

- [x] 套装档位只引用真实 Canonical graph，参数来自真实 threshold 行。
- [x] active/inactive、低/高档、2+2 和多 wearer 注册身份正确且幂等。
- [x] 静态面板后注册，runtime 不重算 set count。
- [x] partial/伪来源/缺参数完整阻断，零部分状态和 mutation。
- [x] 复用 S6/P7 通用机制；其契约未被实际改动，或已通过对应最小 direct；无套装专用事件循环或 ID 特判。
- [x] S16/S17 family gap 诚实保留，来源反查完整。
- [x] `ready_for_review` evidence 完整，阶段无能力入口 blocker。

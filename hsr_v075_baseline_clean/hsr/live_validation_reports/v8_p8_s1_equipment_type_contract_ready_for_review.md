# P8-S1 类型化装备与构筑架构 ready_for_review

## 状态

- 执行线程状态：`ready_for_review`
- 验收线程状态：`accepted`
- Checklist：已由验收线程勾选 P8-S1
- Git：随本次 P8-S1 验收检查点提交
- 后续阶段：未开始 P8-S2
- runtime / scenario schema / UI：未修改
- 真实装备目录 lowering、装备数值、槽位 / 词条 / 套装合法性、机制启动：均未实现

本报告是证据索引，不是独立完成证明。验收线程已复核当前源码、聚焦验证谓词和独立负例，P8-S1 通过验收。

## 本阶段产物

### 共享来源基础类型与单向依赖

- 根模块 `ir_types.py` 下沉既有 `JSONValue`、`CoverageStatus`、`IRSource`；根模块 `immutable_json.py` 承载递归冻结实现，`core/immutable_json.py` 只保留兼容重导出。
- `equipment/models.py` 只依赖上述根基础模块；`rules/ir.py` 在运行时导入正式装备定义类型，因此 `get_type_hints()` 可完整解析 `CanonicalIR` 和既有 IR。
- 依赖方向为基础类型 / 不可变 JSON → 装备模型 → Canonical IR → RuleBook；没有使用 `Any`、重复来源模型、`TYPE_CHECKING` 占位或延迟导入掩盖循环。

### 类型化定义、查询和每次构筑数据

- 正式定义键为 `EquipmentDefinitionKey(definition_kind, definition_identity)`；不同类型可合法复用同一 raw 身份。
- CanonicalIR 只增加角色装备资格、光锥、遗器模板、词条、套装、套装档位和机制引用七类定义集合。
- 玩家光锥 / 遗器实例、构筑输入、激活决策和装配结果位于 `equipment/models.py`，不进入 CanonicalIR。
- RuleBook 新增按定义类型收窄的查询；正式返回 `EquipmentDefinitionResolution[T]`，不返回宽泛字典。
- `resolved` 强制一个正确类型的 value 和一个候选；`blocked` 强制 `value=None`，并稳定排序诊断候选。
- `resolved` 模型自身还强制 value 处于可解析 coverage，且候选的规范键、具体对象类型和来源与 value 完全一致；直接构造和 `from_json` 不能伪造查询来源。
- RuleBook 按 CanonicalIR 字段声明的目录类型建立索引，不信任对象自报类型；目录错放、规范键损坏、资格 owner 不符和未 lower 定义均结构化 blocked。
- 机制引用只保存已有通用 ability graph 身份和参数绑定身份，不保存第二套效果 payload。

### P4 边界迁移

- 删除 `character_cards.py` 中旧 `card_contract.equipment_boundary` 字符串声明。
- `CharacterDataCardIR` 增加类型化 `equipment_eligibility_id`，当前正式构建路径使用默认空引用。
- RuleBook 对当前未绑定角色卡返回 `character_equipment_eligibility_unbound`，不合成通用资格。
- P4 原矩阵行 ID `equipment_build_input_hook_boundary` 保留；公开 row builder 和 row validator 同时检查源码、生成卡、类型化字段、blocked 查询、scenario flags/resources 和 setup mutations。

## 强制约束与证据映射

| 约束 | 代码 / 验证证据 | 通过条件 |
|---|---|---|
| 类型化查询结果 | `EquipmentDefinitionResolution[T]`、RuleBook 七类窄查询 | resolved 单值单候选、value coverage 可解析、候选类型 / 来源与 value 一致；blocked 无 value，候选稳定 |
| CanonicalIR 仅定义 | `CanonicalIR` 七个定义集合；`canonical_definition_boundary` | dataclass 与 JSON 均无实例、构筑、激活、装配字段 |
| 无循环依赖 | `ir_types.py`、根 `immutable_json.py`、`rules/ir.py` 的运行时类型导入 | import、compileall 与全部 IR `get_type_hints()` 通过 |
| 类型命名空间身份 | `EquipmentDefinitionKey`、RuleBook multimap | 光锥与遗器同 raw 身份分别 resolved；错请求类型 blocked |
| 当前资格未绑定 | `CharacterDataCardIR.equipment_eligibility_id=""`、P4 原矩阵行 | 当前未绑定查询稳定 blocked；仅 fixture 可 resolved |
| 来源验证语义收紧 | `validate_equipment_source_fingerprint`、`make_equipment_source`、`_require_equipment_source` | 缺字段、非十六进制摘要、文件数与路径数不符、非字符串 `json_path`、错对象、空身份、可变 evidence、来源提权字段均由生产模型拒绝 |
| blocked 装配不变量 | `EquipmentAssemblyResult` | blocked 静态 / 动态通道为空且不能携带 active 决策；候选只在 diagnostics |
| S1 输入范围 | `EquipmentBuildInput` 及实例模型 | 无角色等级 / 晋阶 / 行迹 / 星魂 / 最终面板；不执行合法性 |
| P4 完整矩阵行 | public row builder + public validator | 七项检查全部为真且原 row ID 保留 |
| S0 fail-closed | `load_s0_summary_fail_closed` | 缺文件、非对象、schema 错、ok 非真、指纹缺失 / 畸形均拒绝 |

来源边界只证明结构、不可变性和非行为用途。S0 主指纹作为前置审计指纹使用，不证明任意 fixture `source_path` 是真实 TBGD 节点；来源账本不参与 RuleBook 候选选择或激活。

## 聚焦验证结果

主命令：

```text
env PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p8_s1_equipment_type_contract \
  --s0-summary /tmp/hsr_v8_p8_s0_equipment_source_inventory/validation_summary_p8_s0_equipment_source_inventory.json \
  --output-dir /tmp/hsr_v8_p8_s1_equipment_type_contract
```

结果：`ok=true`、`ready_for_review=true`。

聚焦负例直接构造原始 CanonicalIR / 定义 / 构筑对象并重新建立 RuleBook 或模型，不修改生成后的计数摘要。覆盖：空目录、缺定义、错请求类型、跨目录错放、重复 / 损坏规范身份、资格 owner 错配、未 lower 定义、缺通用 graph、错误 resolved value 类型、resolved 包装 blocked 定义、候选伪造对象类型或来源（直接构造与 `from_json`）、blocked 携带 value、公开模型嵌套成员错类型或可变列表、blocked 非空贡献或 active 决策、生产来源指纹非十六进制 / 数量不一致、整数 `json_path`（直接构造与反序列化），以及 S0 摘要 fail-closed。另对 `rules.ir` 内全部 dataclass 执行运行时 `get_type_hints()`。

聚焦产物：

```text
/tmp/hsr_v8_p8_s1_equipment_type_contract/validation_summary_p8_s1_equipment_type_contract.json
/tmp/hsr_v8_p8_s1_equipment_type_contract/p8_s1_equipment_type_contract_matrix.json
/tmp/hsr_v8_p8_s1_equipment_type_contract/p8_s1_equipment_query_negative_matrix.json
```

产物合计约 100 KiB；未写完整 CanonicalIR、RuleBook 或 transition dump。读取一次 S0 summary，TBGD source read / lowering / runtime transition 均为 0；小型 RuleBook 构建 9 次、scenario builder 样本 1 次，全部串行。

相同 S0 summary 另输出到 `/tmp/hsr_v8_p8_s1_equipment_type_contract_repeat`，summary、类型矩阵和查询负例矩阵逐文件 `cmp` 一致。

## 直接回归与静态检查

```text
env PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p6_s0_architecture_boundary_ledger \
  --output-dir /tmp/hsr_v8_p8_s1_p6_static_boundary
```

结果：`ok=true`，25 行、0 violation、5/5 问题覆盖。首次运行暴露 P6 账本仍要求旧的 `card.source.evidence` 动态值 token；当前实现早已使用类型化 `card.dynamic_value_bindings`。本阶段只更新该静态 evidence token 和说明，未改变运行行为，复跑通过。

```text
env PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p6_s4_s5_boundary_static \
  --output-dir /tmp/hsr_v8_p8_s1_p6_s4_s5_boundary_static
```

结果：`ok=true`，6 行；`boundary_guard=5`、`audit_only=1`。

```text
env PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p7_s2_mutation_reducer_contract \
  --output-dir /tmp/hsr_v8_p8_s1_p7_s2_mutation_reducer_contract
env PYTHONPATH=.:./hsr PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p7_s18_compact_semantic_state \
  --output-dir /tmp/hsr_v8_p8_s1_p7_s18_compact_semantic_state
```

结果：Mutation reducer `14/14`、9 类冲突覆盖；紧凑语义状态 5 行，`ok=true`、`ready_for_review=true`。紧凑状态验证器运行时需要同时暴露包根和 UI 根，因此显式设置 `PYTHONPATH=.:./hsr`；未修改验证器或运行时行为。

```text
env PYTHONPYCACHEPREFIX=/tmp/hsr_v8_p8_s1_pycache python3 -m compileall -q hsr/simulator_v8_clean_core
git diff --check
```

两项均通过。新增未跟踪 Python 文件另行扫描尾随空白，无命中。

未运行 P1-P7 聚合、P6 全阶段聚合、全量 TBGD lowering、完整 RuleBook 构建、runtime/replay 重验证；本阶段没有触达相应执行链，运行它们会超出 S1 聚焦范围。

## 当前边界与后续缺口

当前只具备类型化定义、查询、构筑数据和失败边界。距离 P8 最小可用构筑纵切，仍至少缺 P8-S2 起的正式角色构筑输入、基础面板、光锥 / 遗器 lowering、数值与合法性、装配器、最终面板和 runtime 出生链；距离完整复刻还缺全部装备机制族、套装机制、审计 / snapshot / replay、全量覆盖与最终聚合。

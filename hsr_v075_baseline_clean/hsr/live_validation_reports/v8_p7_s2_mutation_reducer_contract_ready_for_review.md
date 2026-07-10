# v8 P7-S2 Mutation 前置条件与 reducer 冲突检测 ready_for_review

## 阶段边界

本 evidence 包只覆盖 `P7-S2`。执行线程没有修改 P7 checklist，没有宣告阶段完成，也没有提前实现 P7-S3 所选执行图原子提交。

当前提交状态：

```text
p7_s2_ready_for_review=true
p7_all_fixed=false
p7_done_eligible=false
```

## 核心结果

`Mutation` 现在显式区分值与路径存在性：

```text
before + before_exists
after  + after_exists
```

因此缺失键和“键存在但值为 null”不再共用隐式含义。存在性字段进入 `stable_id()` 和序列化结果；旧式宽松 Mutation JSON 不再被兼容。

当前明确支持三种 op：

```text
set     -> 对已有状态字段赋值，或按 before_exists 明确创建/更新映射键
delete  -> 删除已有映射/队列键，after_exists 必须为 false
spawn   -> 只允许作用于 units/<unit_id>，before 必须不存在
```

生产侧原先使用 `set + after=None` 表示删除、使用 metadata 区分单位出生的路径已经迁移。单位出生 payload 必须完整描述生成后的 `UnitState`，不能依赖 reducer 默认填充字段。

### Mutation 不可变边界

`Mutation.__post_init__()` 会对 before、after 和 metadata 做递归防御性冻结，并在创建时缓存 stable ID：

- 原始 dict/list 后续被外部修改，不会改变 Mutation。
- Mutation 的嵌套 dict/list 通过普通写入、append/update 等接口不可修改。
- `to_json()` 每次返回独立的可变副本，修改导出结果不会反向污染 Mutation。
- stable ID 在 Mutation 创建时确定，不再根据之后的可变对象动态重算。
- reducer 写入 BattleState 前会递归 thaw 为新的状态对象，不把 Mutation 内部容器或调用者原始容器直接放入状态。

运行时别名污染负例同时修改了原始 before、after、metadata 和 `to_json()` 导出副本，并尝试直接修改 Mutation 嵌套值；Mutation JSON、stable ID 和已提交 BattleState 均保持原值。

### 单一 UnitState codec

单位完整 payload 的字段集合、数字规范、范围校验、JSON 深拷贝和编解码现集中在：

```text
core/unit_state_codec.py
```

`reducer`、`UnitLifecycleSystem.spawn_mutation()` 和 `UnitSpawnPlan.to_unit()` 均调用该 core 契约。`unit_spawn` 只保留出生请求、来源绑定和卡片归属校验，不再复制 UnitState 字段转换规则；旧 `_unit_payload`、`_unit_from_payload`、`unit_from_payload` 定义为零。

## reducer 契约

`MutationReducer.apply_all_result()` 逐条执行以下检查：

- op 是否受支持。
- path 是否属于明确的 BattleState / UnitState / mapping / queue 路径形态。
- 当前路径存在性是否等于 `before_exists`。
- 当前值与 before 是否类型严格相等。
- after 是否符合目标路径的类型和 op 存在性规则。
- 写入后重新读取该路径，确认实际存在性和值等于声明的 after。

比较不经过字符串化：`bool`、`int`、`float`、缺失路径和真实 `None` 均保持不同身份；tuple 只在 BattleState 存储边界按明确 JSON codec 投影为 list。

同批 mutation 在候选状态中按顺序校验。后一条同路径 mutation 只有在 before 精确衔接前一条 after 时才合法。冲突包含 mutation index/id、path、op、期望/实际存在性和值，以及前一条同路径 mutation 的 index/id。

任一冲突返回：

```text
ok=false
after_state=输入 state
applied_count=0
conflicts=[结构化冲突]
```

生产便捷入口 `apply_all()` 也必须经过同一个严格入口；冲突时抛出的 `MutationConflictError` 携带完整 `MutationReductionResult`。不存在继续使用旧宽松 writer 的公开旁路。

## replay 契约

`replay_snapshot()` 不再只写入 after 后比较快照。它先严格验证整条 before/存在性/op 链，再用类型严格的快照比较验证最终 after。

当前能检出：

- 被篡改的 before。
- 同路径 mutation 顺序变化。
- 被篡改的 after。
- 预期快照中的 bool/int 类型替换。
- reducer 的路径、op 和存在性冲突。

`ReplayResult` 同时输出 `errors` 和结构化 `conflicts`。既有 `tools.snapshot_replay` 也已把 conflict 明细纳入结果。

## 生产调用方迁移

本阶段只迁移 Mutation 表达和前置条件，没有改战斗公式。触达的生产域包括：

- 单位出生和生命周期记录。
- break flag、break 来源及恢复清理。
- 状态明细和 dynamic value store。
- 资源、护盾和机制条映射键。
- queue 创建、入列、出列和 summon cleanup。
- timeline、pending turn end、enemy sequence cursor。
- summon runtime、wave runtime 和 battle outcome。

结构化 AST 审计扫描 `core/` 与 `systems/`：

```text
python_files=44
mutation_constructor_sites=77
parse_errors=0
invalid_literal_ops=0
legacy_set_after_none_sites=0
legacy_unit_root_set_sites=0
positional_constructor_sites=0
```

这项静态证据只证明生产构造点没有保留已知旧表达；实际 before/op/原子性结论由运行时反例验证提供，不以源码字符串存在作为通过依据。

## P7-S2 轻量主验证

命令：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p7_s2_mutation_reducer_contract --output-dir /tmp/hsr_v8_p7_s2_mutation_reducer_contract
```

结果：

```text
v8 p7_s2_mutation_reducer_contract ok=True cases=14/14 conflicts=9
```

输出：

```text
validation_summary_p7_s2_mutation_reducer_contract.json
p7_s2_mutation_reducer_matrix.json
p7_s2_mutation_reducer_cases.json
```

十四类实际检查包括：

- 正常连续 mutation 链。
- 错误 before 导致整批回滚，且生产异常携带结构化结果。
- 同路径 before 不连续冲突。
- 非法 op。
- 非法路径。
- 错误 after 类型和存在性。
- 缺失路径与真实 null 的正反例。
- 显式 delete 及删除缺失路径负例。
- 真实 `UnitLifecycleSystem.spawn_mutation()` 产生 spawn，重复出生被拒绝。
- Mutation 原始输入、内部容器和序列化副本的别名污染负例。
- UnitState codec round trip、数字规范、缺字段、多字段、非法范围和单一定义位置。
- before、顺序、after 和快照类型篡改 replay。
- 生产 Mutation 构造点 AST 审计。
- 既有 snapshot replay helper 直接回归。

覆盖到的结构化冲突码：

```text
before_presence_mismatch
before_value_mismatch
invalid_after_presence
invalid_after_type
invalid_delete
invalid_op
invalid_op_path
invalid_path
same_path_before_value_mismatch
```

## P7-S1 直接回归

命令：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p7_s1_transition_trust_contract --output-dir /tmp/hsr_v8_p7_s1_after_p7_s2_fix
```

结果：

```text
v8 p7_s1_transition_trust_contract ok=True committed=committed blocked=blocked diagnostic=diagnostic unclassified=diagnostic
```

这证明 S1 当前五类 transition outcome、contract、replay、source audit 和 scheduler/UI outcome 消费口径没有因 reducer 收紧而退化。

## 验收反馈直接回归

三项触达系统回归均以 `ionice -c3 nice -n 15` 串行运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p1_1_unit_lifecycle --output-dir /tmp/hsr_v8_p1_1_after_p7_s2_fix
PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p1_4_status_system --output-dir /tmp/hsr_v8_p1_4_after_p7_s2_fix
PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p1_2_wave_system --output-dir /tmp/hsr_v8_p1_2_after_p7_s2_fix
```

结果：

```text
v8 p1_1_unit_lifecycle validation ok=True
v8 p1_4_status_system validation ok=True
v8 p1_2_wave_system validation ok=True
```

P1-1 未知单位负例现在检查结构化 `invalid_path`、mutation index/path、`applied_count=0` 和原状态不变，不再期待 `KeyError`。

P1-4 stack cap case 在每次叠层前保存 `before_last_stack`，最后一次 result 使用真实的直接前驱状态构造 transition 和 replay；evidence 输出 `before_last_stack_snapshot`，不再从第一次叠层后的旧状态重放最后一次 mutation。

P1-2 用于确认统一 UnitState codec、新增完整 `statuses` 字段和出生数值规范未破坏波次出生链路。

## 编译与格式检查

定向 `compileall` 覆盖本阶段修改的 core、systems 和 tools 文件：通过。

`git diff --check`：通过。

## 资源预算

P7-S2 主验证：

```text
tbgd_read_count=0
full_rulebook_build_count=0
minimal_in_memory_rulebook_build_count=1
large_artifacts_written=false
full_transition_dump_written=false
```

P7-S2 主验证只输出 compact summary/matrix/case evidence。三项必要旧回归串行执行并只写 `/tmp`，目录规模分别约为：

```text
P1-1  80K
P1-2  7.8M
P1-4  110M
```

没有运行 P1-5；该脚本已知会默认写出约 1.6GB 结果，不作为普通 S2 回归入口。

## 未运行

- P1-P6 聚合及 P1-5：只运行了验收反馈直接触达的 P1-1、P1-2、P1-4；P1-5 已知大产物风险且当前旧失败归后续 P7 阶段。
- `validate_v0_209`：未修改 direct damage、crit 或 RNGEvent schema。
- UI 全量验证：未修改 UI/query-submit，既有 `enemy_ai_auto_skip` 属 P7-S8。
- 全量 TBGD discovery / canonical IR / coverage / fidelity 写出：本阶段没有来源扫描需求。

## Deferred

P7-S2 保证的是“每次 reducer batch 严格验证且冲突时整批不提交”。Executor / Scheduler 当前仍会在一次完整动作内部依次形成多个候选 batch；把所选执行图的全部节点汇总后再经过统一提交门、并让 diagnostic transition 的正式 after/mutation 回到 unchanged/zero，属于 P7-S3，尚未实现。

## 当前距离

距离最小可信战斗纵切仍缺 P7-S3 至 P7-S17 的执行图原子提交、规则/审计分离、typed IR、动作/目标/query-submit、阶段机、timeline/control、queue、damage、shield、status、RNG、战斗中 summon 和 wave 修复。

距离完整复刻仍缺全角色、全怪物、光锥、遗器、装备构筑、关卡环境、特殊模式及既有 admission/source backlog 的后续扩面。

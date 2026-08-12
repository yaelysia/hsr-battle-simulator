# P9 执行卡索引

## 1. 用途

本目录保存 P9 非记忆、非欢愉角色共享机制收口的单阶段执行卡。总目标、严格依赖和唯一
阶段 checklist 位于 `P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md`。本目录不是
第二套总计划；每个文件只约束一个阶段。

P9-S5 已按目标 IR、实体关系、动作目标来源、动作选择权威和随机账本拆分。S5C1 独立建立
来源目录；查询、提交、选择上下文和 executor 消费不能在保留双重权威的前提下继续拆开，
因此合并为 S5C2。S5D 再按共享随机抽样契约和动作消费/聚合拆为 S5D1、S5D2。不存在
可执行的旧 S5、S5C、S5D 总卡或 S5C3。

原 P9-S6 同时包含完整来源分区和 evaluator 实现，已按权威边界拆为 S6A、S6B。S6A 只建立
条件责任目录和精确 blocker；S6B 才实现 committed-state 求值。旧 S6 总卡不再是执行入口。

原 P9-S8 同时修改完整来源字段归属、通用任务图事务以及命中/RNG 时序，首次实时分母重建还
证明旧 `31 / 8,651` 数字混合了过期来源与不同物化角色。S8A 曾独立建立来源目录；S8B1
开工审查随后发现其分母仍遗漏 hybrid child-bearing task、命名 template 参数子图和 shared
template 内部节点。S8A-R1 已完成修订并验收，原 S8A 分母只保留为历史证据。2026-08-12
试运行进一步证明原 S8B 同时改变任务图 IR、共享执行器、ability、status callback 和跨入口上下文
五个行为边界以及一个独立兼容债务退出边界，因此继续拆为 S8B1-S8B6。S8B3 开工预检又发现
“能力入口/正式目录、普通动作消费、queue standalone 消费”是三个独立边界，并确认 S8A 分母
只覆盖 P9 角色能力，不能据此全局删除怪物等内容域的旧执行路径，因此 S8B3 再拆为严格顺序的
S8B3A-S8B3C。该预检同时发现旧 ability task lowering 会丢通用分支和模板子树，因此在迁移前
增加 S8B1-R2 根因修复；S8C 才处理命中、barrier、parallel 和随机顺序。
旧 S8、S8B 与 S8B3 文件都只保留聚合说明，不再是执行入口。

执行线程最多提交 `ready_for_review`，不得勾总计划、提交 Git 或提前进入下一卡。验收线程
通过代码审查和聚焦 evidence 后才更新卡片与总 checklist，并建立阶段检查点。

## 2. 开工协议

每张卡开始前必须：

1. 记录前置阶段已验收 commit、当前工作区状态和 CodeGraph 索引状态。
2. 只读当前卡、共享机制归并文档和卡内列出的直接代码；不通读其他 P9 卡或历史验证器。
3. 用 CodeGraph 定位起始符号、生产调用链和影响范围，最多两轮结构探索。
4. 核对“当前事实”。若差异改变目标、职责或验收，立即返回 `plan_mismatch`；不能自行缩小目标。
5. 先形成本阶段一页闭合地图：权威分母、输入/输出、生产不变量、全部正式调用者、
   gap owner 和最小 evidence。任一项无法从当前代码或来源确定时不得编码。

## 3. 共用实施约束

- 角色专属差异只能作为内容 IR，不得形成角色/技能/固定 ID runtime handler。
- 先在模型、lowering、装配或原子提交边界拒绝非法状态，再用少量负例证明。
- 普通动作、状态 callback、provider 和角色战斗事件必须复用同一效果契约。
- 未知、缺来源或缺 payload 时 state、mutation、event、RNG 均保持不变。
- 不能以旧验证变绿作为目标；旧假设过时则迁移仍有效谓词或退役。
- 不兼容旧弱接口时不建双轨兼容层，除非用户明确要求。
- 发现记忆、欢愉或非战斗产品范围时分类记录，不提前实现。

### `ready_for_review` 硬门槛

提交前必须在报告中逐项给出以下闭合证据；缺一项不得使用 `ready_for_review`：

1. 当前卡定义的非法、矛盾或未准入状态已由生产模型、lowering、装配或原子提交边界直接
   拒绝，不能只依靠验证器发现，也不能留给 runtime 静默忽略。
2. 本次改变的公开类型、返回状态和字段已通过 CodeGraph 核对全部正式生产调用者；报告列出
   实际迁移范围和仍保留旧接口的明确理由，不能只搜索卡内点名样例。
3. 当前目录全部已知 gap 已按原因和下游 owner 聚合；每个分组至少保留一个包含文件、记录
   身份和具体位置的代表来源。允许后续阶段负责，但不得漏报或用通用原因覆盖精确 blocker。
4. 每项执行清单都有生产不变量、正式调用链或真实来源 evidence 对应。一个边界只保留一个
   最小负例；不得增加并列 CLI、重复 matrix 或验证专用 runtime 来制造完成证据。
5. 所有会先写队列、阶段或 committed state 的请求入口，均在首次 mutation 前完成 actor、动作
   所有权和 submission admission 校验；UI/adapter 命令身份直接来自所选 choice/template。

任一项未闭合时提交 `blocked`；发现卡片职责或语义错误时提交 `plan_mismatch`；仅缺少卡内
明确导航信息时提交 `context_gap`。已接受的 deferred 不阻止提交，但必须满足第三项交接要求。

## 4. 验收与返工止损

首次验收必须在一次内完成：完整来源范围、生产不变量、全部正式调用者、gap 归属和验证器本身
五面审查。验收线程先形成内部 finding ledger，再一次性发出整改意见。

修复后只做差量代码复核，但必须重跑来源范围门和 gap 归属门。若一次集中修复后仍出现新的系统性
问题类别，立即返回规划线程重写闭合地图或拆卡；不再连续进入局部补丁循环。

执行线程在 45 分钟内必须形成卡内定义的可编译纵切；90 分钟仍不能提交该纵切时必须停止并返回
`plan_mismatch` 或 `context_gap`。首次审查若同时发现三个以上独立系统性类别，直接判定执行卡
分解失败，备份并回退未验收实现；不得把长整改清单继续塞给同一执行线程。

## 5. 共用验证协议

验证顺序固定为：

```text
生产不变量 -> 秒级失败切片 -> 唯一阶段主验证 -> 实际触达 direct -> git diff --check
```

- 每阶段只有一个公开业务主入口和一份 summary。
- 主入口最多一次诊断和一次最终运行；修复期间只运行失败 family/矩阵行。首次主入口前必须
  完成生产自审与五面验收清单，不能靠反复全入口发现本可静态审查的问题。
- direct 默认最多两个，只由实际修改的生产调用链触发。
- source/family 过滤必须在读取、lowering、IR/RuleBook 构建和 evidence 之前生效。
- 不构建完整 Canonical IR 后过滤，不写完整 RuleBook、raw ability 或 transition dump。
- 不运行 P1-P8 聚合、`validate_v0_209`、旧未过滤 family 聚合或固定历史验证套餐。
- summary 记录来源读取次数、构建次数、case 数、墙钟、峰值 RSS、产物大小和代码增减。
- 验证器默认在阶段验收后冻结为 `historical_evidence`；需要成为 direct 时只提取稳定小切片。

统一命令形状：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/hsr_v8_p9_<stage>_pycache \
  python3 -m compileall -q simulator_v8_clean_core

PYTHONDONTWRITEBYTECODE=1 /usr/bin/time -v -o /tmp/hsr_v8_p9_<stage>_time_v.txt \
  timeout --signal=TERM <budget> ionice -c3 nice -n 15 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_<stage>_<topic> \
  --tbgd-root ../../turnbasedgamedata-main \
  --output-dir /tmp/hsr_v8_p9_<stage>_<topic>

git diff --check
```

## 6. 资源止损

| 阶段 | 单次主入口 | 累计验证 | RSS | evidence | 验证代码目标 |
|---|---:|---:|---:|---:|---:|
| S0-S3 | 8 分钟 | 15 分钟 | 1 GiB | 5 MiB | 900 行 |
| S4-S9 | 8 分钟 | 15 分钟 | 1 GiB | 5 MiB | 900 行 |
| S10-S17 | 10 分钟 | 20 分钟 | 1 GiB | 8 MiB | 1,000 行 |
| S18 | 12 分钟 | 15 分钟 | 1 GiB | 10 MiB | 900 行 |
| S19 | 12 分钟 | 25 分钟 | 1.25 GiB | 12 MiB | 1,000 行 |
| S20 | 20 分钟 | 25 分钟 | 1.5 GiB | 20 MiB | 900 行 |

到达任一上限立即停止并提交资源证据。不得提高限制、并发补跑、压缩可读性或拆文件绕过
代码预算。主入口达到单次预算 80% 即使通过，也必须先缩窄投影/evidence 才能最终验收。

S5A、S5B、S5C1-S5C2 和 S5D1-S5D2 是原 S5 的职责拆分，不因阶段名数增加总验证预算。后序卡不得重跑前序主入口；
S5C1-S5C2 两段主入口墙钟合计目标 12 分钟、evidence 合计 4 MiB、新增验证代码合计目标 1,200 非空行；
不得通过压缩可读性满足行数。
超过任一总量应暂停重新划分证据，不能通过增加 CLI mode 或重复矩阵继续扩张。

S8B1-S8B6 同样共享原 S8B 的预算：主入口累计目标 6 分钟、硬上限 8 分钟，单进程峰值
768 MiB，evidence 合计 3 MiB，新增验证代码合计目标 1,650 非空行。S8B1 后不得重跑前序
主入口或完整 S8A 目录；后序卡只证明新增消费边界和必要的最小集成链。

## 7. Gap 口径

- `source_gap_blocked`：raw 确实缺失或无法唯一证明；必须排除扫描/lowering/谓词错误。
- `lowering_gap`、`admission_gap`、`implementation_missing`、`validation_gap`：当前责任阶段
  必须关闭，不能改名 deferred。
- `external_content_dependency`：通用消费者存在但当前 79 条来源没有生产者，不用 synthetic
  gameplay 冒充执行。
- `non_gameplay`：完整分支证明仅表现/客户端/AI/统计，零战斗副作用。
- `not_proven`：没有证据；不能解释成通过或失败。

## 8. 推荐配置与执行卡

| 阶段 | 执行卡 | 推荐配置 |
|---|---|---|
| S0 | `P9-S0_SCOPE_AND_PROJECTION_CONTRACT.md` | 5.6 Sol / max / 普通聚焦 |
| S1 | `P9-S1_ABILITY_SOURCE_GRAPH.md` | 5.6 Sol / max / Goal |
| S2 | `P9-S2_TRACE_EIDOLON_BUILD_BINDING.md` | 5.6 Sol / max / Goal |
| S3 | `P9-S3_OBFUSCATED_SOURCE_RESOLUTION.md` | 5.6 Sol / max / Goal |
| S4 | `P9-S4_NUMERIC_DYNAMIC_VALUE_CLOSURE.md` | 5.6 Sol / max / 普通聚焦 |
| S5A | `P9-S5A_TARGET_SOURCE_AND_TYPED_CONTRACT.md` | 5.6 Terra / xhigh / 普通聚焦 |
| S5B | `P9-S5B_ENTITY_RELATION_DETERMINISTIC_TARGET.md` | 5.6 Terra / xhigh / Goal |
| S5C1 | `P9-S5C1_ACTION_TARGET_SOURCE_CONTRACT.md` | 5.6 Terra / max / 普通聚焦 |
| S5C2 | `P9-S5C2_ACTION_SELECTION_QUERY_SUBMIT_CONTEXT.md` | 5.6 Sol / max / Goal |
| S5D1 | `P9-S5D1_TARGET_RANDOM_SAMPLER.md` | 5.6 Sol / xhigh / 普通聚焦 |
| S5D2 | `P9-S5D2_BOUNCE_DYNAMIC_TARGET_AND_AGGREGATE.md` | 5.6 Sol / max / 普通聚焦 |
| S6A | `P9-S6A_CONDITION_RESPONSIBILITY_CONTRACT.md` | 5.6 Sol / xhigh / 普通聚焦 |
| S6B | `P9-S6B_COMMITTED_STATE_CONDITION_EVALUATION.md` | 5.6 Sol / max / Goal |
| S7 | `P9-S7_CONTEXTUAL_CONDITION_CLOSURE.md` | 5.6 Sol / max / Goal |
| S8A | `P9-S8A_CONTROL_FLOW_SOURCE_CONTRACT.md` | 5.6 Sol / max / 普通聚焦 |
| S8A-R1 | `P9-S8A-R1_CONTROL_FLOW_DENOMINATOR_COMPLETENESS.md` | 5.6 Sol / max / 普通聚焦 |
| S8B1 | `P9-S8B1_TASK_GRAPH_IR_MATERIALIZATION.md` | 5.6 Sol / high / 普通聚焦 |
| S8B2 | `P9-S8B2_ATOMIC_EXECUTOR_CORE.md` | 5.6 Sol / xhigh / 普通聚焦 |
| S8B1-R2 | `P9-S8B1-R2_FORMAL_TASK_TREE_COMPLETENESS.md` | 5.6 Sol / high / 普通聚焦 |
| S8B3 | `P9-S8B3_ABILITY_STANDALONE_MIGRATION.md` | 5.6 Sol / high / 普通聚焦 |
| S8B3A | `P9-S8B3A_ABILITY_INVOCATION_FORMAL_CATALOG.md` | 5.6 Sol / high / 普通聚焦 |
| S8B3B | `P9-S8B3B_ACTION_CALLBACK_MIGRATION.md` | 5.6 Sol / high / 普通聚焦 |
| S8B3C | `P9-S8B3C_STANDALONE_QUEUE_MIGRATION.md` | 5.6 Sol / high / 普通聚焦 |
| S8B4 | `P9-S8B4_STATUS_CALLBACK_MIGRATION.md` | 聚合说明，不直接执行 |
| S8B4A | `P9-S8B4A_STATUS_CALLBACK_FORMAL_CATALOG.md` | 5.6 Sol / high / 普通聚焦 |
| S8B4B | `P9-S8B4B_STATUS_CALLBACK_RUNTIME_MIGRATION.md` | 5.6 Sol / xhigh / 普通聚焦 |
| S8B5 | `P9-S8B5_CROSS_ENTRY_INTEGRATION_AUDIT.md` | 5.6 Sol / xhigh / 普通聚焦 |
| S8B6 | `P9-S8B6_LEGACY_TOPOLOGY_RETIREMENT.md` | 5.6 Sol / high / 普通聚焦 |
| S8C | `P9-S8C_HIT_BARRIER_RANDOM_SEQUENCE.md` | 5.6 Sol / max / Goal |
| S9 | `P9-S9_EVENT_CONTRACT_ACTION_WINDOWS.md` | 5.6 Sol / max / 普通聚焦 |
| S10 | `P9-S10_STATUS_CALLBACK_LIFECYCLE_CLOSURE.md` | 5.6 Sol / max / Goal |
| S11 | `P9-S11_DAMAGE_HEAL_SHIELD_CLOSURE.md` | 5.6 Sol / max / Goal |
| S12 | `P9-S12_RESOURCE_SKILL_AVAILABILITY_CLOSURE.md` | 5.6 Sol / xhigh / 普通聚焦 |
| S13 | `P9-S13_TIMELINE_QUEUE_EXTRA_ACTION_CLOSURE.md` | 5.6 Sol / max / Goal |
| S14 | `P9-S14_HP_DEATH_REVIVE_DEPARTURE_CLOSURE.md` | 5.6 Sol / max / Goal |
| S15 | `P9-S15_WEAKNESS_TOUGHNESS_BREAK_CLOSURE.md` | 5.6 Sol / max / Goal |
| S16 | `P9-S16_ACTION_SET_PHASE_TRANSFORMATION_CLOSURE.md` | 5.6 Sol / max / Goal |
| S17 | `P9-S17_OWNED_BATTLE_EVENT_ACTION_ENTITY_CLOSURE.md` | 5.6 Sol / max / Goal |
| S18 | `P9-S18_CURRENT_CHARACTER_GAP_RECALCULATION.md` | 5.6 Terra / xhigh / Goal |
| S19 | `P9-S19_REPRESENTATIVE_FORMAL_BATTLE_SLICES.md` | 5.6 Sol / max / Goal |
| S20 | `P9-S20_CURRENT_SOURCE_CHARACTER_AGGREGATE.md` | 5.6 Sol / max / Goal |

## 9. 报告边界

`ready_for_review` 只汇报：状态、生产改动、主验证、实际 direct、资源、遗留 gap 和报告路径。
报告写入仓库级 `live_validation_reports/`，临时日志/evidence 写 `/tmp`。执行线程不得在报告中
修改总计划状态或提前声称下一阶段依赖满足。

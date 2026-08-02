# P9-S0 至 P9-S20 执行卡索引

## 1. 用途

本目录保存 P9 非记忆、非欢愉角色共享机制收口的单阶段执行卡。总目标、严格依赖和唯一
阶段 checklist 位于 `P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md`。本目录不是
第二套总计划；每个文件只约束一个阶段。

执行线程最多提交 `ready_for_review`，不得勾总计划、提交 Git 或提前进入下一卡。验收线程
通过代码审查和聚焦 evidence 后才更新卡片与总 checklist，并建立阶段检查点。

## 2. 开工协议

每张卡开始前必须：

1. 记录前置阶段已验收 commit、当前工作区状态和 CodeGraph 索引状态。
2. 只读当前卡、共享机制归并文档和卡内列出的直接代码；不通读其他 P9 卡或历史验证器。
3. 用 CodeGraph 定位起始符号、生产调用链和影响范围，最多两轮结构探索。
4. 核对“当前事实”。若差异改变目标、职责或验收，立即返回 `plan_mismatch`；不能自行缩小目标。
5. 先形成本阶段 `source -> lowering -> admission -> runtime -> validation` 差距矩阵，再编码。

## 3. 共用实施约束

- 角色专属差异只能作为内容 IR，不得形成角色/技能/固定 ID runtime handler。
- 先在模型、lowering、装配或原子提交边界拒绝非法状态，再用少量负例证明。
- 普通动作、状态 callback、provider 和角色战斗事件必须复用同一效果契约。
- 未知、缺来源或缺 payload 时 state、mutation、event、RNG 均保持不变。
- 不能以旧验证变绿作为目标；旧假设过时则迁移仍有效谓词或退役。
- 不兼容旧弱接口时不建双轨兼容层，除非用户明确要求。
- 发现记忆、欢愉或非战斗产品范围时分类记录，不提前实现。

## 4. 共用验证协议

验证顺序固定为：

```text
生产不变量 -> 秒级失败切片 -> 唯一阶段主验证 -> 实际触达 direct -> git diff --check
```

- 每阶段只有一个公开业务主入口和一份 summary。
- 主入口最多一次诊断和一次最终运行；修复期间只运行失败 family/矩阵行。
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

## 5. 资源止损

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

## 6. Gap 口径

- `source_gap_blocked`：raw 确实缺失或无法唯一证明；必须排除扫描/lowering/谓词错误。
- `lowering_gap`、`admission_gap`、`implementation_missing`、`validation_gap`：当前责任阶段
  必须关闭，不能改名 deferred。
- `external_content_dependency`：通用消费者存在但当前 79 条来源没有生产者，不用 synthetic
  gameplay 冒充执行。
- `non_gameplay`：完整分支证明仅表现/客户端/AI/统计，零战斗副作用。
- `not_proven`：没有证据；不能解释成通过或失败。

## 7. 推荐配置与执行卡

| 阶段 | 执行卡 | 推荐配置 |
|---|---|---|
| S0 | `P9-S0_SCOPE_AND_PROJECTION_CONTRACT.md` | 5.6 Sol / max / 普通聚焦 |
| S1 | `P9-S1_ABILITY_SOURCE_GRAPH.md` | 5.6 Sol / max / Goal |
| S2 | `P9-S2_TRACE_EIDOLON_BUILD_BINDING.md` | 5.6 Sol / max / Goal |
| S3 | `P9-S3_OBFUSCATED_SOURCE_RESOLUTION.md` | 5.6 Sol / max / Goal |
| S4 | `P9-S4_NUMERIC_DYNAMIC_VALUE_CLOSURE.md` | 5.6 Sol / max / 普通聚焦 |
| S5 | `P9-S5_TARGET_ENTITY_RELATION_CLOSURE.md` | 5.6 Sol / max / 普通聚焦 |
| S6 | `P9-S6_STATE_ENTITY_CONDITION_CLOSURE.md` | 5.6 Sol / xhigh / Goal |
| S7 | `P9-S7_CONTEXTUAL_CONDITION_CLOSURE.md` | 5.6 Sol / max / Goal |
| S8 | `P9-S8_CONTROL_FLOW_SEQUENCE_CLOSURE.md` | 5.6 Sol / max / Goal |
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

## 8. 报告边界

`ready_for_review` 只汇报：状态、生产改动、主验证、实际 direct、资源、遗留 gap 和报告路径。
报告写入仓库级 `live_validation_reports/`，临时日志/evidence 写 `/tmp`。执行线程不得在报告中
修改总计划状态或提前声称下一阶段依赖满足。

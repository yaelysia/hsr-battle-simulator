# VG-R1 P8-S8 task/event 共享证据试点：ready_for_review

日期：2026-07-27

## 状态

- 交付状态：`ready_for_review`
- 实施基线：`e8bb43f2d0613d314d4201fa143799669622506d`
- 最后一次未过滤业务结果：`ok=false`
- 最后一次未过滤治理结果：`governance_ok=true`
- 执行卡 checklist 未勾选，未创建 Git 提交。
- 验收差量只修正 CLI 退出口径、治理缺口口径、当前投影轻量证据和报告位置；
  未修改三项游戏机制，也未重跑未过滤组合。

## 验收差量修正

### CLI 只按业务 `ok` 退出

通用 `main()` 现在只读取 `summary["ok"]` 决定退出码，`governance_ok` 仅保留在
run summary 中供治理审查。纯逻辑探针实测：

| 业务 `ok` | `governance_ok` | 退出码 |
|---:|---:|---:|
| `true` | `false` | 0 |
| `false` | `true` | 1 |
| `true` | 不存在 | 0 |
| `false` | 不存在 | 1 |

因此受限组合业务全绿时不会再被“不属于未过滤治理运行”改写为失败；未过滤业务失败
也不会再因治理通过而退出 0。

### 已知缺口是上限，不是永久基线

治理 helper 现在同时要求：

```text
business_ok == (失败集合为空)
失败集合 ⊆ 已确认 P8-R1 缺口集合
```

纯治理矩阵覆盖三项已知缺口的全部 8 个子集，包含零缺口、任意单项、任意两项和三项
全在，均按预期允许；未知失败、已知与未知混合、未归因业务失败、成功状态却携带失败
行四类不一致输入均按预期阻断。

失败隔离探针会从实际失败集合选取真实 family，在 peer 完整结果已存在后复用同一个
共享上下文执行，并比较 peer 摘要；如果业务已全部修复，探针明确为不适用，不要求
旧缺口继续存在。探针调用前后所有构建计数仍以差值判断，不能写死。

证据：

```text
/tmp/vg_r1_p8_s8_shared_evidence/post_review_fix/
  governance_cli_matrix.py
  governance_cli_matrix.json
```

`governance_cli_matrix.json`：`ok=true`，已知缺口子集检查数为 8。

### 当前源码上的窄投影轻量检查

代码收缩前的 `post_narrow` 只继续作为 6.09 秒、349,136 KiB 的资源基线，不再用来
证明当前负例行为。历史命令中的 `--owned-combatant-projection-only` 已退役，不是
当前 CLI。

本轮直接导入当前 `TBGDLowering` 和当前
`_owned_combatant_projection_build_issues()`，只构建一次窄投影并在内存中制造负例：

- 当前投影成功，完整 build 实际观察为 0 次，窄投影实际观察为 1 次；
- 只包含五类数据 tuple 和 issue tuple；
- 6 个 servant 定义、440 个动作定义、440 个能力绑定、440 个动作准入、6 个出生
  模板；
- 五类集合排序确定；
- 重复动作定义、缺失能力绑定、破坏 servant 来源关系均产生预期结构化 issue 并
  fail-closed；
- 墙钟 8.16 秒，峰值 RSS 347,840 KiB，文件系统输入/输出 403,632 / 8；
- 退出码 0，stderr 为 0 bytes。

证据：

```text
/tmp/vg_r1_p8_s8_shared_evidence/post_review_fix/
  current_projection_check.py
  current_projection_check.json
  current_projection_time-v.txt
  current_projection_stderr.log
```

## 原治理实现结果

- `OwnedCombatantAdmissionProjection` 是类型化 NamedTuple，只携带 servant 定义、
  动作定义、动作能力绑定、动作准入、出生模板及结构化 issue。
- 窄投影在动作能力 lowering 前按 servant 动作集合过滤，不先构建完整角色、怪物和
  servant 能力图。
- 完整 build 与窄投影复用现有动作、能力绑定、准入、owner relation、
  spawn/replacement 和 birth-template helper；完整 build 的默认全量语义不变。
- P8-S8 owned-combatant catalog 只走窄投影，没有 full-build fallback。
- task/event 组合入口只建立一次 focused bundle 和一次公共证据；旧单切片参数只
  路由到同一实现。
- task/event 保留独立过滤、矩阵、summary 和失败诊断，业务 `ok` 与治理
  `governance_ok` 分离。
- 已删除此前为单个验证消费者增加的 IR 深冻结、逐字段来源审计和投影
  meta-validator；没有新增 registry、持久缓存或第二套 oracle。

最后一次未过滤组合的真实入口计数为：

```json
{
  "full_tbgd_lowering_build": 0,
  "owned_combatant_admission_projection": 1,
  "focused_bundle": 1,
  "common_evidence": 1,
  "components": {
    "partition": 1,
    "path_inventory": 1,
    "formal_scenario": 1,
    "lifecycle": 1,
    "production_event_chain": 1,
    "common_mutation_events": 1,
    "battle_state_transition_events": 1,
    "heal_events": 1,
    "custom_events": 1,
    "weakness_events": 1
  }
}
```

## 代码量

当前 `git diff --numstat`：

| 文件 | 新增 | 删除 | 净变化 |
|---|---:|---:|---:|
| `tbgd/__init__.py` | 11 | 3 | +8 |
| `tbgd/lowering.py` | 358 | 43 | +315 |
| P8-S8 validator | 612 | 615 | -3 |
| 合计 | 981 | 661 | +320 |

验证 Python 仍净减少 3 行；production 与 validation Python 总净增长 320 行，低于
350 行上限。收缩来自删除旧 wrapper、重复编排、深冻结/来源审计框架及重复 summary
组装，不是压缩无关代码或删除有效业务诊断。

## 重验证资源与业务结果

所有重验证均串行、低 CPU/IO 优先级、4 GiB 地址空间上限，产物写入 `/tmp`。

| 证据 | 墙钟 | 峰值 RSS | 文件系统输入/输出 | 退出 | 结果 |
|---|---:|---:|---:|---:|---|
| 接受的旧 task 基线 | 46.76 s | 4,137,552 KiB | 446,480 / 8 | 1 | 完整 build 在进入 family 前 `MemoryError` |
| 旧窄投影资源基线 | 6.09 s | 349,136 KiB | 128,160 / 16 | 0 | 仅保留为资源基线 |
| 受限 task+event | 44.29 s | 380,796 KiB | 0 / 192 | 0 | 两个代表 family 通过 |
| 前次未过滤 task+event | 12:31.36 | 585,992 KiB | 0 / 6,264 | 1 | 完整到达业务检查，仅三项既有失败 |
| 最后一次未过滤 task+event | 13:23.06 | 588,188 KiB | 419,568 / 6,264 | 0* | `ok=false`，旧 `governance_ok=true` |
| 当前窄投影轻量检查 | 8.16 s | 347,840 KiB | 403,632 / 8 | 0 | 当前正例与三类负例通过 |

`0*` 是本次审查发现并已修复的旧 CLI 退出语义，不能作为业务成功证据；对应 run
summary 的业务 `ok` 一直为 `false`。纯 CLI 矩阵已证明当前源码对同一
`ok=false/governance_ok=true` 输入退出 1。按本轮要求未重跑 13 分钟组合，因此旧
`time-v.txt` 保持原始退出码，不篡改历史产物。

最后一次未过滤产物总量为 3,179,258 bytes，未序列化完整 Canonical IR、RuleBook、
transition 或 replay dump。task/event 两份执行矩阵、stack property 矩阵、状态替换
矩阵及两份切片 summary 与前次未过滤结果逐字节相同，没有新增业务回归。

未过滤组合完整执行 64 个 task family 和 51 个 event family，只保留以下当前已确认
的 P8-R1 业务缺口：

- `SetDynamicValueByCopying:s8`：正式场景没有建立其依赖的忆灵父状态。
- `SetModifierDynamicValue:s8`：正式场景没有建立其依赖的忆灵父状态。
- `OnDeathrattle:s8`：空目标身份比较仍被单目标规则阻断。

这三项不经过窄投影调用链，不是共享证据重构引入的回归。它们是当前允许失败集合，
不是未来必须保持的失败；修复其中任意项或全部修复都不会使 VG-R1 治理谓词失败。
本轮未修改 target、condition、status、summon、装备或其他游戏机制。

## 本轮实际命令

纯治理与 CLI 矩阵：

```bash
PYTHONPATH=/home/zhangjinhao/code/hsr/hsr_v075_baseline_clean/hsr \
PYTHONDONTWRITEBYTECODE=1 \
python3 /tmp/vg_r1_p8_s8_shared_evidence/post_review_fix/governance_cli_matrix.py \
  > /tmp/vg_r1_p8_s8_shared_evidence/post_review_fix/governance_cli_matrix.json
```

当前窄投影轻量检查：

```bash
ulimit -v 4194304
exec /usr/bin/time -v \
  -o /tmp/vg_r1_p8_s8_shared_evidence/post_review_fix/current_projection_time-v.txt \
  ionice -c 3 nice -n 15 env \
  PYTHONPATH=/home/zhangjinhao/code/hsr/hsr_v075_baseline_clean/hsr \
  PYTHONDONTWRITEBYTECODE=1 \
  python3 /tmp/vg_r1_p8_s8_shared_evidence/post_review_fix/current_projection_check.py \
  > /tmp/vg_r1_p8_s8_shared_evidence/post_review_fix/current_projection_check.json \
  2> /tmp/vg_r1_p8_s8_shared_evidence/post_review_fix/current_projection_stderr.log
```

最后一次未过滤组合（本轮未重跑）：

```bash
ulimit -v 4194304
exec /usr/bin/time -v \
  -o /tmp/vg_r1_p8_s8_shared_evidence/post_unfiltered_governance_final/time-v.txt \
  ionice -c 3 nice -n 15 env PYTHONDONTWRITEBYTECODE=1 \
  python3 -m simulator_v8_clean_core.tools.validate_p8_s8_light_cone_remaining_gameplay_closure \
  --contract-slice task --contract-slice event \
  --tbgd-root /home/zhangjinhao/code/hsr/turnbasedgamedata-main \
  --output-dir /tmp/vg_r1_p8_s8_shared_evidence/post_unfiltered_governance_final
```

最终 fast 检查：

```bash
PYTHONPYCACHEPREFIX=/tmp/vg_r1_post_review_compile \
python3 -m compileall -q \
  simulator_v8_clean_core/tbgd/__init__.py \
  simulator_v8_clean_core/tbgd/lowering.py \
  simulator_v8_clean_core/tools/validate_p8_s8_light_cone_remaining_gameplay_closure.py

PYTHONDONTWRITEBYTECODE=1 \
python3 -m simulator_v8_clean_core.tools.validate_p8_s8_light_cone_remaining_gameplay_closure \
  --help

git diff --check
```

三项均退出 0；当前 `--help` 不包含已退役的投影专用参数。

## 明确未运行

- 本轮没有重跑未过滤 task+event 组合；
- 完整 P8-S8 聚合入口；
- P8-S8 catalog startup；
- 任何直接或间接调用完整 `TBGDLowering.build()` 的 owned-combatant 验证；
- P1-P7 聚合；
- `validate_v0_209`；
- P3/P4/P6/P7 重目录验证；
- 与 task/event 调用链无关的 runtime、UI 或 scenario 验证。

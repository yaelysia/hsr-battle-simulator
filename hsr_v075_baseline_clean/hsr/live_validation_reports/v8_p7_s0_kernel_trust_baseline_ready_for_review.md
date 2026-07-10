# v8 P7-S0 内核可信问题基线 ready_for_review

## 阶段边界

本 evidence 包只覆盖 `P7-S0`。执行线程没有修改 runtime 行为，没有修复 `P7-I01` 至 `P7-I23`，没有修改 P7 唯一 checklist，也没有运行 P1-P6 聚合。

本阶段产物的 `ok=true` 只表示 24 行基线结构满足门禁、十项当前缺陷被实际复现、三项否定性结论具有结构证据，且没有触达 runtime；不表示这些缺陷正确、已经关闭或阶段已经完成。

当前状态：

```text
ready_for_review=true
p7_all_fixed=false
p7_done_eligible=false
runtime_behavior_changed=false
```

执行线程只提交 `ready_for_review`。本报告和验证 summary 均不包含阶段完成布尔字段；是否完成只能由验收线程决定。

## 代码产物

新增：

```text
simulator_v8_clean_core/tools/validate_p7_s0_kernel_trust_baseline.py
```

脚本只使用：

- 通用纯内存 `BattleState` / `UnitState` fixture。
- 一个最小内存 `CanonicalIR -> RuleBook` slice，用于 executor、scheduler 和 queue 调用链。
- 当前 runtime 的真实 reducer、target、damage、status chance、RNG、action query、executor、scheduler 和 queue consumer。
- 精确到函数和行为语句的当前源码锚点。
- 对整个 `simulator_v8_clean_core` Python 包的 AST 结构扫描，用于 I20、I21、I23 的否定性调用链/接口证据。
- Git porcelain 工作区清单，用结构化路径谓词判断本轮是否触达 runtime Python 文件。

脚本不读取 TBGD、TextMap、旧 v7 或 model pack，不使用固定角色、怪物、技能、关卡、文件 hash 或观测答案。

## 输出产物

本轮输出目录：

```text
/tmp/hsr_v8_p7_s0_kernel_trust_baseline/
```

精简产物：

```text
validation_summary_p7_s0_kernel_trust_baseline.json
p7_s0_issue_matrix.json
p7_s0_probe_samples.json
p7_s0_prior_validation_scope_matrix.json
p7_s0_structured_negative_evidence.json
```

没有输出完整 Canonical IR、完整 RuleBook 或全量 transition dump。

## 问题矩阵结果

`P7-I01` 至 `P7-I24` 均有且只有一行主记录：

```text
issue_row_count=24
unique_issue_count=24
confirmed_open_count=24
accepted_fixed_count=0
source_gap_blocked_count=0
evidence_missing_count=0
target_invariant_missing_count=0
structured_evidence_required_count=3
structured_evidence_missing_count=0
```

分类统计：

```text
correctness_blocker=15
architecture_debt=5
integration_missing=2
scalability_blocker=1
validation_gap=1
```

所有问题继续保持 `confirmed_open`。本阶段没有把已确认内核缺陷改写为 raw source gap、lowering gap 或内容扩面 backlog。

## 十个轻量 probe

```text
required_count=10
executed_count=10
current_defect_observed_count=10
current_defect_not_observed_count=0
observation_missing_count=0
target_invariant_missing_count=0
```

| Probe | 当前观察值 | 目标不变量 |
|---|---|---|
| partial transition | selected task blocked，但 `action_enabled=true`、4 条 mutation、state changed，且无权威 trust 字段 | 选中节点 unsupported 时零提交、state unchanged、结果不可作为可信后继 |
| Mutation.before | 当前 skill point 为 3，mutation 声明 before=999 仍把值写成 1 | stale before 原子拒绝 |
| action ownership | query 只返回 `validation:normal`，直接提交未查询的 foreign action 仍 enabled 并产生 3 条 mutation | 未查询/非 owner action 提交被拒且 state unchanged |
| single cardinality | single policy 请求两个敌人，两个都进入 legal/selected，`ok=true` | single 只接受一个主目标 |
| duplicate begin-turn | 第一次推进得到 turn sequence 1；查询不改状态；提交又产生 1→2 的 begin-turn mutation | query-submit 只消费已经打开的决策回合 |
| shield routing | 50 护盾承受 30 DoT 后护盾仍为 50，HP 100→70，mutation 只有 HP | 可吸收伤害先扣护盾，完全吸收时 HP 不变 |
| control progress | 连续两次提交都返回同一 control gate，state unchanged、AV=0、无 turn sequence 进展 | 控制消费/跳过回合并推进生命周期和时间线 |
| omitted chance | `chance_omitted_guaranteed` 的 base probability=1，但 resist probability=0.5、guaranteed=false | 结构化必定施加不再走普通效果抵抗 |
| RNG identity | 两个逻辑 hit 的 crit event id 和 choice key 完全相同 | 每个 hit/task/phase/target 随机决策身份唯一 |
| queue head progress | 首条终结技因 drain 时能量不足连续 blocked，两次后队列仍为 2，head 未变，后项未执行 | 永久无效项进入终态，后续合法项能够前进 |

这些 probe 的 `current_defect_observed=true` 是当前错误行为的事实记录。总门禁现在明确要求十项缺陷全部被当前 runtime 实际复现；任一 probe 未执行、没有结构化 observation，或缺陷未被观察到，`ok` 都会变为 `false`。它们不表示错误行为被当成正确行为验收；每项另有独立 `target_invariant`，供所属修复阶段转为正反不变量。

## I20 / I21 / I23 结构化静态证据

脚本通过 `ast.parse` 扫描包内全部 212 个 Python 文件，`parse_error_count=0`。三项证据的判定不再依赖少量源码字符串：

- I20：收集五个 SummonSystem 公开 spawn plan/apply 入口的全部 AST 调用点。生产范围共 5 个调用点，其中 setup 装配 4 个、`systems/summon.py` 内部委托 1 个；tools 验证调用 57 个；其他生产调用点为 0。由此可复核 action task/effect/callback 等生产路径没有 spawn consumer。
- I21：检查 `CombatScheduler._try_wave_transition` 的完整 AST 函数体、其全包 caller 集合及公开 `step` 返回路径，并枚举 `systems/wave.py` 的全部 `GameEvent` 构造。当前唯一生产 caller 是 `CombatScheduler.step`，它直接返回 `wave_step`；当前产生 5 类事件（`wave.started`、`wave.monster`、`wave.cleared`、`battle.victory`、`battle.defeat`），函数体有 2 处 `result.events` 转交 transition，但 wave 函数和 `step` 中的事件派发器调用均为 0。
- I23：枚举 `BattleState`、`Snapshot`、`BattleTransition` 的直接公开方法与字段，再扫描全部生产符号名。当前公开方法分别只有 `snapshot` / `to_json` / `to_json`；transition 同时序列化完整 before/after，snapshot 两次展开 queues 并展开完整 unit flags；紧凑/搜索状态键候选符号为 0。

结构证据汇总：

```text
required_issue_ids=P7-I20,P7-I21,P7-I23
structurally_observed_count=3
structured_negative_evidence_complete=true
```

这三项仍是当前缺陷证据，不是修复完成证明。

## P1-P6 既有验证边界

新增六行能力范围矩阵，明确记录每个旧阶段能证明和不能证明的内容：

```text
row_count=6
old_ok_covers_p7_issue_matrix=false
p1_p6_aggregates_run_in_s0=false
```

核心结论：

- P1 证明最小纵切和选定 transition/replay/source-audit 样例，不证明全局原子性、before 校验、目标基数或护盾路由。
- P2 证明状态底座及当前语义下的样例，不证明必定施加、控制回合推进和 partial 原子性正确。
- P3 证明 setup/summon substrate，不证明真实战斗 task/effect/callback spawn。
- P4 证明数据卡与动作查询底座，不证明严格动作角色/窗口和完整 query-submit round trip。
- P5 证明参数绑定底座，不证明各伤害家族乘区或审计信息彻底退出行为输入。
- P6 证明选定架构边界回正，不证明 transition trust、reducer conflict 和全部战斗语义正确。

## 验证命令与结果

轻量主验证：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p7_s0_kernel_trust_baseline --output-dir /tmp/hsr_v8_p7_s0_kernel_trust_baseline
```

结果：

```text
v8 p7_s0_kernel_trust_baseline ok=True issues=24 probes=10/10 observed=10 p7_all_fixed=False
```

本次总门禁的关键派生判定：

```text
all_required_defects_observed=true
structured_negative_evidence_complete=true
runtime_behavior_unchanged=true
```

其中 `runtime_behavior_unchanged` 由 `git status --porcelain` 的实际路径清单派生：检查 `simulator_v8_clean_core/**/*.py` 且排除 `tools/**`，本轮命中路径为 0；不再由脚本写死为 `True`。

定向编译：

```bash
PYTHONPYCACHEPREFIX=/tmp/hsr_v8_p7_s0_pycache python3 -m compileall -q simulator_v8_clean_core/tools/validate_p7_s0_kernel_trust_baseline.py
```

结果：通过。

Patch 格式检查：

```bash
git diff --check
```

结果：通过。两个新增未跟踪文件另以 `git diff --no-index --check /dev/null <file>` 检查，无空白错误输出；该命令因存在新增 diff 按约定返回 1，不代表格式失败。

未运行：

- P1-P6 聚合：S0 未修改行为，旧聚合不能为问题基线增加证明力。
- 全量 compileall：本阶段只新增一个 Python 工具脚本。
- `validate_v0_209`：与 S0 无关且属于重验证。
- 完整 TBGD discovery/lowering：S0 所需证据来自通用内存 fixture 和当前调用链，无需读取或构建全量数据。

## 资源预算

```text
tbgd_lowering_build_count=0
full_rulebook_build_count=0
minimal_in_memory_rulebook_build_count=1
git_metadata_subprocess_count=1
child_validation_subprocess_count=0
large_artifacts_written=false
full_ir_written=false
full_transition_dump_written=false
```

## 尚未关闭的问题

`P7-I01` 至 `P7-I24` 当前仍全部是 `confirmed_open`。本 evidence 包只提交问题可重复化和归属固化材料，执行线程没有资格将任何问题标为 `accepted_fixed`，也没有资格宣告 S0 完成。

后续必须从 `P7-S1` 开始，仍需在修改前提交独立阶段执行卡并等待确认，不能根据本报告提前修改 P7 checklist。

## 当前距离

距离最小可信战斗纵切仍缺：transition trust、严格 reducer、原子提交、规则/审计分离、typed IR、动作/目标/query-submit、阶段机、timeline/control、queue、damage、shield、status、RNG、战斗中 summon 和 wave 生命周期等 S1-S17 修复。

距离完整复刻仍缺：全角色、全怪物、光锥、遗器、装备构筑、关卡环境、特殊模式以及 P3/P4/P5 既有 admission/source backlog 的后续扩面。

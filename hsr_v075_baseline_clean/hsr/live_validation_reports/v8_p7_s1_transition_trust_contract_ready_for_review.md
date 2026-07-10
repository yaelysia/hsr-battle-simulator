# v8 P7-S1 Transition 可信结果契约 ready_for_review

## 阶段边界

本 evidence 包只覆盖 `P7-S1`。执行线程没有修改 P7 checklist，没有宣告阶段完成，也没有提前实现 P7-S2 Mutation.before 冲突检测或 P7-S3 完整执行图原子提交。

当前提交状态：

```text
p7_s1_ready_for_review=true
p7_all_fixed=false
p7_done_eligible=false
```

## 核心结果

`BattleTransition` 现在包含一等、可序列化的 `outcome`：

```text
committed  -> successor_eligible=true
blocked    -> successor_eligible=false，mutation=0，before=after
diagnostic -> successor_eligible=false
```

未知或未显式分类的 transition 默认是 `diagnostic`，不会默认成功。`successor_eligible` 由 category 派生，不能与 category 独立写出矛盾值。

每个 outcome 还包含本次实际执行节点的结构化结果：

```text
node_kind
node_id
status=complete|blocked|unsupported|partial|error
reason_code
```

分类器只消费这些运行时完整性信号、candidate state 是否变化和 mutation 数量。它不读取 `coverage`、settlement、source trace 或 evidence。

可信成功还满足最小状态转移一致性门：只要 after 与 before 不同，Mutation 数量就不能为零。违反该不变量时，即使所有执行节点都是 complete，也只能得到 `diagnostic`；伪造的 committed 会被 transition contract 拒绝。Mutation.before、op 和严格 replay 链仍归 P7-S2。

## 生产链路接入

### Executor

`CombatExecutor.execute` 汇总以下结构化结果：

- target resolution。
- resource plan。
- action binding / action event / action plan。
- damage / toughness formula resolution。
- ability task / effect。
- status callback / event dispatch。
- damage / toughness / break application。

任一实际选中节点不完整时，结果是 `diagnostic`。executor 返回给正式调用者的 state 保持为输入 state；candidate after、mutation 和审计材料仍保留在 diagnostic transition 中，供 P7-S3 后续收口内部原子提交。

### Scheduler

所有生产侧 scheduler transition 构造点都显式提供 node result：

- timeline initialize / advance / turn end。
- queue enqueue / drain。
- wave transition。
- scheduler blocked。
- composite child transition。

父 transition 会继承子 transition 的节点结果。任一子项 diagnostic，父结果也不能成为正式后继。

继承时会额外保留一条 `child_transition` 身份节点；因此 diagnostic child 即使内部节点全部显示 complete，也会向父级贡献 partial 节点，不会在父级重新分类时丢失身份。

### UI / route runner

UI 状态推进和 blocked reason 现在只读取 `outcome`。`coverage` 和 settlement 仍用于展示、审计和 gap 列表，但不再决定状态是否推进。

## 轻量主验证

命令：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p7_s1_transition_trust_contract --output-dir /tmp/hsr_v8_p7_s1_transition_trust_contract
```

结果：

```text
v8 p7_s1_transition_trust_contract ok=True committed=committed blocked=blocked diagnostic=diagnostic unclassified=diagnostic
```

输出：

```text
validation_summary_p7_s1_transition_trust_contract.json
p7_s1_transition_trust_matrix.json
p7_s1_transition_trust_cases.json
```

矩阵：

| Case | Category | successor | returned state | candidate | mutations | contract | replay |
|---|---|---:|---|---|---:|---:|---:|
| 完整动作 | committed | true | 使用 after | changed | 3 | true | true |
| preflight 阻断 | blocked | false | unchanged | unchanged | 0 | true | true |
| S0 partial 直接回归 | diagnostic | false | unchanged | changed | 4 | true | true |
| 缺少必需目标 | blocked | false | unchanged | unchanged | 0 | true | true |
| 未显式分类 | diagnostic | false | unchanged | 保留原 candidate | 3 | true | true |

主验证还实际检查：

- 五类样例的 source audit 均为 `ok=true`。
- 篡改 coverage 中的 `action_enabled` / `blocked_reason` 不改变 outcome。
- UI 面对与 outcome 冲突的 coverage 时只服从 outcome。
- scheduler initialize 为 committed，无可行动者为 blocked/state unchanged。
- 伪造“含 incomplete node 的 committed”和“带 mutation/state change 的 blocked”会被 `TransitionContractValidator` 拒绝。
- after 已变化但 Mutation 为零时，分类器返回 `diagnostic/state_changed_without_mutations`；伪造 committed 会被 contract 拒绝。
- diagnostic 子 transition 内部节点即使全部 complete，scheduler 父 transition 仍为 diagnostic，并保留 partial `child_transition` 节点。
- 单体动作不提交目标时，`no_selected_target` 作为独立 preflight blocked 节点进入 outcome；最终为 blocked、零 Mutation、state unchanged。
- 全生产包 AST 扫描 66 个 Python 文件、解析错误为 0；识别出的 executor / scheduler 共 4 个生产 `BattleTransition(...)` 构造点都显式传入 outcome。
- outcome 分类器和 UI 行为函数的 AST/source 不读取 coverage、settlement、source trace 或 evidence。
- 既有 static checks 通过。

## UI 直接回归

按执行卡低优先级串行运行：

```bash
ionice -c3 nice -n 15 env PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_ui.validate --output-dir /tmp/hsr_v8_p7_s1_ui
```

结果：

```text
v8 v0_275 UI validation ok=False
```

实际只有一项失败：

```text
enemy_ai_auto_skip.ok=false
其他 UI 检查均为 true
```

该失败是当前 HEAD 已存在的验证/调度契约错位，不是 S1 outcome 迁移制造的行为回归：

- HEAD 中 UI 只在 reason=`enemy_ai_missing` 时触发临时自动跳过。
- HEAD 中 scheduler 在敌方先行动但提交命令 actor 是我方时，先返回 `manual_command_actor_mismatch`，尚未进入 enemy candidate 分支。
- `simulator_v8_ui.validate` 的 enemy-first case 仍期待 `enemy_ai_auto_skip`。

S1 没有把 `manual_command_actor_mismatch` 改写为 `enemy_ai_missing`，也没有让 UI 从 settlement 猜 expected actor；这会提前介入 P7-S8 的 query/submit 和敌我统一外部决策边界。当前记录为：

```text
classification=preexisting_validation_gap
owner_stage=P7-S8
fixed_in_s1=false
```

验收线程需独立判断该既有 gap 是否阻断 S1；执行线程不把失败隐藏为绿，也不越界修复。

## 编译与格式检查

执行卡要求的定向 compileall：通过。

`git diff --check`：通过。

三个新增未跟踪文件另以 `git diff --no-index --check /dev/null <file>` 检查，无空白错误输出；该命令因存在新增 diff 返回 1，不表示格式失败。

## 资源预算

轻量主验证：

```text
tbgd_read_count=0
full_rulebook_build_count=0
minimal_in_memory_rulebook_build_count=1
large_artifacts_written=false
full_transition_dump_written=false
```

UI 直接回归是唯一完整 RuleBook 重验证，已使用 `ionice -c3 nice -n 15` 单独串行运行，输出仅写入 `/tmp`。未并行运行其他重验证。

## 未运行

- P7-S0 整体脚本：它包含 S0 历史阶段的 runtime-unchanged 门；S1 修改 runtime 后不应作为直接回归。S0 partial fixture 已由 S1 主验证直接复用。
- P1-P6 聚合：默认保留到 P7-S19。
- `validate_v0_209`：本阶段未修改 direct damage、crit 或 RNGEvent schema。
- 完整 discovery / canonical IR / coverage / fidelity 写出：S1 无此需要。

## Deferred

- P7-S2：Mutation.before、op、同路径冲突和 replay 严格校验。
- P7-S3：把 diagnostic candidate 的内部 mutation 计划接入统一原子提交门，使 transition.after 本身也回到 before、正式 mutation 数为零。

S1 当前保证的是：任何 incomplete、unknown 或矛盾结果都不能冒充正式后继。

## 当前距离

距离最小可信战斗纵切仍缺 P7-S2 至 P7-S17 的 reducer、原子提交、规则/审计分离、typed IR、动作/目标/query-submit、阶段机、timeline/control、queue、damage、shield、status、RNG、战斗中 summon 和 wave 修复。

距离完整复刻仍缺全角色、全怪物、光锥、遗器、装备构筑、关卡环境、特殊模式及既有 admission/source backlog 的后续扩面。

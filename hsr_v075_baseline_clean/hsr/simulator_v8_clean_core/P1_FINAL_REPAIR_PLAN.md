# P1 最终收口修复计划

本文档是第一阶段 P1 的最终收口计划，只处理当前仍阻塞 P1 最小完整战斗纵切验收的事项。执行线程应按本文完成后再申请验收，不要继续扩大第一阶段范围。

一句话目标：

```text
补完反击队列端到端正例，并同步所有过期验收文档，使 P1 聚合报告可以诚实地从 minimum=false 变成 minimum=true。
```

执行状态：

```text
已由提交 1b88c70 v8 p1 final counter acceptance 完成。
当前事实以 v8_p1_final_acceptance_checkpoint_v0_292.md 和 CODEX_HANDOFF.md 为准。
```

## 1. 执行前真实状态

执行前验收结果：

```text
P1 底座：通过
P1 最小完整战斗纵切：未通过
唯一机制 blocker：反击队列语义
```

当前已经完成、不要重复返工：

- 外部推演器显式选择行动，core 不做敌方 AI。
- 单位出生、死亡、退场、回放。
- 波次系统最小推进。
- 普通召唤物。
- servant / 忆灵最小可执行纵切。
- 状态基础生命周期、概率、抵抗、免疫、确定性驱散、DoT、过期。
- 目标系统第一阶段关键子集。
- RNG 基础和显式分支记录。
- BattleSetup 最小入口。
- P1-9 聚合报告底座。

当前不作为 P1 blocker：

- assistant 机制完整执行。当前只要求边界清楚，不冒充完成。
- battle unit summon 自动开局生成。当前按定义/catalog 边界处理。
- 随机驱散。当前没有真实来源。
- 叠层同时刷新持续时间的组合正例。当前没有组合来源。
- follow-up。当前没有发现第一阶段可执行来源，不阻塞 P1。

当前必须完成：

- 反击：数据里已有真实来源，但目前只作为通用插入行动被发现，还没有作为“反击机制”形成端到端正例。
- 文档同步：部分 checklist / handoff 仍保留旧结论，尤其 servant/忆灵缺失的表述已经过期。

## 2. 不允许做的事

- 不要新增敌方 AI。
- 不要把特定角色名、技能名、怪物名写进 runtime。
- 不要为了让 P1 通过造 synthetic 反击样例。
- 不要把“通用插入行动可执行”当成“反击完成”。
- 不要因为验证脚本输出 ok 就直接宣称 P1 完成，必须看 P1 minimum 和 blocker 列表。
- 不要跑高 IO 全量旧验证脚本，除非本次修改确实触达对应旧底座且轻量验证无法覆盖。

## 3. P1-FINAL-1 反击队列端到端

### 目标

证明游戏中的反击机制在 v8 中能被真实来源驱动，并以通用、可扩展的方式进入队列、结算、回放和来源审计。

需要证明的游戏链路：

```text
单位被攻击
→ 反击条件满足
→ 生成反击行动
→ 反击进入待结算队列
→ 普通行动被正确暂停或等待
→ 反击按队列规则执行
→ 目标、伤害/效果、来源、回放都可追踪
```

### 要做

1. 重新选择反击正例。
   - 按结构化条件选样：受击相关事件、触发后插入技能行动、目标指向攻击者或事件目标、来源中带反击语义。
   - 不按固定角色名、固定技能名、固定文件名选择。
   - 如果当前真实来源都集中在同一角色，也只能把它当作“结构化谓词筛出来的样例”，不能在主路径写死角色。

2. 明确反击和通用插入行动的关系。
   - 可以继续让 runtime 用通用插入行动执行。
   - 但验证和审计必须能说明这一条通用插入行动是反击。
   - 推荐保留通用队列 family，同时增加或使用“语义 family / 机制标签”来标记反击，不要求大改队列核心。

3. 补触发链路。
   - 攻击或受击事件必须带足够 payload，让反击条件能判断。
   - 反击来源必须能追到真实状态监听或能力配置。
   - 不能由验证脚本直接手塞一个伪造队列项冒充触发结果。

4. 补队列入列和结算。
   - 反击入列后，普通输入应被挡住或等待队列结算。
   - 队列 drain 后执行反击行动。
   - 反击行动的 actor、target、来源、能力、优先级必须可审计。
   - 如果目标死亡、攻击者不存在、actor 被移除，必须 blocked 或跳过，并记录原因。

5. 补回放和来源审计。
   - 反击入列、出列、执行产生的 transition 必须能 replay。
   - settlement 能追到 mutation 或明确 process-only。
   - runtime source audit 能从反击结果追回真实来源。

6. 补负例。
   - 反击条件不满足，不入列。
   - 反击 actor 死亡或退场，不执行。
   - 反击 target 不存在或不可选，不假执行。
   - 受击事件缺关键 payload，不假执行。
   - 来源不完整时，不把通用插入行动冒充反击。

### 验收结果

必须满足：

- P1-5 报告中反击不再是“来源不存在”或“只发现但未接通”。
- 反击有真实来源正例。
- 反击端到端 transition 通过 replay。
- 反击来源审计通过。
- 反击负例不产生假 mutation。
- P1-9 中反击不再阻塞最小纵切。

## 4. P1-FINAL-2 聚合验收收口

### 目标

让 P1-9 成为最终可信验收入口，而不是只表示底座可运行。

### 要做

1. 更新 P1-9 聚合判断。
   - 反击正例通过后，`phase1_minimum_battle_slice` 才能为 true。
   - `p1_9_done_eligible` 必须跟随 minimum 结果。
   - blocker 列表必须为空。

2. 更新 P1-5 队列矩阵。
   - 明确区分：通用插入行动、反击语义、assistant 边界、follow-up 当前无来源。
   - 反击不能再只靠文本 hint 被发现后停在 gap。
   - 反击必须有端到端正例记录。

3. 保留非 blocker 的诚实记录。
   - assistant 仍可记录为边界项。
   - battle unit summon 仍可记录为边界项。
   - 随机驱散、叠层+刷新组合、follow-up 仍按当前来源状态记录，不阻塞 P1。

### 验收结果

P1-9 summary 应达到：

```text
ok=True
p1_9_done_eligible=True
phase1_repair_substrate_accepted=True
phase1_minimum_battle_slice=True
phase1_minimum_battle_slice_blocked_by=[]
```

## 5. P1-FINAL-3 文档同步

### 目标

把旧文档中的过期结论全部清掉，避免后续线程继续按旧 blocker 工作。

### 要做

更新：

- `FIRST_PHASE_TASK_CHECKLIST.md`
- `CODEX_HANDOFF.md`
- 新增或更新最终 P1 验收报告。

必须改掉的旧结论：

- servant / 忆灵仍是 implementation_missing。
- servant initial setup 仍是 blocked。
- P1 minimum 仍固定 false。
- 反击不存在或不需要。

最终文档应表达：

```text
P1 最终 blocker 已清空。
反击已完成第一阶段真实来源端到端正例。
assistant / battle unit summon / random dispel / stack+duration refresh / follow-up 不阻塞 P1。
P1 后续进入第二阶段，而不是继续第一阶段修补。
```

## 6. 最小验证范围

必跑：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_5_queue_window_system --output-dir /tmp/hsr_v8_p1_5_counter_final
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_counter_final
git diff --check
```

直接回归：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_0_action_boundary --output-dir /tmp/hsr_v8_p1_0_after_counter_final
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_4_status_system --output-dir /tmp/hsr_v8_p1_4_after_counter_final
```

触发条件：

- 如果改了伤害事件、受击事件或状态监听分发，必须跑 P1-4。
- 如果改了 action availability 或普通输入阻塞，必须跑 P1-0。
- 如果改了 unit lifecycle，必须跑 P1-1。
- 如果改了 target resolution，必须跑 P1-6。
- 如果改了 RNG 选择或概率分支，必须跑 P1-7。

不默认运行：

- `validate_v0_204`
- `validate_v0_209`
- 任何会写完整 CanonicalIR / coverage / fidelity 的高 IO 脚本。

## 7. 最终交付物

执行完成后应交付：

- 反击端到端实现或 admission 修正。
- 反击正例和负例验证。
- P1-5 验证报告。
- P1-9 最终聚合报告。
- 更新后的 checklist / handoff。
- 一个 git 检查点。

最终验收时只看三件事：

```text
1. 反击是否真实来源端到端通过。
2. P1-9 minimum 是否为 true 且 blocker 为空。
3. 文档是否不再保留过期 blocker。
```

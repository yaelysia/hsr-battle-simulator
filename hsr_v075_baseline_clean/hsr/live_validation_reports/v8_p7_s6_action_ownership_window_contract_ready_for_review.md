# P7-S6 动作所有权、角色与窗口契约待验收报告

状态：`ready_for_review=true`。本报告仅作为统一验收的证据索引，不宣告阶段完成，不修改 P7 checklist。

## 本阶段结果

- 新增一等 `ActionAdmissionIR`：稳定记录 owner entity、action/level、动作角色、submission mode、合法窗口、控制方、资源门及真实 source。
- lowering 只根据结构化 `ActionDefinitionIR.attack_type` 与 CombatantActionSet 数据卡归属投影角色：普通/战技/servant 回合动作、终结技插入动作、被动触发、场景外动作和未知 blocked；不读取名称或固定 ID 猜分类。
- 角色、怪物和 servant 都通过同一 `ActionAdmissionIR`/RuleBook 索引声明动作；重复或缺失 admission 不取首项。
- 新增共享 `ActionContractSystem`。ActionAvailability 与 CombatExecutor 共同使用它检查 actor 生命周期、状态控制、owner、role、submission mode、turn owner、window、资源和选中 action graph 完整性。
- executor 在 `require_action_definition` 前执行共享契约；未知 action、其他单位 action、被动直提、终结技直提、错误窗口、资源不足和已知不完整 action graph 均返回 blocked/state unchanged/zero mutation。
- 外部命令不能靠 `metadata.is_insert_action`、伪 `source=queue` 或伪 queue metadata 获得插入/队列权限。scheduler 内部队列执行使用独立 `ActionSubmissionAuthorization`，并校验 actor、owner、action、level、window 和 source identity。
- ActionChoice 现在机器可读地包含 admission ID、owner、action role、allowed windows 和 submission modes。

## 结构化验证证据

主验证：

```text
nice -n 10 python3 -m simulator_v8_clean_core.tools.validate_p7_s6_action_ownership_window_contract --output-dir /tmp/p7_s6_main_final
```

结果：`ok=true`、`ready_for_review=true`、`roles=6`、`negative_cases=10`。

验证实际覆盖：

- 角色矩阵：Normal、BPSkill、Ultra、无 AttackType 被动、Maze 场景外和未知类型；全部由结构字段判定。
- 查询/提交 round trip：查询返回的普通动作携带完整 admission 契约，补入查询给出的合法目标后由 executor committed；mutation replay 与 source audit 均通过。
- insert window 的内部契约正例通过，未就绪能量会由统一资源门阻断。
- 10 个负例：错误 owner、其他 owner action、错误窗口、被动直提、终结技直提、伪 insert metadata、伪 queue source、资源不足、已知不完整 action graph、未知 action；全部 blocked、state unchanged、zero mutation、不可作为后继。
- 完整 lowering 一次，得到 `ActionAdmissionIR=18843`：`executable=18738`、`blocked=105`；角色、怪物、servant 各按结构谓词抽到一个真实 turn-action admission，未固定角色/怪物/技能 ID。
- 当前角色卡虽有真实 action admission，但没有一个角色 action 的已选 runtime graph 全部可执行；query 因此不再暴露伪可提交角色动作，该事实在迁移后的 P4-S2 中记录为 `implementation_missing`。

输出：

- `/tmp/p7_s6_main_final/validation_summary_p7_s6_action_ownership_window_contract.json`
- `/tmp/p7_s6_main_final/p7_s6_action_role_matrix.json`
- `/tmp/p7_s6_main_final/p7_s6_action_ownership_window_evidence.json`

## 直接回归与资源情况

- P4-S2 combatant action availability：迁移后 `ok=true`，7 cases；分类为 `executable=1`、`implementation_missing=1`、`boundary_only=4`、`source_absent_not_required=1`。迁移没有把 gap 改成正例，而是验证 admission 存在且不完整 graph 不被 query 暴露。
- P7-S1：`ok=true`；diagnostic 夹具迁移为显式“候选变化 + unsupported 选中节点”，不再依赖 S6 已提前阻断的 partial action。
- P7-S3：`ok=true`，9 cases；executor diagnostic 负例使用“IR 声称 task executable、runtime 仍无法执行”的矛盾夹具，继续验证原子门。
- P7-S4：`ok=true`，11 ownership rows。
- P7-S5：`ok=true`，6 rows。
- `compileall`：通过。
- `git diff --check`：通过。
- P1-0 action boundary 串行运行时在其 queue-mandatory counter 样例选择阶段失败：当前完整 IR 中没有通过 S4 source-mode admission 的 counter listener，失败发生在 action preflight case 之前。该结果不记为通过；它属于后续 P7-S8 queue/scheduler 直接回归的已知验证/source-admission gap。
- 全量 lowering 均低优先级串行并只写 `/tmp` 摘要；未写完整 CanonicalIR/transition dump，未运行 P1-5。

## 明确未做

- 未实现复杂目标选择/影响组，归 P7-S7。
- 未重做 scheduler 决策循环或 queue drain，归 P7-S8。
- 未把当前真实角色 action graph 的大量视觉/条件/效果缺口伪装成 executable；角色完整可提交正例仍是后续实现缺口。
- 未修改 P7 checklist，未提交 Git 检查点。

## 统一验收反例修正补充

验收发现调用者可公开构造 `ActionSubmissionAuthorization` 绕过 insert/queue 门。现授权包含由内核 issuer 创建、绑定完整 claims 与 state revision 的进程内 capability seal；公开构造、字段篡改或跨状态复用均返回 `action_submission_authorization_not_issued/state_mismatch`，零 mutation、state unchanged。queue scheduler 已改用 issuer。seal 不调用战斗 RNG，也不引入进程随机数。

同时，空 `attack_type` 与字面 `Unknown` 不再默认成为 executable passive；只有明确的 `Talent` / `Passive` / `TalentPassive` 分类可投影 passive role，未知分类保持 `unknown + action_role_classification_missing`。S6 未重跑全量 lowering；角色矩阵、query-submit、issued insert、forged authorization、未知分类和静态边界轻量子集全部通过。

最终复跑复用了 S16/S17 已构建的 CanonicalIR：`ok=true`，角色/怪物/servant 三类真实来源样例仍通过，`lowering_build_count=0`。同时新增统一 ability task contract：明确列出的视觉/同步 opcode 只产生 process-only complete，未知 opcode 仍 blocked；`PredicateTaskList` 和 `SummonMonster` 必须分别有 executable typed condition/intent 才能进入 selected graph，不能因 EffectIR 为 audit-only 或外观任务存在而宽泛放行。

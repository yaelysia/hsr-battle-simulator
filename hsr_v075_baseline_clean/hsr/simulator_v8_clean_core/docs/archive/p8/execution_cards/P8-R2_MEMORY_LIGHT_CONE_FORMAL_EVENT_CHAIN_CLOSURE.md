# P8-R2 记忆光锥正式事件链与目录启动收口执行卡

> **两次阻断后修订（2026-07-28）**
>
> 未过滤运行和九族过滤运行均已按暂停条件停止。后续施工必须先读取
> `P8-R2_REVIEW_DELTA_AFTER_UNFILTERED_FAILURES.md`。该文件已改为两次暂停后的
> 最终差量卡，对剩余生产根因、基础类型来源和验证成本的裁决覆盖本卡旧口径。
> 不得再运行未过滤矩阵或九族组合。

## 执行配置

- 阶段：P8-R2。
- 对应问题：P8-I20。
- 任务性质：关闭 P8-R1 运行时修复与 CHAR-M1 构筑补全后，仍留在正式光锥事件链中的三个已确认业务失败。
- 硬前置：当前分支必须包含 `419e476`，并保留已验收的 CHAR-M1、P8-R1-RUNTIME、VG-S1、VG-S2 和 VG-R1。
- 推荐模型：5.6 Sol。
- 推荐推理等级：`max`。
- 推荐执行模式：普通聚焦模式；若使用 Goal 模式，Goal 只能覆盖本卡。
- 最终状态：只能提交 `ready_for_review`，不得勾本卡或 P8 总 checklist，不得提交 Git，不得进入 P8-S18 或其他阶段。

## 读取范围

开始前只读以下文件，不重新通读 P8 历史：

1. `CODEX_HANDOFF.md`
2. `ARCHITECTURE_BOUNDARY_CONTRACT.md`
3. `FORBIDDEN.md`
4. 本执行卡
5. `docs/AGENT_WORKFLOW_AND_VALIDATION.md`
6. `live_validation_reports/v8_vg_r1_p8_s8_task_event_shared_evidence_ready_for_review.md`

需要追查已验收前置时，只按关键词读取：

- `docs/character_execution_cards/CHAR-M1_MEMORY_OWNED_COMBATANT_BUILD_CLOSURE.md`
- `P8-R1_SUMMON_RUNTIME_HALO_LIFECYCLE_REPAIR.md`
- `../../validation_governance/execution_cards/VG-R1_P8_S8_TASK_EVENT_SHARED_EVIDENCE_PILOT.md`

## 前因后果

原始正式目录启动曾暴露三张记忆相关光锥无法闭合。随后完成了两类前置修复：

1. CHAR-M1 建立了记忆角色与忆灵的正式 owned-combatant 构筑、身份、属性、动作和准入链。
2. P8-R1-RUNTIME 建立了合法空召唤运行时、召唤关系双向校验和通用光环生命周期。

其中原三张来源里的光环路径已经由 P8-R1-RUNTIME 关闭。VG-R1 之后用低内存窄投影首次完整执行当前源码下的 task/event 业务矩阵，证明目录并非单纯“尚未补证”，而是仍有三个真实失败：

```text
SetDynamicValueByCopying:s8
SetModifierDynamicValue:s8
OnDeathrattle:s8
```

三个 family 分布在两条真实光锥来源路径：

- `Config/ConfigAbility/Equip/Equip33.json`
  - 父状态监听单位创建。
  - 只有新建单位与装备者的真实忆灵集合相交时，才给该忆灵添加子状态。
  - 子状态在攻击后复制并更新父子状态中的动态值。
- `Config/ConfigAbility/Equip/Equip36.json`
  - 父状态在已有忆灵上安装监听，也监听后续单位创建。
  - 只有新建实体是装备者自己的忆灵时，才给它安装死亡回响监听。
  - 忆灵进入真实死亡回响窗口后执行对应资源和条件任务。

这些路径的 lowering、任务实现和来源绑定已经存在。当前失败发生在父状态到子状态的正式事件链：

- 合法空目标在身份比较中仍被当作“必须正好有一个目标”的错误。
- 单位创建事件的参数实体与预解析目标没有在所有正式入口保持一致。
- 正式忆灵出生后，监听器必须在同一条提交链中看到新单位、owner/summoner 关系和召唤索引，再据此安装子状态。

因此本卡不是重做记忆构筑，也不是重做光锥机制图，更不是再做一次通用光环系统。目标是回正通用目标条件和召唤单位创建事件链，使已经存在的真实光锥图能够自然执行。

## 当前代码事实

### 1. 目标解析已经具备三态基础

`TargetExpressionResult` 已能区分：

- `ok=true` 且目标非空。
- `ok=true` 且目标为空。
- `ok=false` 且带明确错误。

`CasterServant` 和 `GetServant` 在召唤运行时合法但当前没有忆灵时，已经能够返回成功的空集合。损坏的 schema、关系索引或单位映射仍会返回 blocked。

### 2. 条件消费仍有语义偏差

`ByTargetListIntersects` 的集合交集本身支持空集合为 `false`，但其前置目标上下文仍可能把事件参数实体记为未解析。

`ByCompareTarget` 当前要求左右目标数量都严格等于一。因此一边是已成功解析的空忆灵集合时，会返回 `target_identity_requires_singleton`，并把整个正式场景构建阻断。

### 3. 召唤出生与事件由不同层负责

`SummonSystem` 负责形成单位 mutation、召唤运行时 mutation、光环对账和出生事件；事件 dispatcher 负责消费 `unit.created` 并执行监听器。不能简单让 `SummonSystem` 直接接管 dispatcher。

正确边界是：负责提交召唤 transition 的生产协调层，必须先形成包含新单位和完整关系的候选状态，再让 `unit.created` 监听器在该候选状态上执行；任一步失败时由原子提交边界整体回滚。

### 4. 当前验证已有低内存入口

VG-R1 已将 task/event 业务矩阵改为：

- 完整 `TBGDLowering.build()` 调用 0 次。
- owned-combatant 窄投影 1 次。
- focused bundle 1 次。
- common evidence 1 次。

最后一次未过滤组合峰值约 588 MiB。旧完整 lowering 的 4 GiB `MemoryError` 仅保留为历史成本基线，不得重新运行。

## 阶段完成后的结果

本卡完成后必须同时成立：

1. 没有忆灵时，涉及“装备者的忆灵”的目标表达式是合法空集合；依赖它的普通条件得到 `false` 或合法 no-effect，不阻断正式场景。
2. 目标表达式、事件参数或召唤关系确实损坏时仍 blocked，不能被空集合语义掩盖。
3. 真实忆灵出生时，创建事件能够看到已提交候选中的新单位、owner、summoner 和召唤索引。
4. Equip33 来源链在真实忆灵出生后安装子状态，并在真实攻击后执行两条动态值 family。
5. Equip36 来源链在真实忆灵出生后安装死亡回响监听，并在真实死亡回响事件中执行。
6. 当前已发布光锥正式目录启动失败数为零，task/event family 业务失败数为零。
7. VG-R1 中为这三个失败保留的临时允许集合被删除，不留下永久豁免。

## 详细目标

### 1. 回正身份条件对合法空目标的解释

`ByCompareTarget` 是实体身份比较，不是动作选目标。它必须按目标解析结果处理：

- 任一操作数解析失败：条件 blocked，state unchanged。
- 左右各一个实体：比较稳定实体身份并返回真或假。
- 任一操作数是已成功解析的空集合：条件返回 `false`，不是 blocked。
- 任一操作数包含多个实体：继续 blocked，除非未来 raw opcode 明确提供集合比较语义。

不得把“零个目标”和“目标表达式损坏”合并。也不得为修复当前来源，把所有 singleton 错误都改成 `false`。

### 2. 保证事件参数实体进入同一套类型化目标上下文

所有正式状态回调中的 `ParamEntity` 必须来自当前生产事件的类型化身份：

- `unit.created` 使用刚创建的单位。
- 动作、伤害、资源和其他事件继续使用各自已定义的参数实体。
- 预解析目标组和条件求值必须引用同一身份，不能一个读取 `GameEvent.target_id`，另一个读取缺失字段。

当前来源需要的 `ByTargetListIntersects(CasterServant, ParamEntity)` 必须满足：

- 当前没有忆灵时：空集合与当前事件实体不相交，结果为 `false`。
- 当前事件实体是装备者自己的忆灵时：结果为 `true`。
- 当前事件实体是普通角色、敌人或其他人的忆灵时：结果为 `false`。
- 参数实体缺失、引用不存在单位或来源上下文互相矛盾时：blocked。

不得绕过 TargetSystem 后在条件 evaluator 中手工猜测召唤关系。

### 3. 闭合召唤出生后的正式创建事件顺序

正式忆灵出生 transition 必须在监听器执行前具备以下一致视图：

- 新 `UnitState` 已存在于候选状态。
- 新单位的 owner 和 summoner 已写入单位身份。
- `summon_runtime.entities`、owner 索引和 servant 索引已经同步。
- P8-R1 光环对账已经基于同一候选状态完成。
- `unit.created` 的参数实体明确指向该新单位。

事件只能派发一次。不得同时把显式 spawn event 和 mutation-backed event 当作两个创建事件重复执行。

若监听器、关系校验、状态添加或后续完整性门失败，不能留下以下半提交状态：

- 单位已出现但召唤索引没有它。
- 索引已有单位但 `UnitState` 不存在。
- 子状态已添加但单位出生被回滚。
- 创建事件已记录为成功但对应 mutation 未提交。

修复应落在现有 transition 协调和原子提交边界中，不能让 SummonSystem、事件 dispatcher 和验证器各自维护一套顺序。

### 4. 闭合 Equip33 的父子状态与动态值链

正式、来源真实的执行链必须证明：

1. 光锥启动后，父状态存在于装备者。
2. 战场当前没有忆灵时，单位创建监听合法执行但条件为假，不添加伪子状态。
3. 使用 CHAR-M1 已准入的真实 owned-combatant build 和真实 spawn source 生成忆灵。
4. 忆灵创建事件命中父状态监听，并在该忆灵上恰好添加一次真实子状态。
5. 子状态保存的 caster、owner、summoner、父状态身份、动态值和来源均可反查。
6. 忆灵通过正式动作或正式攻击事件进入 `OnAfterAttack`。
7. `SetDynamicValueByCopying:s8` 从真实 summoner 父状态读取并写入子状态。
8. `SetModifierDynamicValue:s8` 按原图更新对应父状态动态值。
9. settlement、mutation、事件、snapshot 和 replay 能还原同一结果。

不能预先把子状态塞进 fixture，也不能直接调用子回调来代替父监听安装。

### 5. 闭合 Equip36 的创建监听与死亡回响链

正式、来源真实的执行链必须证明：

1. 光锥启动后父状态存在。
2. 开局没有忆灵时，已有忆灵目标为空只产生合法 no-effect。
3. 初始角色的 `unit.created` 事件与空忆灵比较得到 `false`，场景仍可进入战斗。
4. 真实忆灵出生后，`ParamEntity` 与装备者的忆灵身份比较得到 `true`。
5. 死亡回响监听只安装在该真实忆灵上，且只安装一次。
6. 其他单位或其他角色的忆灵不会误装监听。
7. 忆灵通过正式生命周期进入真实 `OnDeathrattle` 窗口。
8. 回调中的条件、资源变化、settlement、事件和 replay 全部来自现有机制图。

不能手工构造 `OnDeathrattle` 回调成功记录，也不能直接把监听状态塞入忆灵。

### 6. 退役 VG-R1 临时业务缺口豁免

当前验证器中的三项允许失败集合只是 VG-R1 治理试点期间的事实边界，不是产品契约。

三项 family 全部修复后必须：

- 删除 `P8_R1_CONFIRMED_BUSINESS_GAPS` 及仅为它服务的判断函数，或将该临时分支完整退役。
- 业务 `ok=false` 时 CLI 继续退出非零。
- 治理结果不得覆盖业务失败。
- 不把允许集合改名、迁移到配置或留成空壳兼容层。
- 不新增 R2 专用豁免。

## 架构与来源约束

- 生产代码只能依据 Canonical IR、类型化目标表达式、正式事件和已提交战斗状态。
- `Equip33.json`、`Equip36.json`、光锥 ID 和 modifier 名只用于来源审计、验证选样和报告定位。
- 禁止在 target、condition、summon、status、event 或 executor 中按装备身份分支。
- 禁止伪造 servant、spawn source、父状态、子状态、事件或能力图。
- 禁止强制记忆角色开局生成忆灵；真实出生时机仍由内容机制决定。
- 禁止重做 CHAR-M1 构筑、P8-R1 光环或 S8 已闭合的动态任务实现。
- 禁止把条件型动态效果折算到静态面板。
- 禁止从 raw TBGD 在 runtime 临时查规则。
- blocked 路径不得提交 gameplay mutation，也不得产生派生 gameplay event 或 RNG 消耗。触发它的既有事件和 process-only 诊断记录可以保留，但不能伪造成功 settlement。

## 本阶段只做

- 修正类型化目标条件对合法空集合和事件参数实体的解释。
- 修正正式召唤出生 transition 与创建事件的必要协调顺序。
- 让两条真实光锥来源的父状态、子状态和后续事件链自然闭合。
- 删除三项临时业务失败豁免。
- 更新现行低内存 P8-S8 证据，使目录事实回到 `ok=true`。

## 本阶段不做

- 不扩面其他记忆角色、忆灵技能或出生来源。
- 不修改遗器轨、UI、推演器、敌方 AI 或关卡内容。
- 不重新 lower 全部角色、怪物或完整 Canonical IR。
- 不建立新的通用验证注册表、selector、缓存框架或元验证器。
- 不为了让旧脚本通过而恢复旧事件名、旧接口或兼容分支。
- 不把当前两个来源样例写成内核中的固定规则。

## 验收矩阵

| 验收目标 | 必须成立的结果 | 不能接受的替代证据 |
|---|---|---|
| 合法空目标 | 解析成功、条件为假、场景继续 | 捕获异常后忽略 |
| 损坏目标 | blocked 且 state unchanged | 当作空集合 |
| 单实体身份 | 同一实体为真，不同实体为假 | 按名称或模板 ID 比较 |
| 多实体身份 | fail-closed | 取第一项 |
| 创建事件上下文 | 参数实体是新生单位且存在于候选状态 | 验证器手填别名 |
| 召唤关系可见 | 监听器同时看到 owner、summoner 和索引 | 事件后补关系 |
| Equip33 父链 | 真实出生事件安装真实子状态 | fixture 预装子状态 |
| Equip33 子链 | 两条动态值 family 都产生正确 mutation | 只证明回调可查询 |
| Equip36 父链 | 空时不阻断，真实忆灵出生时命中 | 强制开局出生 |
| 死亡回响 | 正式生命周期事件执行真实回调 | 直接调用 callback |
| 原子性 | 任一失败整体不提交 | 清理残留状态后算通过 |
| 来源审计 | mutation 回到 IR 节点和 raw 记录 | 手工 source_trace |
| replay | 重放得到相同状态和事件顺序 | 只比最终面板 |
| 当前目录 | 已发布定义装备侧启动失败为 0 | 只测两张样例 |
| 当前 family | task/event 业务失败为 0 | governance 豁免标绿 |

## 必须覆盖的负例

1. 合法空 summon runtime，当前没有忆灵。
2. summon runtime 缺失、schema 错误或 owner 索引损坏。
3. `ParamEntity` 缺失、指向不存在单位或与事件目标矛盾。
4. 身份比较一侧为空、两侧各一项、一侧多项。
5. 事件实体是普通角色、敌方单位、其他装备者的忆灵。
6. 伪造 owner、summoner、召唤种类或阵营。
7. 创建事件重复派发，不得重复安装子状态。
8. 子状态来源身份与父状态不一致。
9. 出生后监听失败，整个 transition 不得残留半提交状态。
10. 伪造死亡回响事件或在非死亡回响窗口触发。
11. 篡改 snapshot 中的召唤关系、状态来源或动态值后 replay 拒绝。
12. 业务失败存在时，CLI 必须退出非零。

## 预计触达范围

执行线程必须先用 CodeGraph 复核实际调用链。预计可能触达：

- `rules/evaluator.py`
- `systems/target.py`
- `systems/status_callbacks.py`
- `systems/summon.py`
- 负责提交召唤结果和派发其事件的现有生产协调层
- `systems/event_dispatch.py`
- `systems/mutation_events.py`
- `core/atomic_commit.py` 或现有完整性门，仅在当前原子边界确实缺口时
- `tools/validate_p8_s8_light_cone_remaining_gameplay_closure.py`
- 本阶段 `ready_for_review` 报告

这不是拟改文件配额。若实际根因只需修改更小范围，应保持更小范围；若需要修改角色构筑、光环模型或装备专用 runtime，必须暂停并交回规划线程。

## 验证设计

### 1. 修改前

不要重跑 13 分钟的未过滤组合。以检查点 `419e476` 和 VG-R1 当前源码证据作为修改前基线，只做：

- CodeGraph 调用链核对。
- 当前三项 failure row 与真实 raw 来源核对。
- 工作区和 source fingerprint 核对。

若当前 family 集合、来源路径或失败原因已变化，先停止并报告，不得按旧卡继续。

### 2. 开发循环

开发期间只运行一次共享 bundle 的三个 family 过滤组合：

```bash
cd hsr_v075_baseline_clean/hsr
mkdir -p /tmp/p8_r2_filtered
ulimit -v 4194304
exec /usr/bin/time -v \
  -o /tmp/p8_r2_filtered/time-v.txt \
  ionice -c 3 nice -n 15 env \
  PYTHONDONTWRITEBYTECODE=1 \
  python3 -m simulator_v8_clean_core.tools.validate_p8_s8_light_cone_remaining_gameplay_closure \
  --contract-slice task \
  --contract-slice event \
  --task-family SetDynamicValueByCopying:s8 \
  --task-family SetModifierDynamicValue:s8 \
  --event-family OnDeathrattle:s8 \
  --tbgd-root ../../turnbasedgamedata-main \
  --output-dir /tmp/p8_r2_filtered
```

过滤运行的 `governance_ok` 可能因“不是未过滤组合”而为假；不得修改治理规则把它伪装成全量通过。开发判断只看三个所选 family 的业务结果、负例和资源计量。

修复失败时只重跑受影响 family，不重复执行未受影响的完整组合。

### 3. 直接回归

按实际生产调用链选择，不允许全部无条件运行：

- 修改召唤、出生事件或光环协调：运行 `validate_p8_r1_summon_runtime_halo_lifecycle`。
- 修改目标解析通用语义：运行现行目标条件聚焦矩阵；若旧 P1 脚本仍依赖完整 lowering，只迁移与本次直接相关的有效谓词，不兼容过时假设。
- 修改原子提交：运行 `validate_p7_s3_selected_graph_atomic_commit`。
- 修改 snapshot / replay 数据：运行 `validate_p7_s15_rng_identity_replay`。
- 只修改条件 evaluator 时，不运行无调用链的伤害、护盾、波次和完整 P1-P7 聚合。

新增验证必须直接证明生产契约。禁止另写一个大型 validator 来验证 P8-S8 validator；纯验证代码不得因本卡形成新的重复场景构建框架。

### 4. 最终业务证明

三个 family 过滤组合与负例全绿后，只允许各运行一次：

1. 未过滤 task + event 共享组合，证明当前所有 task/event family 业务失败为零。
2. 完整 `--catalog-startup-only` 低内存入口，证明当前已发布光锥装备侧启动失败为零。

两项必须严格串行。若能在不新增通用调度框架、不复制场景构建且验证代码不净膨胀的前提下，让 catalog 消费同一 focused bundle，可以合并为一次进程；否则保留两个简单入口，不为节省一次最终构建制造新的验证架构。

明确禁止：

- 完整 `TBGDLowering.build()`。
- P1-P7 聚合。
- `validate_v0_209`。
- 旧 1.5 GiB 目录验证路径。
- 完整 Canonical IR、RuleBook、transition 或 replay dump。
- 同时运行任何两个重验证。

### 5. 快速检查

- 对实际修改的 Python 文件运行 `compileall`，缓存写入 `/tmp`。
- `git diff --check`。
- 核对没有 `.pyc`、`__pycache__` 或大体积证据进入工作区。

## 资源上限

- 完整 lowering 调用数：0。
- 每个共享组合中 owned-combatant 窄投影、focused bundle、common evidence 各 1 次。
- 开发期间不运行未过滤组合。
- 最终未过滤 task/event 组合最多 1 次。
- 最终完整 catalog startup 最多 1 次。
- 地址空间上限：4 GiB。
- 预期峰值应保持在 VG-R1 约 0.6 GiB 的量级；超过 1 GiB 必须先停止检查是否恢复了重复构建。
- 所有产物写入 `/tmp`，报告只保存摘要、失败矩阵、来源样本、原子性样本和资源计量。

## 暂停条件

出现以下任一情况必须停止并交回规划线程：

- 当前三项失败不再来自本卡记录的两条真实来源。
- raw 来源要求多个同时 owned servant 的新集合身份语义。
- 修复必须按光锥、角色、modifier 名或固定 ID 分支。
- 正确出生时机缺少真实 spawn source，需要内容卡扩面才能证明。
- 需要恢复旧事件名、旧 runtime adapter 或兼容层。
- 低内存窄投影重新超过 1 GiB，或出现完整 lowering 调用。
- 最终未过滤组合出现本卡之外的新业务失败。

## 交付物

- 通用生产修复。
- 三个 family 的来源真实过滤证据。
- 合法空、损坏目标、错误归属、重复事件和原子回滚负例。
- 当前未过滤 task/event 业务摘要。
- 当前完整 catalog startup 摘要。
- settlement、source walkback、snapshot / replay 证据。
- 资源计量。
- `live_validation_reports/v8_p8_r2_memory_light_cone_formal_event_chain_ready_for_review.md`。

报告必须列出实际修改、未运行验证和剩余 gap。最终状态只能是 `ready_for_review`。

## 唯一执行清单

- [x] 当前三项业务失败与两条真实来源已按当前源码重新核对，没有沿用失效假设。
- [x] `ByCompareTarget` 正确区分合法空、单实体、多实体和解析失败。
- [x] `ParamEntity` 与预解析目标组在正式创建事件中保持同一实体身份。
- [x] 正式忆灵出生时，监听器看到已一致提交的新单位和召唤关系。
- [x] Equip33 父监听通过真实创建事件安装子状态，两个动态值 family 通过正式攻击链执行。
- [x] Equip36 在无忆灵时不阻断，在真实忆灵出生后安装监听并通过正式死亡回响链执行。
- [x] 错误归属、损坏关系、重复事件和监听失败均 fail-closed 且无半提交状态。
- [x] mutation、settlement、来源反查、snapshot 和 replay 证据闭合。
- [x] VG-R1 三项临时业务失败豁免已完整退役，没有留下替代豁免。
- [x] R2 聚焦的两条真实来源业务失败为零，完整已发布光锥目录装备侧启动失败为零。
- [x] 未恢复完整 lowering、重复构建、大型验证框架或装备专用 runtime。
- [x] 直接回归、资源审计、快速检查和 `ready_for_review` 报告完整。

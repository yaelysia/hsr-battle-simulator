# P1 第一阶段返工修正总体性执行计划

本文档是对第一阶段 P1-3 / P1-4 / P1-5 / P1-8 / P1-9 验收口径放宽问题的返工计划。目标是让一个没有前序对话上下文的新执行线程，可以根据本文件修正第一阶段中“边界验证通过但机制未完整可用”的问题。

一句话目标：

```text
把第一阶段从“底座能跑、blocked 边界正确”修正为“关键战斗机制按游戏语义可执行、可审计、可 replay”，并重新定义哪些项真的可以验收。
```

## 0. 背景和问题

本项目正在构建《崩坏：星穹铁道》战斗模拟器 v8 clean core。最终目标是给外部推演器当战斗结算内核：外部枚举动作、目标和随机分支，core 判断合法性、执行规则、输出完整 transition、settlement、replay 和 source audit。

第一阶段原本应该形成最小可用战斗纵切。但此前验收存在一个严重问题：

```text
把“blocked/no mutation 边界正确”误当成“机制已经完成”。
```

这导致以下模块被过早验收：

- 状态系统：有 stack / refresh / duration / chance / dispel / control 的局部代码，但没有证明所有状态默认生命周期规则正确。
- 召唤物 / servant / 忆灵：有 summoned monster 正例和 servant blocked 边界，但没有完成 servant/忆灵作为召唤物进入战斗的通用路径。
- 队列 / 行动窗口：有 mandatory drain、ultimate/extra-turn 等局部正例，但 follow-up、counter、assistant 等端到端 family 仍未完整验收。
- BattleSetup：能生成 summoned monster，但 servant initial setup 被当成 source gap blocked 验收，这不能代表开局召唤物完整可用。
- P1-9 聚合：`ok=true` 只能说明聚合脚本自身通过，不能说明第一阶段机制完整。

后续修正必须遵守：

- 机制目标是 executable 时，必须有真实来源正例。
- 只有明确是 discovery / boundary 子项时，blocked/no mutation 才能算通过。
- 不能为了验收造 synthetic 正例。
- 不能因为数据库字段投影不完整就直接叫 source gap。
- 不能把路径名、角色名、怪物名、固定 id、文本猜测写进 runtime。

## 1. 本次返工范围

本计划只修正第一阶段已经暴露的关键验收缺口，不做全量角色、光锥、遗器、环境、完整关卡机制。

返工项：

1. `P1-R0` 验收口径和文档矩阵修正。
2. `P1-R1` 状态生命周期总返工。
3. `P1-R2` 控制抵抗和状态概率分支修正。
4. `P1-R3` 召唤物 / servant / 忆灵统一系统返工。
5. `P1-R4` BattleSetup 召唤物开局生成返工。
6. `P1-R5` 队列 / 行动窗口端到端正例补强。
7. `P1-R6` P1 聚合验收重建。

不再把 `DispelStatus(Order=Random)` 当作当前 blocker。当前游戏和数据库都更像是按最后添加顺序驱散；随机驱散若数据库没有真实来源，应记录为“未出现机制”，而不是阻塞第一阶段完成。

## 2. 通用验收口径

每个子项必须按下面四类标记：

- `executable`：有真实来源，runtime 可执行，mutation / settlement / replay / source audit 都通过。
- `boundary_only`：该子项目标就是证明缺来源或非法输入时 blocked/state unchanged；不能冒充机制完成。
- `source_absent_not_required`：当前游戏/数据库未出现该机制，不作为当前阶段 blocker，例如 random dispel。
- `implementation_missing`：机制应当存在，当前代码没有正确实现或验证不足。

阶段完成口径也拆成两层：

- `P1 repair substrate accepted`：关键底座和边界正确，但仍有非核心扩展项未做。
- `P1 minimum battle slice accepted`：本计划列出的状态、召唤物、队列、BattleSetup 正例全部通过，才算第一阶段最小可用战斗纵切重新验收。

禁止继续使用下面口径：

```text
脚本 ok=true => 阶段完成
blocked/no mutation => 机制完成
字段存在 => 语义完成
source trace 存在 => 来源正确
```

## 3. P1-R0 验收口径和文档矩阵修正

### 目标

先修正项目管理层，避免执行线程继续根据旧结论推进。

### 要做

- 更新 `FIRST_PHASE_TASK_CHECKLIST.md`：
  - 把 P1-3、P1-4、P1-5、P1-8 从“已完整验收”改成“底座通过，机制返工中”或重新拆分子项。
  - 明确 servant/忆灵、状态默认生命周期、队列 family 正例是未完成项。
- 更新 P1-9 聚合报告：
  - 不再把 random dispel 当第一阶段 blocker。
  - 不再把 servant blocked 边界写成 servant 机制完成。
  - 输出 `boundary_only` 和 `executable` 的区别。
- 更新 `CODEX_HANDOFF.md`：
  - 明确当前第一阶段不是完整可用，只是部分底座可用。
  - 新线程优先处理本返工计划。
- 更新 `AGENTS.md`：
  - 保留“blocked 边界不能冒充机制完成”的规则。

### 验收结果

- 文档中不能再出现“servant source gap 所以 P1-8 完成”这类表述。
- P1-9 summary 必须能列出：
  - 真正 executable 的机制。
  - boundary-only 的 blocked 验证。
  - implementation_missing 的返工项。
  - source_absent_not_required 的机制。

### 验证范围

必跑：

```bash
git diff --check
```

不需要跑完整 TBGD lowering，除非同时修改验证脚本。

## 4. P1-R1 状态生命周期总返工

### 目标

建立统一状态生命周期规则，使 buff、debuff、DoT、控制、特殊状态默认走同一套生命周期。

默认规则：

- 没有特殊说明时，重复施加同一状态默认刷新持续时间。
- 没有特殊说明时，状态默认不能叠层。
- 能叠层的状态必须来自机制说明或数据投影。
- 叠层状态重复施加时，具体是“加层并刷新”“只加层不刷新”“只刷新不加层”“到上限后刷新”要由来源决定。
- 持续时间 tick、到 0 移除、DoT tick、控制状态过期都走同一生命周期框架。

### 为什么要返工

当前 `StatusSystem` 已有 stack、refresh、duration、tick、chance、dispel 的局部能力，但旧验收没有证明“全状态默认规则”正确。此前只盯着少量 AddModifier 字段判断 source gap，漏掉状态定义和文本解释层。

### 要做

1. 做状态来源审计矩阵。
   - 扫描状态定义、modifier 定义、AddModifier、状态配置、回调配置。
   - 不只看 task 上的叠层字段，也要看状态/ modifier 自身定义。
   - 输出每种状态的默认生命周期归类：单层刷新、可叠层刷新、可叠层不刷新、永久、特殊来源、未知。

2. 建立统一状态生命周期 policy。
   - 建议新增或扩展状态 policy IR / metadata。
   - runtime 只读 Canonical IR / 数据卡 IR，不直接读 raw 或 TextMap。
   - 文本解释只能发生在数据卡构建层，不能在 runtime 解析文本。

3. 实现默认重复施加刷新持续时间。
   - 如果状态有 duration，重复施加同状态默认刷新到新 duration。
   - 如果状态无 duration，按永久或来源指定处理。
   - 如果状态被明确标为可共存或多实例，不能被默认刷新覆盖。

4. 实现默认不可叠层。
   - 未声明叠层的状态再次施加不增加 stacks。
   - 已存在同源或同状态实例时刷新 duration。
   - 不同来源如何处理必须有 policy；没有 policy 时不能静默共存。

5. 实现可叠层状态的通用路径。
   - 叠层增加、上限、到上限后的行为要记录在 settlement。
   - 层数影响公式时，公式读取当前 status detail，而不是初始值。

6. 实现 duration tick 和过期移除统一路径。
   - turn start、turn end、action after 等 tick owner 要清楚。
   - 到 0 后 status id 和 status detail 都移除。
   - 过期事件、callback、settlement 顺序稳定。

7. 实现 DoT tick 与生命周期结合。
   - DoT tick 不应该是状态系统外的孤岛。
   - DoT 伤害来源要能追到状态实例、施加者、状态定义和 tick 事件。

8. 实现确定性驱散。
   - 当前应优先支持按最后添加顺序驱散。
   - 可驱散/不可驱散、buff/debuff/control 分类必须来自来源。
   - 被跳过的状态要记录 skipped reason。

### 验收结果

必须有真实来源正例：

- 普通非叠层有持续时间状态：重复施加刷新持续时间，不增加层数。
- 普通非叠层无持续时间状态：重复施加不重复创建状态实例。
- 可叠层状态：重复施加增加层数，不超过上限。
- 可叠层且刷新持续时间状态：如果真实来源存在，层数和持续时间同次更新。
- duration tick：剩余回合减少，到 0 移除。
- DoT tick：状态触发伤害，来源可追溯。
- 确定性驱散：按最后添加顺序或来源指定顺序移除可驱散状态。

必须有负例：

- 未声明叠层的状态不能叠层。
- 不可驱散状态不能被 DispelStatus 驱散。
- 缺 target / 缺状态定义 / unsupported lifecycle policy 时 blocked/state unchanged。
- 不能用 synthetic 正例证明 stack+duration refresh。

### 验证范围

必跑：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_4_status_system --output-dir /tmp/hsr_v8_p1_4_status_repair
git diff --check
```

直接回归：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_7_rng_branch_system --output-dir /tmp/hsr_v8_p1_7_after_status_repair
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_after_status_repair
```

条件触发：

- 改 DoT 伤害时跑 damage / DoT 相关验证。
- 改 target 时跑 P1-6。
- 改 queue/control gating 时跑 P1-5。

禁止默认跑高 IO 全量脚本。

## 5. P1-R2 控制抵抗和状态概率分支修正

### 目标

把效果抵抗和控制抵抗分开。效果抵抗用于大多数概率状态；控制抵抗只用于控制类状态。

### 要做

1. 先在数据库中搜索控制抵抗来源。
   - 查角色/怪物属性、状态配置、公式配置、全局常量。
   - 如果数据库找不到完整公式，再查可靠外部资料。
   - 外部资料只能用于数据卡解释或公式确认，不能让 runtime 直接依赖网页文本。

2. 定义概率状态的结算链。
   - 基础概率。
   - 效果命中。
   - 效果抵抗。
   - 免疫。
   - RNG event。

3. 定义控制状态的额外结算链。
   - 控制分类。
   - 控制抵抗。
   - 控制免疫。
   - RNG event。

4. settlement 区分失败原因。
   - 概率没中。
   - 被效果抵抗。
   - 被控制抵抗。
   - 被免疫。

### 验收结果

- 普通概率状态失败和 resisted 是不同 record。
- 控制状态 resisted 使用控制抵抗，不使用普通效果抵抗替代。
- 所有 RNG 都通过 `RNGEvent` 和 explicit / deterministic ledger replay。
- 缺公式来源时 blocked 或 process-only，不产生状态 mutation。

### 验证范围

必跑：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_4_status_system --output-dir /tmp/hsr_v8_p1_4_control_resist_repair
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_7_rng_branch_system --output-dir /tmp/hsr_v8_p1_7_control_resist_repair
git diff --check
```

如果为了公式确认查外部资料，报告中必须写明资料只用于公式确认，不是 runtime 来源。

## 6. P1-R3 召唤物 / servant / 忆灵统一系统返工

### 目标

把 servant、忆灵、召唤怪、战斗召唤单位纳入统一召唤物系统。忆灵属于召唤物大类，但它有自己的文本和召唤者文本，必须在数据卡构建层解释成结构化机制。

### 为什么要返工

当前 P1-3 / P1-8 验证只证明了：

- 至少一种 summoned monster 能生成。
- servant 初始生成被 blocked 时不会伪造单位。

这不能代表 servant/忆灵机制完成。

### 要做

1. 建立召唤物分类。
   - 普通召唤怪。
   - servant / 忆灵。
   - battle unit summon。
   - adventure / visual / scene-only unit。
   - assistant 只作为协助能力或队列 family，不要和实体召唤混淆。

2. 结合数据库和数据网站做分类对照。
   - 数据库是规则主来源。
   - 数据网站只用于确认“这个单位是否实际战斗召唤物”和文本解释方向。
   - 分类结果要进入数据卡 IR 或 Canonical IR，runtime 不读网站。

3. 构建 servant / 忆灵数据卡。
   - 读取召唤物自身文本/能力。
   - 读取召唤者文本/能力。
   - 形成 owner、stat、action、timeline、target、lifecycle 的结构化槽位。

4. 扩展 SummonSystem runtime。
   - 统一 registry：owner -> summon list，summon -> owner，last summon，active summons。
   - UnitState flags 明确 summon kind、owner、summoner、source trace。
   - spawn/remove 都走 UnitSpawn / UnitRemove mutation。

5. 接目标系统。
   - owner/summoner fetch。
   - 选中所有 servant / 当前 owner 的 servant。
   - 排除 servant。
   - servant 或 summoner。
   - 缺 registry / 缺 owner 时 blocked。

6. 接行动和时间轴。
   - 有 action source 才能作为可行动单位。
   - 有 timeline source 才能进入行动轴。
   - 不能给召唤物默认速度、默认 action set、默认 action value。

### 验收结果

必须有真实来源正例：

- 至少一个 servant/忆灵能从召唤者和自身数据卡生成战斗单位或 owner-bound component。
- 生成后 registry、owner 关系、source trace 完整。
- servant/忆灵目标表达式能定位自身、主人、同类召唤物。
- 有行动来源时可暴露行动候选；无行动来源时明确 blocked。
- 召唤物移除后不可行动、不可被普通目标选中，registry 更新。

必须有负例：

- 路径名含 `Servant` 不能直接生成单位。
- `SummonUnitData` 不能被当成自动战斗 spawn trigger。
- adventure / visual unit 不能进入战斗 runtime。
- 缺 owner、缺 stat、缺 action、缺 timeline 时 blocked/state unchanged。

### 验证范围

必跑：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_3_summon_assistant_servant --output-dir /tmp/hsr_v8_p1_3_summon_repair
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_8_battle_setup --output-dir /tmp/hsr_v8_p1_8_summon_repair
git diff --check
```

直接回归：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_6_target_system --output-dir /tmp/hsr_v8_p1_6_after_summon_repair
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_after_summon_repair
```

条件触发：

- 改 timeline/action availability 时跑 P1-5。
- 改状态 owner-bound 清理时跑 P1-4。

## 7. P1-R4 BattleSetup 召唤物开局生成返工

### 目标

BattleSetup 能正确生成开局存在的召唤物/servant/忆灵，而不是把 servant initial setup 永久当 blocked。

### 要做

1. 扩展 scenario schema。
   - `initial_summons` 支持 summon kind、owner、source ref、可选 timeline override。
   - servant/忆灵使用数据卡或 Canonical IR source，不用固定角色名。

2. IdentityResolver 校验。
   - owner 必须存在。
   - summon definition 必须存在且 executable。
   - adventure/visual summon 禁止进入 battle setup。

3. ScenarioStateBuilder 生成。
   - 通过 SummonSystem spawn。
   - 写 UnitSpawn mutation。
   - 写 summon_runtime registry。
   - 写 setup records 和 source trace。

4. timeline 初始化。
   - 有 timeline source 时进入行动轴。
   - 无 timeline source 时作为非行动 component 或 blocked。

### 验收结果

- 开局生成真实 servant/忆灵正例。
- 开局生成普通 summoned monster 正例仍通过。
- 无 owner / 无 definition / 非战斗 summon / 缺 timeline source 都 blocked，不产生伪单位。
- setup mutation replay 通过。
- source audit 能追到 summon definition、owner data card、scenario setup。

### 验证范围

必跑：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_8_battle_setup --output-dir /tmp/hsr_v8_p1_8_battle_setup_repair
git diff --check
```

直接回归：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_3_summon_assistant_servant --output-dir /tmp/hsr_v8_p1_3_after_battle_setup_repair
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_after_battle_setup_repair
```

## 8. P1-R5 队列 / 行动窗口端到端正例补强

### 目标

补齐真实 route 中的 queue/window family 正例，不能只靠 direct contract case。

### 为什么要返工

当前 P1-5 验证覆盖了不少队列底座，但第一阶段要作为推演器结算内核，必须证明常见行动窗口端到端可执行：

- 追击。
- 反击。
- 额外行动。
- 终结技插队 / selectable window。
- assistant family 如果有真实来源。
- actor/target 生命周期变化后的 pending queue 处理。

### 要做

1. 建立 queue family 来源矩阵。
   - 每个 family 列 raw source、IR intent、resolution、window、runtime drain 状态。
   - 有来源的必须做正例。
   - 无来源的才 boundary_only。

2. 补 follow-up 端到端正例。
   - 触发来源真实。
   - enqueue、drain、child action、settlement、replay、source audit 完整。

3. 补 counter 端到端正例。
   - 受击事件 payload 明确 attacker/defender/target。
   - 反击 target 合法。
   - actor 被控制/死亡时不执行。

4. 补 extra turn 端到端正例。
   - 额外行动不等于终结技插队，不等于追击。
   - pending natural turn end 顺序稳定。

5. 补 ultimate selectable window 正例。
   - energy ready 时暴露可选窗口。
   - 无外部 command 不自动释放。
   - command 匹配才执行，不匹配 blocked。

6. 补 assistant family。
   - 如果当前有真实来源，做 executable 正例。
   - 如果没有，明确 boundary_only，不能因为 P1-3 有 assistant 分类就冒充 queue 正例。

7. 补 pending queue 生命周期负例。
   - actor removed / defeated。
   - target removed / defeated。
   - 缺 retarget source 时 blocked。

### 验收结果

- 每个当前有真实来源的 queue family 都有 route-level 正例。
- queue enqueue/dequeue/cancel/drain 都通过 mutation 或 process-only record 表达。
- queue child action 的 source trace 能追到 parent event / queue intent / IR source。
- replay/source audit 通过。
- 不存在“unknown family 被静默忽略”。

### 验证范围

必跑：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_5_queue_window_system --output-dir /tmp/hsr_v8_p1_5_queue_repair
git diff --check
```

直接回归：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_4_status_system --output-dir /tmp/hsr_v8_p1_4_after_queue_repair
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_after_queue_repair
```

条件触发：

- 改 target / random target 时跑 P1-6 / P1-7。
- 改 summon actor 行动时跑 P1-3 / P1-8。

## 9. P1-R6 P1 聚合验收重建

### 目标

重建 P1-9 聚合验收，让它真实反映第一阶段是否能作为“最小可用战斗纵切”。

### 要做

1. 更新 system matrix。
   - 每项区分 executable、boundary_only、source_absent_not_required、implementation_missing。
   - 不再只用 source_gap_blocked。

2. 聚合 scenario 覆盖真实机制。
   - 状态重复施加刷新。
   - 状态 tick / expire。
   - 确定性驱散。
   - 至少一个 summon/servant/忆灵开局或行动中生成。
   - 至少一个 queue/window route-level drain。
   - target、RNG、source audit、replay 全部闭环。

3. 报告 P1 最小可用状态。
   - 不能再只说 `ok=true`。
   - 必须说明当前距离完整模拟器还缺哪些模块。

### 验收结果

P1-9 只有在下面条件满足时才能写 `phase1_minimum_battle_slice=true`：

- P1-R1 到 P1-R5 的必做正例全部通过。
- 没有 implementation_missing。
- boundary_only 项都明确不是当前阶段必做机制。
- replay/source audit/settlement traceability 通过。
- 验证输出资源受控。

### 验证范围

必跑：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_repair
git diff --check
```

直接回归：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_3_summon_assistant_servant --output-dir /tmp/hsr_v8_p1_3_repair_final
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_4_status_system --output-dir /tmp/hsr_v8_p1_4_repair_final
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_5_queue_window_system --output-dir /tmp/hsr_v8_p1_5_repair_final
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_8_battle_setup --output-dir /tmp/hsr_v8_p1_8_repair_final
```

全量验证只在最终阶段验收或结构性大改后运行，且必须串行。

## 10. 建议执行顺序

推荐顺序：

1. `P1-R0` 先修验收口径和文档。
2. `P1-R1` 状态生命周期总返工。
3. `P1-R2` 控制抵抗和概率分支。
4. `P1-R3` 召唤物 / servant / 忆灵统一系统。
5. `P1-R4` BattleSetup 开局召唤物生成。
6. `P1-R5` 队列 / 行动窗口端到端正例。
7. `P1-R6` P1 聚合重验收。

原因：

- 状态系统是大量角色、怪物、召唤物和队列触发的基础。
- 控制抵抗依赖状态分类和概率分支。
- 召唤物系统先确定身份、owner、target 和 action/timeline，BattleSetup 才能正确生成。
- 队列端到端需要状态 callback、目标、召唤物和生命周期共同稳定后再补。
- P1-9 必须最后重建，不能再先聚合后补机制。

## 11. 禁止事项

- 禁止把 blocked 边界当成机制完成。
- 禁止因为路径名含 servant / summon 就创建单位。
- 禁止用固定角色名、怪物名、技能 ID、召唤物 ID 做主路径。
- 禁止 runtime 读取 raw TBGD、TextMap、数据网站或旧 v7。
- 禁止用数据网站替代 TBGD / 数据卡 IR；数据网站只能辅助分类核对。
- 禁止把随机驱散当当前阶段 blocker，除非数据库出现真实 Random 驱散来源。
- 禁止把控制抵抗和效果抵抗混成同一个公式。
- 禁止默认给召唤物速度、行动值、行动列表或死亡清理策略。
- 禁止无来源 retarget、默认随机目标、默认 owner。
- 禁止新增高 IO 验证脚本默认写完整 Canonical IR 或完整 coverage artifact。

## 12. 最终交付物

每个返工项完成后都应交付：

- 更新后的代码。
- 对应 P1 验证脚本。
- 阶段报告，写清当前做到哪里、还有什么没做。
- `FIRST_PHASE_TASK_CHECKLIST.md` 状态更新。
- 必要时更新 `CODEX_HANDOFF.md` 和 `AGENTS.md`。
- 验证命令和输出目录。
- 成功后 git 检查点提交。

第一阶段重新验收成功时，应能明确回答：

```text
当前 v8 是否已经能跑一个包含状态、召唤物、队列窗口、目标、RNG、波次、setup 的最小可用战斗纵切？
哪些机制已经 executable？
哪些只是 boundary_only？
哪些不是当前游戏/数据库出现的机制？
哪些仍是 implementation_missing？
```

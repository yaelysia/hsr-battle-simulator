# P8-R2 两次暂停后的最终差量执行卡

## 执行配置

- 归属阶段：P8-R2，不新增阶段或总 checklist 项。
- 基线检查点：`419e476`。
- 当前状态：第二次验证暂停后的继续施工。
- 推荐模型：5.6 Sol。
- 推荐推理等级：`max`。
- 执行模式：普通聚焦模式。
- 最终状态：只能提交 `ready_for_review`；不得勾 checklist、提交 Git或进入后续阶段。

本文件是 P8-R2 当前唯一有效的差量卡。它覆盖原 P8-R2 卡中与验证范围、
证据组织和资源预算冲突的内容。执行线程不得继续运行九族组合验证，也不得再为旧
S8 聚合器增加缓存、顺序探针或验证器自证逻辑。

## 两次暂停后的当前事实

### 首次未过滤运行

- 原两个动态值任务和死亡回响在当时专用路径中变绿。
- 额外出现六个事件族失败。
- 代码审查发现旧验证跨状态复用事件、依赖合成状态生产者，并手工拼装动作和伤害。
- 因此首次变绿和变红都不能直接作为正式 gameplay 结论。

### 第二次九族过滤运行

- 两个动态值任务已经通过正式决策、动作命令和 `CombatExecutor.execute` 执行。
- 一次动作产生 21 个 mutation，原子提交、来源审计和 replay 均成功。
- 三个外部内容依赖已经诚实分类，没有继续使用合成状态生产者冒充执行。
- 仍失败：
  - `OnDeathrattle:s8`
  - `OnListenAvatarBaseTypeChange:s8`
  - `OnListenCharacterDie:s8`
  - `OnTriggerDeath:s8`
- 峰值内存约 1.14 GiB，耗时约 8 分 6 秒，超过本阶段 1 GiB 暂停线。
- 磁盘产物只有约 170 KB，内存峰值不是写大 JSON 造成的。

### 当前验证入口并不是真正的过滤构建

现有九族命令虽然只输出选中 family，仍然会：

- 构建整套 S8 focused bundle。
- 构建完整 owned-combatant admission projection。
- 构建 formal、lifecycle、custom、heal、weakness 等全部公共证据。
- 同时保留基础 IR、扩展 IR、多个 RuleBook 和场景证据。
- 再执行反向顺序探针和失败隔离探针。

摘要还保留旧的 3.5 GiB 治理谓词，而本卡硬预算已经是 1 GiB。由此可见当前入口是
“结果过滤”，不是“计算过滤”。继续优化它或重复运行不会增加本阶段证明力。

## 四项失败的最新裁决

### 1. 三项死亡监听共享一个生产事件问题

一次正式致死动作已经成功：

- 目标进入 defeated 状态。
- mutation、settlement、来源审计和 replay 一致。
- 交易中却出现两个针对同一目标的 `unit.defeated` 事件。

代码事实是：

- 伤害系统产生的死亡事件没有稳定 event identity。
- dispatcher 为该事件补齐类型化参数实体后，返回的是规范化事件。
- executor 最终同时收集生产者原事件和 dispatcher 返回事件。
- 两个对象 payload 不同且都没有稳定 event identity，因此现有去重无法识别为同一事件。

这不是三个独立光锥问题。应从通用事件身份和正式交易事件流上修复一次，随后共同复核：

- `OnDeathrattle`
- `OnListenCharacterDie`
- `OnTriggerDeath`

不得把验收条件从“恰好一个死亡事件”放宽为“至少一个”，也不得在验证器中事后删除
重复事件。

### 2. 基础类型监听使用了错误的生产者

失败来源 `Equip40 / 23053` 的真实回调统计的是 Elation 角色基础类型数量。当前探针却把
状态 owner 当作召唤者，尝试生成其 servant；该 owner 没有 servant 定义，因此得到
`definition_count=0`。

这条验证路径的生产者类别错误：

- `OnListenAvatarBaseTypeChange` 应由角色阵容单位的出生、移除或基础类型变化产生。
- servant 出生只有在该 servant 本身具有真实角色基础类型时才可能产生同类事件；
  不能把所有 servant spawn 当成阵容基础类型变化。

执行线程必须先核对当前正式角色卡和 scenario 是否存在可用的真实 Elation 阵容变化：

- 若存在，使用正式角色单位 mutation 和同一候选状态执行监听。
- 若当前只具备监听实现、没有战斗中阵容变化的正式内容生产者，分类为
  `external_content_e2e_deferred`。

不得伪造一个 Elation 单位，也不得继续用忆灵出生证明该事件。

### 3. 三项外部内容依赖保持 deferred

当前以下三项没有已接入内容卡提供完整真实触发条件：

- `OnCustomEvent:s8`
- `OnListenModifierAdd:s8`
- `OnListenModifierOnStack:s8`

它们可以保持 `external_content_e2e_deferred`，前提是每项继续记录：

- 真实监听来源。
- 所需真实触发条件。
- 当前缺失的角色、怪物或关卡内容归属。
- 后续应在哪类内容卡闭合。

它们不得计入 `executed`，但也不属于当前 P8-R2 的内核实现失败。

## 本轮唯一目标

### 目标一：死亡事件在正式交易中只有一个规范身份

通用事件流必须做到：

1. 每个由真实死亡生命周期 mutation 产生的死亡事件有稳定、可审计且确定性的身份。
2. dispatcher 规范化 payload 时不把同一生产事件变成第二个业务事件。
3. transaction、settlement、source audit 和 replay 看到同一个规范事件。
4. 同一伤害序列后续命中已死亡目标时不能再次产生死亡事件。
5. 两个不同单位死亡或两个不同生命周期 mutation 仍必须保留为两个事件。
6. 伪造、缺身份、缺生命周期 mutation 或状态不一致的死亡事件继续 blocked。

修复必须是通用事件契约，不得按光锥、回调名或具体装备分支。

### 目标二：基础类型事件使用正确的阵容生产链

必须移除“为基础类型监听生成 servant”的错误探针。随后按真实代码事实二选一：

- `executed`：正式角色阵容 mutation 产生事件，监听在同一候选状态中执行。
- `external_content_e2e_deferred`：内核生产和监听契约存在，但当前内容卡没有正式的
  战斗中阵容变化入口。

无论哪种结果，都必须证明：

- event target、参数实体和 mutation 单位相同。
- 事件只在单位真实具有基础类型时产生。
- 普通召唤物不会被虚构成角色基础类型。
- 缺单位、身份冲突或跨状态事件继续 fail-closed。

### 目标三：保留已经成立的正式动作改造

当前两个动态值任务已经通过正式动作入口。修复期间必须保持：

```text
DecisionSystem / ActionAvailability
-> ActionCommand
-> CombatExecutor.execute
-> 正式 task/effect
-> mutation/event
-> listener
-> atomic commit
```

不得恢复验证器手工计算伤害、手工派发窗口或直接调用子回调。生产 API 只有在真实
scenario 或 runtime 调用链消费时才能保留。

### 目标四：把 R2 验证从 S8 聚合器中真正切小

本轮不是再写一套大型验证框架。必须删除或停止使用当前 R2 路径中的：

- 九族组合入口。
- 反向顺序和失败隔离元探针。
- 与 R2 无关的 heal、weakness、catalog、完整 family partition 等公共证据。
- 跨状态事件缓存。
- 合成 gameplay producer。
- 为每个 callback 重复保存完整 transition 的结构。

family 选择必须在以下工作发生前生效：

- 来源投影。
- IR/RuleBook 组合。
- scenario 构建。
- transition 执行。
- evidence 保留。

不能先构建整套对象再过滤输出。

允许采用一个小型 R2 专用验证入口，但必须满足：

- 直接调用生产接口，不复制动作、伤害、召唤或提交逻辑。
- 从当前阻断版本迁移并删除旧 R2 验证代码，验证 Python 总量明显减少。
- 不新增注册表、缓存框架、场景 DSL 或“验证验证器”。

## 验收结果

### 生产正确性

- 两个动态值任务由一次正式忆灵动作共同证明。
- 一次正式致死动作对目标只产生一个死亡事件。
- 死亡回响、角色击杀监听和死亡触发监听均消费这个规范事件。
- 三类死亡监听各自执行真实成功分支，或根据真实 scope 明确不匹配，不能靠重复事件碰巧命中。
- 基础类型监听使用角色阵容变化，或诚实分类为外部内容依赖。
- 三项既有外部内容依赖保持结构化 deferred。
- 所有 committed mutation 可追溯，snapshot 与 replay 一致。

### 架构正确性

- 内核没有装备专用 handler 或身份分支。
- 验证器不再手工拼装正式动作、伤害和提交顺序。
- 新增或保留的 core API 至少有一个非 `tools/` 生产调用者。
- dispatcher 的严格单位身份和死亡状态检查继续保留。
- 合法空目标仍为条件假，损坏目标仍 blocked。

### 验证成本

- 完整 `TBGDLowering.build()`：0 次。
- R2 所需来源投影和 RuleBook：各最多 1 次。
- 正式动作 transition：
  - 一次普通忆灵动作。
  - 一次致死忆灵动作。
  - 基础类型事件最多一次；若 deferred 则不构造伪 transition。
- 不运行顺序、失败隔离或共享缓存元探针。
- 默认产物小于 1 MiB。
- 峰值 RSS 必须低于 1 GiB，目标低于 768 MiB。
- 墙钟超过 5 分钟即暂停，不以“尚未超内存”为由继续。

## 验证顺序

### 第一步：不读取 TBGD 的直接契约验证

使用小型真实内核对象验证：

- 死亡事件有稳定身份。
- dispatcher 规范化前后仍是同一事件。
- 同一生命周期 mutation 不会在 transaction 中出现两次。
- 两个不同生命周期 mutation 不会被错误合并。
- 伪死亡事件继续 blocked 且 state unchanged。

这一步只证明通用事件契约，不冒充光锥正例。

### 第二步：R2 单次聚焦验证

只构建 R2 实际需要的两条光锥来源、对应状态回调、一个正式 owned-combatant 动作链及
必要角色阵容来源。一次运行输出：

- 两个动态任务结果。
- 三项死亡监听结果。
- 基础类型监听的 executed 或 deferred 裁决。
- 三项既有 external deferred 记录。
- mutation、事件、来源审计和 replay 的紧凑摘要。

不得调用现有九族组合模式。

### 第三步：必要直接回归

只运行被生产修改直接触达的小型现行契约，随后运行：

```text
compileall
git diff --check
```

不得运行 P1-P8 聚合、完整 S8 task/event、`validate_v0_209` 或完整 lowering。

### 第四步：目录启动

只有前三步全部通过且规划线程代码验收无阻断后，才允许运行一次低内存 catalog
startup。目录报告必须把 external content e2e deferred 与 implementation failure
分开；不得要求 deferred 永久存在。

## 暂停条件

出现以下任一情况立即暂停：

- 需要放宽事件单位身份、死亡状态或来源校验。
- 需要伪造角色、召唤物、状态、事件或 gameplay producer。
- 正式动作无法执行，拟改回 validator-only API。
- 基础类型正例需要实现新的角色卡、怪物卡或关卡内容。
- R2 聚焦入口仍先构建完整 S8 公共证据。
- 峰值达到 1 GiB 或墙钟达到 5 分钟。
- 出现本卡范围外的新生产实现失败。

## 唯一执行清单

- [x] 死亡事件重复的通用根因已修复，没有在验证器中事后去重。
- [x] 三项死亡监听使用同一个规范死亡事件完成裁决。
- [x] 基础类型监听不再使用 servant spawn 作为错误生产者。
- [x] 基础类型监听已真实执行或结构化标记为外部内容依赖。
- [x] 两个动态值任务继续通过完整正式动作入口。
- [x] 三项既有外部内容依赖没有冒充 executed。
- [x] R2 验证构建在 family 选择后发生，旧九族组合不再作为 gate。
- [x] 验证代码相对当前阻断版本收缩，没有新增元验证框架。
- [x] 单次 R2 聚焦验证低于 1 GiB、5 分钟和 1 MiB 产物。
- [x] 必要直接回归、`compileall` 和 `git diff --check` 通过。
- [x] catalog startup 最多运行一次，完整 lowering 保持 0。
- [x] 执行线程未勾总 checklist、未提交 Git、未进入后续阶段。

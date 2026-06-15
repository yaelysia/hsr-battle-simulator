# v8 禁止事项

## 总红线

v8 不为了旧版兼容牺牲最终成品完整性。旧版本没有稳定用户，不能把兼容旧半成品当成工程目标。

禁止把“少改一点”“暂时能跑”“复用旧接口”放在内核正确性、结构干净程度和完整快照之前。

## 旧兼容红线

禁止：

- 为保持 v7 内部 Python API 兼容而污染 v8。
- 为保持旧 CLI、旧 JSON 内部结构、旧 compiled case 结构而改变 v8 内核设计。
- 把 `BattleSimulator` 当作 v8 核心对象。
- 引入或复活 `SimulatorRuntimeAdapter`。
- 引入或复活 `_legacy_effects`。
- 使用 `action_ctx` 作为 v8 主上下文。
- 用 wrapper 把旧运行时包成新内核。
- 把旧 model pack 当作 v8 规则事实来源。

允许旧 v7 仅作为参考和数值对照，不允许作为 v8 runtime 依赖。

## 数据来源红线

禁止：

- runtime 直接读取 TBGD raw schema。
- runtime 直接按 TBGD 原始字段名判断机制。
- 使用 `model_pack_v3_0` 补齐 v8 规则。
- 用观测伤害、旧模拟器输出、手工答案作为规则输入。
- 在 scenario 里写规则结果。
- 在测试里写死战斗结算作为模拟逻辑的一部分。

所有规则必须经过 Canonical IR。

## 状态与快照红线

禁止：

- 在 system handler 中原地修改 `BattleState`。
- 绕过 `Mutation` 改 HP、能量、战技点、护盾、状态、AV、队列、flags。
- 只写 settlement 不写 mutation。
- 只写日志不写 mutation。
- after snapshot 缺字段但仍标记 transition 完整。
- before/after snapshot 无法 replay 却继续通过验证。
- 把 process-only event 伪装成状态变化。
- 把状态变化藏在临时对象、缓存或 helper 副作用里。

所有状态变化必须能从 `before + mutations` 重放到 `after`。

## 机制实现红线

禁止：

- 为某个角色、敌人、遗器、关卡、路线写硬编码特判。
- 在核心系统里判断具体角色名、技能名或 case id。
- 跳过未知 opcode 后仍把机制标记为 supported。
- 把 `audit_only` 当成 executable。
- condition 失败不记录 skipped reason。
- formula 项不记录来源。
- modifier 项不记录 applied/skipped。
- 伤害族各自输出不同 settlement 结构。
- trigger window 顺序不明确时继续扩展机制。
- 队列行为不进入 snapshot。
- RNG 调用不记录事件。

## 结算红线

禁止：

- 从日志事后反推 settlement。
- 只记录最终数值，不记录计算路径。
- 只记录 applied term，不记录 skipped term。
- settlement record 无法对应 mutation，也没有 process-only 标记。
- 使用游戏观测值校正公式。
- 用常数补洞掩盖未知公式或未知状态。

## 文档红线

禁止：

- 为每个小机制新增一份长期文档。
- 写大量推荐式文档替代硬约束。
- 让文档数量膨胀到影响索引和上下文检索。
- 文档与代码事实冲突后继续保留旧说法。

v8 长期文档只保留少数高密度约束文档。普通阶段说明进入 live validation report。

## 提交红线

禁止：

- 把 `AGENTS.md` 混入 v8 检查点提交。
- 把 `__pycache__` 或 `.pyc` 混入提交。
- 在未说明的情况下引入新依赖。
- 为追求短期验证通过删除 coverage 或降低静态检查。


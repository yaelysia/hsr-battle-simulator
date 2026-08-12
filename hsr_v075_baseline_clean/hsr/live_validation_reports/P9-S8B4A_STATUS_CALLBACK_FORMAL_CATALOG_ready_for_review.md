# P9-S8B4A 状态 Callback 正式图目录验收报告

状态：`accepted`

## 结论

角色状态 callback 的完整来源结构已投影为正式任务图目录，并与普通 ability entry 通过同一
Canonical IR 目录安装。共享模板的原始来源身份与各 callback 中的图位置身份已经分离；上游属性
监听尚未准入时，其下游 callback 仍被完整保留但保持 blocked。Runtime 消费路径未在本阶段迁移。

## 五面审查

1. 来源范围：验证器独立从完整角色 snapshot 重建 2,470 条 callback 分母，生产投影同为 2,470；
   其中 2,390 条有任务 callback 各有一个 entry，80 条无任务 callback 不生成 synthetic graph。
   生产 materializer 也内建分母对账，删除任一 callback 会在目录构造边界 fail-closed。
2. 生产不变量：9,392 条任务的 callback owner、原始来源位置、图位置、root/child 账本和能力引用均
   由类型化构造边界核对。重复任务或 effect 身份、跨 callback 子节点、悬空节点、环、不可达节点、
   owner/source 不一致及无效 ability 链接均在 Canonical IR 前后边界被拒绝。
3. 正式调用者：`TBGDLowering.build()` 只安装一次 ability/status 联合目录，RuleBook 继续提供唯一
   类型化查询。通用 limit 打开时不再把截断目录伪装为完整目录。`StatusCallbackSystem` 尚未消费
   新目录，旧 runtime 行为保持不变，迁移唯一归属 S8B4B。
4. Gap 归属：状态 callback runtime 消费归 S8B4B，跨入口 active context 归 S8B5，旧拓扑字段退役
   归 S8B6，随机与命中时序归 S8C。8 条受阻属性监听分支的结构已进入目录，但其运行时属性可读性
   仍保持 blocked，没有被本阶段冒充为可执行。
5. 验证独立性：raw callback 分母由验证器独立读取，目录身份、查询和来源反查直接检查生产结果；
   TaskGraphIR/CanonicalIR 已承担完整拓扑校验，因此验证器不复制第二套树解释器。真实 action 与
   TriggerAbility 来源均动态选样，没有固定角色、文件或 ID。

## 验证结果

- 最终唯一主入口：`ok=true`，21/21 谓词通过。
- 完整分母：2,470 callbacks、9,392 tasks、2,390 entries/graphs、80 taskless callbacks。
- 共享来源 occurrence：431 组；TriggerAbility task：8；联合目录 ability entry：2。
- 来源上下文准备 1 次；完整 Canonical IR build 0 次。
- 最终墙钟 18.88 秒（外层计时 19.30 秒），峰值 RSS 614,680 KiB，低于 640 MiB 上限。
- 验证器 347 个非空行，低于 360 行硬上限；`compileall`、`git diff --check` 通过。
- 同一主入口共运行 4 次：一次聚焦 fixture 依赖错误、一次发现真实来源漏投影、一次审计文档生命周期
  错误、一次最终通过。最终 evidence 仅保留小型 summary。

## 流程反馈

首次完整分母对账发现一个被 blocked 属性监听提前跳过的真实角色战斗分支。这说明 admission 状态
只能阻止执行，不能改变结构目录分母。共享模板还证明来源 occurrence 与正式图位置是两个独立身份：
前者用于审计，后者用于 owner 范围内的唯一执行与引用解析。最后，生产类型已负责拓扑闭合时，验证器
只需独立证明完整来源进入该构造边界；复制第二套拓扑算法既增加成本，也会形成新的错误权威。

本验证器验收后冻结为 `historical_evidence`。后续 S8B4B 只运行自身 runtime 迁移入口，不重跑本目录
主验证；目录契约变化时才提取一个最小 active direct。

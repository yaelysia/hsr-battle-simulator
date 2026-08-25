# P9-S8C1 RandomConfig 任务图权重契约聚合说明

此文件不再作为单次执行入口。当前唯一执行卡是：

```text
P9-S8C1A_WEIGHTED_SELECTION_IR_CONTRACT.md
```

执行线程不得把本文件的聚合目标加入 S8C1A PR，也不得提前实施 S8C1B、S8C1C 或随机运行时。

## 聚合背景

P9-S8B 已建立正式任务图和原子执行边界，但 `RandomConfig` 尚未在任务图中保存“第几个候选使用
哪一条权重表达式”。原 S8C1 试图在一张卡中同时建立模型、迁移 materializer，并闭合角色能力、
文件内全局模板、状态回调和共享模板入口。

实时代码与一次隔离验证表明这些来源不共享同一个公开生产入口：

- 一部分来源可以从现有正式 action slice 进入任务图。
- 文件内 GlobalTemplates 和部分状态回调尚不能由该入口完整承载。
- GridFight 共享模板中的若干完整定义当前没有正式 producer。

因此“建立权重模型”“接入现有正式入口”“补齐其余公开入口”是三个可独立验收的权威边界，必须
严格顺序实施。旧观察数量只用于解释拆卡，不得成为生产逻辑或固定完成门。

## 聚合目标

S8C1 聚合完成后，完整角色控制流来源中的每条直接 `RandomConfig` 记录都必须唯一归为：

1. 已进入正式任务图位置，并形成候选 branch、`TaskList[i]` child、`OddsList[i]` 权重定义和精确来源
   的一对一类型化契约；或
2. 当前确实没有正式 producer，保留精确来源、引用闭包和唯一后续依赖。

其中“契约已物化”只表示任务图保存了加权候选事实。随机求值、RNG 请求、选中 child、mutation、
event、settlement 和 replay 均不属于 S8C1。

## 严格顺序

| 子阶段 | 唯一主要权威 | 完成边界 |
|---|---|---|
| P9-S8C1A | 加权 choice/selection 的类型、身份、来源关系、不可变性和 codec | 不接任务图节点，不读取 TBGD，不改变 runtime |
| P9-S8C1B | 现有正式 action entry 的 materializer 接线 | 只证明该公开入口实际承载的来源，不宣称完整目录闭合 |
| P9-S8C1C | GlobalTemplates、状态回调和共享模板的公开 entry 覆盖及完整分母账本 | 所有 gameplay 来源均有正式绑定或精确 no-producer 归属 |

S8C1B 只能在 S8C1A 验收并合并后制定最终执行卡；S8C1C 只能根据 S8C1B 的真实剩余集合制定。
不得现在预写固定 ID、固定角色或私有 lowering 路径。

## 聚合红线

- 不从旧状态回调解释器、私有 lowering 或手工 `CanonicalIR` 拼装恢复第二套权威。
- 不按角色名、固定 ID、固定文件名或旧观察数量选择正式来源。
- 不把没有 producer 的完整定义预先标成 executable entry。
- 不因上游 entry 尚未接线就让真实 child 从来源分母消失。
- 不将相同数值的不同 `OddsList[i]` 合并为同一字段身份。
- 不要求相对权重合计为 1，不在 lowering 时归一化或提前求值动态权重。
- 不在 S8C1 修改 runtime、RNG、transaction、settlement 或 replay。

## 聚合完成标准

只有 S8C1A、S8C1B、S8C1C 均独立验收后，才允许勾选 P9 总计划中的 S8C1：

- 完整来源分母由实时类型化投影独立重建，直接记录与祖先上下文分开。
- 每个正式 RandomConfig 图位置恰有一个严格加权选择契约。
- 候选、branch、child、weight 和精确来源按 ordinal 双向闭合。
- 固定与动态表达式均保留原始结构，相等表达式的不同位置身份独立。
- 无孤儿正式绑定、无未归属 gameplay 来源、无伪造 producer。
- 所有节点仍诚实保持后续随机执行 deferred，runtime 行为未变化。
- 聚合验证使用公开生产入口，资源在届时执行卡预算内，不恢复历史重验证。

## 聚合状态

- [ ] P9-S8C1A 加权选择 IR 契约完成验收。
- [ ] P9-S8C1B 正式 action entry materializer 接线完成验收。
- [ ] P9-S8C1C 剩余公开入口与完整来源分母闭合完成验收。
- [ ] P9-S8C1 RandomConfig 任务图权重契约聚合完成验收。

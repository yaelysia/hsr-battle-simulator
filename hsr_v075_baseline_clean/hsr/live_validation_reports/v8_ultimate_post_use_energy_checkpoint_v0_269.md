# v8 v0_269：终结技释放后能量回正

## 做了什么

- 修正手动终结技队列执行后的能量结算。
- 以前执行成功后直接把能量设为 0；现在改为保留该终结技动作数据里的 `SPBase` 回能。
- 本地 TBGD `AvatarSkillConfig` 里大多数终结技 `SPBase=5`，但也存在特殊值或缺失项，所以 runtime 不硬写 5。
- 资源 mutation 仍由 `ResourceSystem` 产生，并带 action、queue、resource rule、post-use energy source metadata。

## 没做什么

- 没把一魂、六魂塞成希儿特判。
- 没改变终结技入队、dequeue、child action 执行链路。
- 没把数据网站或技能文本作为 runtime 规则输入。

## 语义边界

- 终结技释放前仍要求满足满能 preflight。
- 终结技 action 执行成功后，最终能量来自 `ActionDefinitionIR.sp_base`。
- 如果某个终结技没有可执行 action definition 或 `sp_base` 不可用，不能靠固定数值补。

## 验证

新增 `validate_v0_269`：

- 结构化选择一个真实 executable avatar 终结技。
- 验证执行后能量等于该 action 的 `sp_base`。
- 验证 resource mutation、settlement、source audit 均通过。
- 输出本地 Canonical IR 中终结技 `sp_base` 分布，证明不是硬编码固定 5。

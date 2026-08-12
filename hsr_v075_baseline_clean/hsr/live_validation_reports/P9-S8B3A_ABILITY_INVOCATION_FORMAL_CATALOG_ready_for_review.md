# P9-S8B3A 能力入口拓扑与正式图目录验收报告

## 结论

状态：`accepted`。角色动作根、嵌套 phase、queue standalone 根和未绑定定义已经由 compiler
类型化区分；TriggerAbility 具有唯一目标；正式 ability 目录一次构建、一次来源账本归并，并由
Canonical IR 完整性门 fail-closed 安装。本阶段未改变 runtime 行为，可以进入 P9-S8B3B。

## 生产结果

- `AbilityPhaseIR` 现在区分动作根、嵌套调用、独立队列根、未绑定定义、无任务定义和外部旧域。
- 角色 standalone 定义初始保持未绑定；lowering 只从可执行 queue resolution 和正式动作根出发，
  沿类型化能力调用边计算可达闭包。目录存在不再等同于拥有执行入口。
- TriggerAbility 优先关联同一 action binding 内的唯一 phase，否则关联唯一 standalone graph；
  两种目标互斥，缺失或歧义保持 blocked。
- 聚焦 action slice 与完整 build 使用同一 TriggerAbility 链接规则，不再出现“完整 build 能关联、
  聚焦生产入口不能关联”的双口径。
- 批量 materializer 只准备一次来源账本及全部索引；任一正式 entry 无法物化时立即拒绝整个目录。
- Canonical IR 独立复核正式 phase/callback 分母、entry/graph、来源、拓扑和定义引用，截断目录或
  blocked entry 无法安装。

## 验收证据

唯一主入口：

```text
python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8b3a_ability_invocation_formal_catalog
```

最终结果：

- `ok=true`
- 真实动作根、嵌套 phase、queue standalone 根各 1 个，共 3 个正式 entry/graph
- 同一 queue 来源文件中 14 个无生产者定义保持 `unbound_definition`，正式 entry 为 0
- 完整 S8A 来源责任账本 10,113 条，只合并 1 次
- 控制流来源扫描 1 次，formal catalog 构建 1 次，完整 Canonical build 0 次
- 墙钟 12.215 秒，峰值 RSS 413,580 KiB
- evidence 1,428 bytes，验证器 363 非空行，低于 420 行硬上限
- import smoke、`compileall`、`git diff --check` 均通过

负例确认：非法调用角色、空的未绑定定义、双能力目标、悬空嵌套 phase、blocked 正式 entry 和
截断 formal catalog 均在生产构造/物化边界被拒绝。

## 五面审查

- 来源范围：动作入口由已验收的角色来源图独立核对；queue 入口回读真实 raw 任务路径和能力名。
- 生产不变量：入口身份、目标互斥、可达闭包和目录完整性均由生产边界执行，不依赖报告常量。
- 正式调用者：完整 lowering 和聚焦 action slice 均已迁移；runtime 保持不变，留给 B3B/B3C。
- gap 归属：怪物、装备和其他外部 ability 仍为 `external_legacy`；未绑定角色定义保留来源，等待
  未来真实生产者引用时重新准入，不作为当前 executable 缺口。
- 验证器：真实样例按来源结构动态选择；没有固定角色、能力或 ID，没有空集 `all()` 假阳性，
  业务 `ok` 与 CLI 退出码一致。

## 流程反馈

修改前 preflight 发现原卡把“完整定义目录”错误等同于“正式调用入口分母”。若按原设计继续，
会物化大量没有生产者的定义，并让无关定义中的未闭合调用阻断正式目录。流程规范已增加可复用规则：
正式执行目录必须从真实生产者根节点沿类型化调用边计算可达闭包；未被调用的完整定义保留为未绑定，
不能预先标成 executable entry。

新增验证器首次业务运行前由编译门发现一处生成式语法错误，修正后才进入主入口；因此没有把验证
装配错误计作业务运行。主入口首次业务执行通过；五面审查补充“未绑定定义不得为空”的生产不变量，
最终复跑仍通过。未运行历史阶段聚合、完整 lowering 或 runtime 回归。

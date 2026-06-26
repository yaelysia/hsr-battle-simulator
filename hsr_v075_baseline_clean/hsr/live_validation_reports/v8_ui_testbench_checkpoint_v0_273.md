# v8 v0_273 Local UI Testbench Checkpoint

## Scope

本阶段新增零新依赖本地 UI 测试台，不新增战斗机制、不改 v8 clean core 运行时规则。

新增范围：

- `simulator_v8_ui.server`：标准库 HTTP server 与静态页面。
- `simulator_v8_ui.runner`：加载 scenario，构建 RuleBook，执行 route，生成 UI 调试报告。
- `simulator_v8_ui.report`：把 transition/snapshot/settlement/source audit 整理成面板、伤害、状态、资源、队列和 blocked 视图。
- `simulator_v8_ui.static`：单页 UI，无 npm、无外部前端依赖。
- `simulator_v8_ui.cases`：本地 scenario 与 observations sidecar。

## Boundaries

- UI 只是测试编排与审计展示层，不是规则来源。
- UI 不计算伤害、不补公式、不解释技能文本、不读旧 v7 或旧 model pack。
- 观测值只保存在 `.observations.json`，不会进入 `ActionCommand.metadata` 或 runtime 输入。
- `simulator_v8_clean_core/core`、`systems`、`tbgd` 不引用 `simulator_v8_ui`。

## Current Capability

第一版 UI 已支持：

- 编辑和保存 scenario JSON。
- 编辑和保存 observations JSON sidecar。
- 默认 scheduler 模式执行 route，并保留 executor 调试模式。
- 可选 timeline 初始化。
- 展示完整 `UIRunReport`，包含：
  - initial/final snapshot。
  - 每步 command、transition、child transitions。
  - 面板摘要与面板来源拆解。
  - damage/dot/break/super-break/hp-loss 等 settlement 记录。
  - formula result、modifier ledger、numeric evaluation、source frame、source trace。
  - status/resource/timeline/queue/blocked 记录。
  - replay、settlement traceability、source audit、contract。

## Not Done

本阶段没有实现：

- 完整角色、光锥、遗器、装备装配。
- 表单化的全字段 scenario 构建器；当前主编辑面是 JSON，辅以单位/路线预览。
- 敌方 AI、波次、召唤物、assistant 或特殊模式。
- 图形化行动条动画；当前以结构化 timeline/queue 表和 raw JSON 展示。
- 游戏观测日志自动导入或差异自动定位。

## Minimum Usable Battle Slice

距离最小可用战斗纵切仍缺：

- 完整角色面板装配：晋阶、行迹、装备、光锥、遗器。
- 至少一套稳定队伍/敌人/路线配置格式与更多 UI 表单辅助。
- 敌方 AI 或可替代的敌方路线输入。
- 波次进入/结束。

## Full Replication Gaps

距离完整复刻仍缺：

- 大量角色卡人工解释与验证。
- 光锥、遗器、套装、星魂全量机制。
- 敌方 AI、召唤物、assistant、特殊模式。
- 更完整的事件监听、队列优先级和特殊回合窗口。
- 观测日志只作为对照验证，不能作为规则输入。

## Validation

计划验证命令：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_ui.validate --output-dir /tmp/hsr_v8_ui_v0_1
git diff --check
```

期望：

- compileall 通过。
- UI validation 输出 `ok=true`。
- scheduler/executor 报告都包含 panel summary、damage records、source audit、replay 和 raw transition。
- unknown target / missing action / blocked queue 不产生 mutation，并能在 blocked records 中看到。
- observations sidecar 不进入 command metadata。
- clean core 不反向引用 UI 包。

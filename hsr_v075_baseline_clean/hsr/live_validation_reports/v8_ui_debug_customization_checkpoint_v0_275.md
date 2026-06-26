# v8 UI 可读详情、自定义编辑与敌方临时跳过检查点 v0_275

## 本阶段做到哪里

- UI 报告把问题拆成三类：`blocked_records` 只表示真正阻塞；`coverage_gap_records` 表示覆盖缺口；`process_notice_records` 表示过程提示。
- 截图里类似“2 条阻塞”的误导已修正：表现类 ability task 未支持、hook 未接通、韧性动态 hash 未绑定等不再混入真正阻塞。
- scheduler 模式增加 UI 临时敌方跳过：遇到 `enemy_ai_missing` 时只在 UI runner 内临时推进敌方回合结束，并记录 `temporary_until_enemy_ai=true`、`todo=enemy_ai`。
- 详情抽屉默认改成中文表格、数值卡片、标签和来源卡片；原始 JSON 只保留在“高级调试”折叠区。
- 单位详情增加“查看 / 编辑”：可编辑等级、星魂、站位、生命、攻击、防御、速度、能量、韧性、常用资源、弱点、初始状态。
- `/api/catalog` 增加 `trace_nodes_by_entity`，行迹复选框来自角色卡 / Canonical IR 的 trace nodes，保存到 `panel.flags.enabled_trace_node_ids` 和 `disabled_trace_node_ids`。

## 没做什么

- 敌方跳过不是正式敌方 AI，不生成敌方动作、敌方伤害或敌方规则来源。
- 行迹编辑只接当前已有 trace node 和静态面板加成链路，不解释技能文本，不读取 TextMap。
- 自定义编辑仍只写 scenario JSON，不做装备、光锥、遗器、套装或完整晋阶装配。
- 伤害公式展示只展示当前 v8 report 已有字段，不在 UI 层补公式或补数值。

## 距离最小可用战斗纵切还缺什么

- 需要把更多真实角色卡的动作、行迹、星魂和常用机制接入可执行链路，让点选路线能覆盖常见对照场景。
- 需要补目标模式 UI 约束，例如单体、扩散、群攻、自身、我方目标、多目标选择。
- 需要把行动条/队列视图继续细化到终结技、额外回合、追击、反击、中断等窗口来源。
- 需要把面板来源拆解继续细化到晋阶、行迹、装备、光锥、遗器、套装、环境等来源层。

## 距离完整复刻还缺哪些大模块

- 完整角色面板装配：晋阶、全量行迹、装备、光锥、遗器、套装。
- 大量角色数据卡人工解释、来源审计和负例验证。
- 敌方 AI、敌方动作选择、波次系统、召唤物、assistant 和特殊战斗模式。
- 光锥、遗器、环境、关卡机制。
- OnCustomEvent、OnWaveMonster 等 hook 的真实事件源。

## 验证

- 已通过：
  - `PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui`
  - `node --check hsr_v075_baseline_clean/hsr/simulator_v8_ui/static/app.js`
  - `PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_ui.validate --output-dir /tmp/hsr_v8_ui_v0_275`
- v0_275 验证摘要：
  - `ok=true`
  - `catalog_action_slots.ok=true`
  - `catalog_trace_nodes.ok=true`
  - `enemy_ai_auto_skip.ok=true`
  - `observations_sidecar_only.ok=true`
  - `reverse_dependency.ok=true`

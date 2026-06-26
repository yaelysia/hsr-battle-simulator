# v8 monster display names checkpoint v0_279

## 本阶段完成

- 怪物卡新增 display-only 展示字段。
- 怪物卡构建层读取 `TextMapCHS` 与 `TextMapEN`，解析怪物名、怪物介绍、技能名、技能类型、技能标签和技能说明。
- `MONSTER_CARD_SPEC.md` 补充 TextMap 展示边界：
  - TextMap 只能用于 UI/审计展示。
  - runtime 禁止读取 TextMap。
  - runtime 禁止按中文名、英文名、技能名或描述文本驱动规则。
- 完整示例卡已重新导出，顶部可直接看到可读名字。

## 示例结果

示例卡：

`simulator_v8_clean_core/examples/monster_cards/simple_sequence_monster_card_v0_278.json`

当前样例：

- 中文名：`冰锋`
- 英文名：`Ice Edge`
- 技能中文名：`冰风`
- 技能英文名：`Icy Wind`
- 技能说明：`对我方全体造成少量冰属性伤害。`
- 英文技能说明：`Deals minor Ice DMG to all targets.`

这些字段全部标记为 display-only，`runtime_rule_source=false`。

## 验证结果

命令：

```bash
cd hsr_v075_baseline_clean/hsr
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_277 --output-dir /tmp/hsr_v8_monster_cards_v0_277
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_278 --output-dir /tmp/hsr_v8_monster_cards_v0_278 --example-output simulator_v8_clean_core/examples/monster_cards/simple_sequence_monster_card_v0_278.json
git diff --check
```

结果：

- `compileall` 通过。
- `validate_v0_277` 通过，`ok=true`。
- `validate_v0_278` 通过，`ok=true`。
- `git diff --check` 通过。

## 未完成

- 展示名只解决“人能看懂这是谁”的问题，不代表怪物技能执行链已接通。
- 敌方出手、目标选择、复杂 AI、普通 `MonsterSkillConfig` ability binding、关卡等级与 HardLevelGroup 仍待后续实现。

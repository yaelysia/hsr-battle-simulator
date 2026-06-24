# v8 v0_262：角色数据卡边界回正

## 做了什么

- 将 v0_261 的技能文本解析从通用 lowering 主链路拆出，放到 `tbgd/character_cards.py` 的角色数据卡构建层。
- 新增 `CharacterDataCardIR`：角色数据卡记录 avatar、profile、技能列表和技能公式槽位。
- `SkillFormulaBindingIR` 现在必须归属某个角色数据卡；direct damage 只消费 `character_data_card_skill_formula`，不再直接消费文本解析产物。
- `RuleBook` 增加角色数据卡查询，后续角色接入可以按角色卡扩展面板、行迹、光锥、遗器和机制。
- 新增 `validate_v0_262`，专门检查文本 parser 不留在 lowering 主文件、direct emission 必须来自角色数据卡公式槽位。

## 没做什么

- 没做完整角色面板。
- 没做遗器、光锥、星魂、完整行迹。
- 没把普通 DoT 百分比强行接到角色文本；仍需要后续状态实例记录 DoT 的具体技能来源。

## 当前进度

- 角色接入前置边界已回正：数据库文本解析属于角色卡制作，runtime 和伤害系统只看 Canonical IR 里的结构化角色卡/公式槽位。
- direct damage 当前可信范围：角色数据卡中有明确技能文本基础值和 ParamList 绑定的动作。
- 这比 v0_261 更接近目标架构：后续做任意角色时，不需要让内核猜文本，也不需要在伤害系统写角色特判。

## 验证结果

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_257 --output-dir /tmp/hsr_v8_regression_v0_257
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_258 --output-dir /tmp/hsr_v8_regression_v0_258
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_261 --output-dir /tmp/hsr_v8_regression_v0_261
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_262 --output-dir /tmp/hsr_v8_v0_262
```

`validate_v0_262` 结果：`ok=true`。

## 后续阻塞

- 完整角色卡还需要接入角色面板来源和可叠加的战斗输入覆盖。
- 普通 DoT 百分比需要 AddModifier / StatusInstance 保留“该状态来自哪个技能公式槽位”。
- 多段技能需要把不同文本片段和不同 ParamList 槽位更精确地绑定到 HitProfile。

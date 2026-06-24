# v8 v0_261：角色接入前置与技能公式基础值绑定

## 做了什么

- 新增技能公式绑定 IR：从 `AvatarSkillConfig.SkillDesc` 和 TextMap 文本解析“造成/受到/附加/追加等同于 #N% 攻击力/生命上限/防御力的伤害”，并绑定到 `ParamList[N-1]`。
- direct damage 不再使用“当前先默认攻击力”的占位来源；只有拿到技能文本绑定后才 executable。
- 新增 avatar profile 骨架，记录角色配置、技能列表和晋阶基础面板来源，供后续完整角色信息接入。
- RuleBook 增加 avatar profile 与 skill formula binding 查询，runtime 仍只读 Canonical IR。
- 新增 `validate_v0_261`，覆盖真实 direct 技能文本绑定、DoT 文本绑定证据、文本解析负例、source audit、settlement traceability 和 replay。

## 没做什么

- 没做完整角色面板：遗器、光锥、星魂、完整行迹仍未接入。
- 没把状态 DoT 的全局模板强行接到某个角色文本；只有当后续 AddModifier / StatusInstance 能证明 DoT 来源技能时，普通 DoT 百分比路径才可安全执行。
- 没用角色名、固定 action id、固定 hash 或观测数值补规则。

## 当前进度

- 角色接入前置层已具备：技能文本里的基础值可以作为公式事实来源进入 Canonical IR。
- direct damage 当前可信范围提升为：文本与 ParamList 能证明基础值和倍率的 action。
- 普通 DoT 的固定 `DamageValue` 路径保持可信；百分比路径已有文本绑定证据，但 runtime 仍需要状态来源链把具体技能绑定带入。

## 验证结果

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_257 --output-dir /tmp/hsr_v8_regression_v0_257
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_258 --output-dir /tmp/hsr_v8_regression_v0_258
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_261 --output-dir /tmp/hsr_v8_v0_261
```

`validate_v0_261` 结果：`ok=true`。

## 后续阻塞

- 完整角色接入还需要角色面板来源：AvatarPromotion、行迹、光锥、遗器、星魂、队伍/战斗输入叠加规则。
- DoT 百分比 runtime 接入需要状态实例记录“该 DoT 来自哪个技能文本绑定”。
- 多段/多倍率仍需要更完整的 hit profile 与技能文本片段匹配，不能继续默认只拿 `ParamList[0]`。

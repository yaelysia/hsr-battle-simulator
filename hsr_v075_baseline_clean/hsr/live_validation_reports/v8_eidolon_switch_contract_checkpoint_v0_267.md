# v8 v0_267 - 星魂开关合同与角色卡接入

## 结果

`v0_267` 把星魂从 v0_265 的占位接口推进为可配置的角色卡入口：

- 角色卡从 `RankIDList` 读取 6 个星魂槽。
- 每个星魂槽反查 `AvatarRankConfig`，保留 `RankAbility`、技能等级提升、额外效果 ID、参数和 source trace。
- 场景单位可以设置 `eidolon_level=0..6`。
- 启用规则是前缀闭包：E3 自动启用 E1-E3，E6 自动启用 E1-E6，不支持单独只开 E6。
- state flags 会记录启用的星魂等级、槽位、rank id、机制槽和来源。
- 星魂具体效果不进入核心特判；未 admission 的效果保留为角色卡机制槽位并 blocked，后续逐个接入。

## 本次修复点

- `CharacterEidolonSlotIR` 增加 `activation` 与 `semantics`，表达星魂开关和来源证据。
- 角色卡构建层读取 `AvatarRankConfig.json / AvatarRankConfigLD.json`。
- 每个星魂生成一个 `eidolon_rank_effect` 机制槽，承载后续要接入的效果。
- `RuleBook.character_eidolon_slots_for_level()` 统一展开星魂等级。
- `UnitSpec` 和场景 loader 支持 `eidolon_level`。
- `ScenarioStateBuilder` 将星魂等级展开到 runtime state flags。
- v0_265 验证更新为新星魂合同，不再要求星魂全部是 reserved blocked。

## 当前边界

- 本阶段只完成星魂开关、来源和角色卡机制槽位。
- 星魂效果本身没有硬算；例如加技能等级、RankAbility、额外效果都要后续按对应通用系统 admission 后再执行。
- 不做遗器、光锥、完整星魂效果实现、敌方 AI、波次系统。

## 验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_265 --output-dir /tmp/hsr_v8_regression_v0_265
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_266 --output-dir /tmp/hsr_v8_regression_v0_266
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_267 --output-dir /tmp/hsr_v8_v0_267
git diff --check
```

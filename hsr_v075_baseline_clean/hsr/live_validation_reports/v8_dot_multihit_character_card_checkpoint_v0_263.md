# v8 v0_263 - DoT 与多段技能公式槽位收束

## 本阶段做了什么

- 将多段直伤的 hit profile 来源从 `ParamList[0]` 回正为角色数据卡中的公式槽位。
- 普通 DoT 的百分比路径不再因缺基础值被 lowering 一刀切 blocked；tick 时从状态实例携带的角色数据卡公式槽位解析基础值。
- 状态实例新增 `formula_bindings`，用于保存施加状态时已经整理好的公式来源；runtime 不读取 TextMap 或 TBGD raw。
- 新增 `validate_v0_263`，覆盖真实 DoT 百分比 tick、真实多段 direct action、缺公式槽位负例和 source audit。

## 没做什么

- 没实现完整角色面板、遗器、光锥、星魂、行迹。
- 没把未知目标组倍率、bounce RNG、敌方 AI 或波次系统硬算出来。
- 没把 ability 文件里所有同角色 DoT 文本候选当成精确状态来源；无法证明精确施加关系时仍保持候选/验证输入，不伪装成 runtime 规则事实。

## 当前进度

- DoT 当前可信范围：`AttackType=DOT` 的百分比或动态值路径，前提是状态实例能追溯到角色数据卡公式槽位或已有动态值绑定。
- 多段技能当前可信范围：角色数据卡明确识别出的多个 direct damage 公式槽位，可生成多个 hit profile / damage emission，并走统一 DamageSystem 与 source audit。
- 仍需后续角色信息接入：角色卡需要从“公式槽位”继续扩展到完整角色机制卡、面板来源、行迹/星魂/光锥/遗器修正。

## 验证

必跑项：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_257 --output-dir /tmp/hsr_v8_regression_v0_257
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_258 --output-dir /tmp/hsr_v8_regression_v0_258
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_262 --output-dir /tmp/hsr_v8_regression_v0_262
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_263 --output-dir /tmp/hsr_v8_v0_263
git diff --check
```

当前已通过：

- `compileall`
- `validate_v0_225`
- `validate_v0_257`
- `validate_v0_258`
- `validate_v0_262`
- `validate_v0_263`
- `git diff --check`

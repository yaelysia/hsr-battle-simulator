# v8 v0_264 Target Group And Bounce Checkpoint

## 做了什么

- 角色数据卡现在会输出弹射策略，包含弹射次数、候选目标、活目标优先、全死后补完、是否优先未命中过目标、RNG 来源等结构化字段。
- AOE / blast 不再把目标组倍率当成结构 smoke。能从角色数据卡公式槽位证明的主目标、相邻目标、全体目标会生成独立 hit 和 damage record。
- bounce 不再整体 blocked。只有角色卡里存在可执行弹射策略和可执行伤害槽位时，runtime 才会展开弹射 hit。
- 弹射目标选择接入 `TargetSystem`：有活敌人时只选活敌人；所有敌人都已死亡但本次弹射段数没打完时，按同一主行动序列补完剩余 hit，不重复发击杀事件。
- 每次弹射随机选目标都会写 `RNGEvent`，同一输入和 rng state 可 replay。
- v0_219/v0_225 旧审计更新为只把“仍不可 admission 的 bounce”作为 blocked 负例，不再把已接入角色卡的 bounce 当成错误。

## 没做什么

- 没有按角色名、固定 action id、固定 hash 或文件名硬编码弹射规则。
- 没有让 runtime 读取 TextMap 或 TBGD raw。文本解析和语义提取仍只在角色数据卡构建层。
- “优先未命中过目标”的弹射策略已经有结构和执行入口，但当前主线数据里没有 admitted 样例；验证输出具体 blocker，不造假正例。
- 没有做完整角色面板、遗器、光锥、星魂、敌方 AI、波次系统。

## 当前进度

- `blast`：当前范围可信。验证样例能产生主目标和相邻目标两组 damage records。
- `aoe`：当前范围可信。验证样例能按敌方全体展开 damage records。
- `bounce`：普通随机弹射当前范围可信。验证样例能生成固定段数弹射 hit，并记录 RNG events。
- `prefer_unhit bounce`：结构已准备，执行入口已支持；当前缺 admitted 主线角色卡来源，保持 blocked。

## 验证结果

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_257 --output-dir /tmp/hsr_v8_regression_v0_257
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_263 --output-dir /tmp/hsr_v8_regression_v0_263
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_264 --output-dir /tmp/hsr_v8_v0_264
git diff --check
```

`target_group_bounce_matrix_v0_264.json` 摘要：

- executable bounce policy：60
- blocked bounce policy：160
- selected blast sample：`avatar_skill:100302` level 1
- selected aoe sample：`avatar_skill:100303` level 1
- selected bounce sample：`avatar_skill:100402` level 1
- prefer-unhit admitted sample：0，原因是当前主线角色卡没有可 admission 的明确来源


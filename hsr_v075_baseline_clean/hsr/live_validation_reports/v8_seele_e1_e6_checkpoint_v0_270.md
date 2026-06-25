# v8 v0_270 - 希儿一魂 / 六魂通用机制接入

## 范围

本阶段把加强版希儿一魂和六魂接入到通用机制链路：

- 一魂通过 `DamageModifierIR` 表达伤害前修正，不在伤害公式里写希儿特判。
- 六魂通过状态回调、动态值、标记状态和 `true_damage` 伤害族执行，不走 direct 乘区。
- runtime 只消费 Canonical IR；TBGD/增强版配置只在 lowering 和角色卡构建层使用。

## 做了什么

- 新增 `DamageModifierIR`，lower `ModifyDamageData`。
- 支持 `OnBeforeHitAll -> ByCompareHPRatio -> ModifyDamageData`：
  - 目标当前血量不高于 80% 时应用。
  - 暴击率加成进入 crit bucket。
  - 防御修正进入 defense bucket。
- 六魂链路：
  - 终结技命中后记录本次终结技伤害。
  - 终结技结束后给目标添加六魂标记。
  - 标记保存 `终结技伤害 * 30%` 的动态值。
  - 标记目标被攻击后触发来自希儿的 true damage。
  - 死亡前通过 `OnBeforeDying` 清理敌方六魂标记。
- Source audit 新增覆盖：
  - 状态回调写动态值。
  - 状态回调发出的 true damage。

## 没做什么

- 没接旧版希儿星魂；默认示例仍是加强版希儿。
- 没把六魂标记的缺 LifeStepMoment 状态硬接入持续时间 tick。当前会记录持续时间数值 3，但生命周期倒计时仍因缺明确 LifeStepMoment 保持 blocked。
- 没实现遗器、光锥、完整行迹、敌方 AI 或波次。

## 验证结果

`validate_v0_270` 覆盖：

- 希儿卡使用加强版一魂、六魂来源。
- 一魂正例：目标血量不高于 80% 时，direct ledger 出现暴击率与防御修正项。
- 一魂负例：目标血量高于阈值时，只记录 skipped，不应用修正。
- 六魂正例：终结技后挂标记，持续时间记录为 3，后续被攻击触发 true damage。
- 六魂负例：非终结技不挂标记；缺动态值不触发额外伤害；死亡前清理标记。

## 当前进度

希儿一魂和六魂在当前可证明范围内已接入通用内核。后续做其他角色星魂时，应继续把星魂机制落成角色卡/Canonical IR 槽位，再接通用系统，不能进入 runtime 特判。

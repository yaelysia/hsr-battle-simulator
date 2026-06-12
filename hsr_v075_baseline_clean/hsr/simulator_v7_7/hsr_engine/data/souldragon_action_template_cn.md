# 龙灵行动模板（数据派生 fallback）

这个文件把丹恒·腾荒龙灵 fallback 行动从运行时代码常量中抽出来，改成由 TurnBasedGameData 参数表生成的模板。

- 龙灵初始速度：165.0
- 普通行动护盾：0.115 × 丹恒攻击力 + 256.25
- 强化物理伤害：1.0 × 丹恒攻击力
- 强化同袍附加伤害：1.0 × 同袍攻击力
- 同袍固定攻击力加成 AttackConvert：0.15 × 丹恒当前攻击力，非快照

当前模板已优先从 TBGD 的 BE_InsertShield / BE_InsertAttack 能力图生成 summon_action_ir；如果图解析失败才回退到参数派生模板。
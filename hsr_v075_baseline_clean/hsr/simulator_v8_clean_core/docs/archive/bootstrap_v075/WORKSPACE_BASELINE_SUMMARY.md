# hsr_combat_workspace v0.74

本轮不是继续推进路线，而是针对 C0→C8 伤害差异做机制拆解。

## 主要结论

1. 缇宝一魂在当前 C0→C8 路线中不能直接作为默认伤害来源加入，除非确认缇宝终结技结界处于激活状态。当前截图/记录中明确存在的是【神启】和【好忙好忙的缇宝】，没有明确记录结界/终结技领域易伤状态。
2. 当前模拟器已经有缇宝 E1 的 `zone_followup_true_damage` runtime，但该触发需要 zone additional damage 先触发。
3. 本轮发现并修正：花火终结技【谜诡/Cipher】对花火天赋增伤的额外 +6%/层没有进入 live C0→C8 case。C0 观测到全队“伤害提高 12%”，等价 2 层，因此【谜诡】应额外提供 +12% 伤害加成。
4. 修正后，缇宝追击模拟总伤从 3999.60 提升到 4393.01，接近实战 4401。
5. 同一修正会让希儿战技总伤从 110585.91 提升到 115919.64，进一步高于实战 109262，说明希儿剩余误差不是“漏缇宝一魂”能解释的，而是另有 buff/debuff/敌方状态/暴击窗口问题。

## 产物

- `live_validation_reports/damage_formula_component_audit_v0_74.md`
- `live_validation_reports/damage_formula_component_audit_v0_74.json`
- `validation_outputs_v0_74/c0_to_c8_simulator_only_after_buff_audit.json`

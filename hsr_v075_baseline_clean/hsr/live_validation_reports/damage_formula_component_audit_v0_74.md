# v0.74 damage formula component audit

## Tribbie follow-up
Observed total: 4401
Simulator total after adding Sparkle Cipher extra: 4393.006
Diff: -7.994 (99.8184%)

Packets:
- blaze: 2312.108; base=942.480; crit=3.527; dmg_bonus=1.340; def=0.465116; res=1.240; taken=1.000; reduction=1.000; toughness=0.900
- titan: 2080.897; base=942.480; crit=3.527; dmg_bonus=1.340; def=0.465116; res=1.240; taken=1.000; reduction=0.900; toughness=0.900

## Seele skill
Observed total: 109262
Simulator total after adding Sparkle Cipher extra: 115919.635
Diff: 6657.635 (106.0933%)

Packets:
- seele_skill_formula_total_hit_1: 27496.851; base=4052.078; crit=True mult=4.635; dmg_bonus=2.608; def=0.465116; res=1.490; taken=1.000; reduction=0.900; toughness=0.900
- seele_skill_formula_total_hit_2: 2966.117; base=2026.039; crit=False mult=1.000; dmg_bonus=2.608; def=0.465116; res=1.490; taken=1.000; reduction=0.900; toughness=0.900
- seele_skill_formula_total_hit_3: 2966.117; base=2026.039; crit=False mult=1.000; dmg_bonus=2.608; def=0.465116; res=1.490; taken=1.000; reduction=0.900; toughness=0.900
- seele_skill_formula_total_hit_4: 82490.552; base=12156.234; crit=True mult=4.635; dmg_bonus=2.608; def=0.465116; res=1.490; taken=1.000; reduction=0.900; toughness=0.900

## Findings
- Tribbie E1 true damage is not active in the current C0-C8 route unless Tribbie Zone is active. The current observed buff list does not include a clear Zone/ultimate field status; it includes 神启 and 好忙好忙的缇宝.
- Sparkle Cipher extra +6% per active Figment/talent stack was missing. C0 observed damage-up is 12% = two stacks, so Cipher adds +12% DMG bonus. This almost fully explains Tribbie follow-up: 3999.60 -> 4393.01 vs observed 4401.
- Seele remains over after the same fix, so Seele's remaining error is a separate buff/debuff/window issue, not Tribbie E1.

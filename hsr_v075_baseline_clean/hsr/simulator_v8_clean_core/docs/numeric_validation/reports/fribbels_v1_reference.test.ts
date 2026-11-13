// @vitest-environment jsdom
import { writeFileSync } from 'node:fs'
import { test, expect } from 'vitest'
import { Metadata } from 'lib/state/metadataInitializer'
import { Sets, Stats } from 'lib/constants/constants'
import { generateFullDefaultForm } from 'lib/simulations/utils/benchmarkForm'
import { generateContext } from 'lib/optimization/context/calculateContext'
import { runStatSimulations } from 'lib/simulations/statSimulation'
import { StatSimTypes } from 'lib/simulations/statSimulationTypes'
import { testStatSpread } from 'lib/simulations/tests/simTestUtils'
import { BasicKey } from 'lib/optimization/basicStatsArray'

test('export independent roster calculator outputs', () => {
  Metadata.initialize()
  const cases = []
  for (const sample of [
    ...[-0.587, 0.413].map(critBuff => ({
      name: `evernight_basic_enemy80_${critBuff < 0 ? 'noncrit' : 'crit'}`, characterId: '1413', lightCone: '20021',
      hp: 1, enemyLevel: 80, resistance: 0.2, critBuff, attackBuff: 0.08,
      body: Stats.HP_P, sphere: Stats.HP_P, rope: Stats.HP_P,
      characterConditionals: { traceCritBuffs: true, memoTalentDmgBuff: true, skillMemoCdBuff: false,
        talentMemoCdBuff: true, memoriaStacks: 0, enhancedState: false, cyreneSpecialEffect: false,
        e1FinalDmg: false, e2CdBuff: false, e4Buffs: false, e6ResPen: false },
    })),
    ...[-0.05].map(critBuff => ({
      name: 'hyacine_basic_enemy80_crit', characterId: '1409', lightCone: '20021',
      hp: 1, enemyLevel: 80, resistance: 0.2, critBuff, attackBuff: 0.08,
      body: Stats.OHB, sphere: Stats.HP_P, rope: Stats.ERR,
      characterConditionals: { clearSkies: false, healTargetHp50: false, resBuff: true, spd200HpBuff: false,
        healingDmgStacks: 0, healTallyMultiplier: 0, e1HpBuff: false, e2SpdBuff: false, e4CdBuff: false, e6ResPen: false },
    })),
    ...[-0.237, 0.763].map(critBuff => ({
      name: `castorice_basic_enemy80_${critBuff < 0 ? 'noncrit' : 'crit'}`, characterId: '1407', lightCone: '20021',
      hp: 1, enemyLevel: 80, resistance: 0, critBuff, attackBuff: 0.08,
      body: Stats.HP_P, sphere: Stats.HP_P, rope: Stats.HP_P,
      characterConditionals: { memospriteActive: false, spdBuff: true, talentDmgStacks: 0, memoSkillEnhances: 0,
        memoTalentHits: 6, teamDmgBoost: false, memoDmgStacks: 0, cyreneSpecialEffect: false,
        e1EnemyHp50: false, e6Buffs: false },
    })),
    ...[-0.05, 0.95].map(critBuff => ({
      name: `lingsha_basic_enemy80_${critBuff < 0 ? 'noncrit' : 'crit'}`, characterId: '1222', lightCone: '23013',
      hp: 1, enemyLevel: 80, resistance: 0.2, critBuff, attackBuff: 0.08, broken: true,
      relicSet: Sets.PasserbyOfWanderingCloud, body: Stats.OHB, sphere: Stats.ATK_P, rope: Stats.ERR,
    })),
    ...[0.45, 0.55].flatMap(basicHitFraction => [-0.17, 0.83].map(critBuff => ({
      name: `jingyuan_teammate_fleet_basic_${basicHitFraction}_${critBuff < 0 ? 'noncrit' : 'crit'}`,
      characterId: '1204', lightCone: '20006', hp: 1, enemyLevel: 80, resistance: 0, critBuff,
      attackBuff: 0.08, basicHitFraction,
      characterConditionals: { skillCritBuff: false, talentHitsPerAction: 3, talentAttacks: 3,
        e2DmgBuff: false, e6FuaVulnerabilityStacks: 0, ex1EnhancedState: false },
    }))),
    ...[0, 0.2].flatMap(resistance => [false, true].flatMap(proof => [-0.29, 0.71].map(critBuff => ({
      name: `topaz_teammate_fleet_basic_res${resistance}_proof${proof}_${critBuff < 0 ? 'noncrit' : 'crit'}`, characterId: '1112', lightCone: '20000',
      hp: 1, enemyLevel: 80, resistance, critBuff, sphere: Stats.Fire_DMG, attackBuff: 0.08,
      characterConditionals: { enemyProofOfDebtDebuff: proof, numbyEnhancedState: false, e1DebtorStacks: 0 },
      lightConeConditionals: { critBuff: true },
    })))),
    ...[0.45, 0.55].flatMap(basicHitFraction => [-0.17, 0.83].map(critBuff => ({
      name: `jingyuan_basic_${basicHitFraction}_${critBuff < 0 ? 'noncrit' : 'crit'}`,
      characterId: '1204', lightCone: '20006', hp: 1, enemyLevel: 80, resistance: 0, critBuff, basicHitFraction,
      characterConditionals: { skillCritBuff: false, talentHitsPerAction: 3, talentAttacks: 3,
        e2DmgBuff: false, e6FuaVulnerabilityStacks: 0, ex1EnhancedState: false },
    }))),
    ...[0.3, 0.1, 0.6].map(ultimateHitFraction => ({
      name: `arlan_academic_ult_${ultimateHitFraction}_noncrit`, hp: 1, enemyLevel: 80,
      resistance: 0, critBuff: -0.05, damageBuff: 0.5, ultimateHitFraction,
    })),
    ...[0, 0.2].map(resistance => ({
      name: `natasha_enemy10_res${resistance}_noncrit`, characterId: '1105', lightCone: '23013',
      hp: 1, enemyLevel: 10, resistance, critBuff: -0.05,
      relicSet: Sets.PasserbyOfWanderingCloud, body: Stats.OHB, sphere: Stats.HP_P, rope: Stats.ERR,
    })),
    { name: 'natasha_enemy66_res0_noncrit', characterId: '1105', lightCone: '23013',
      hp: 1, enemyLevel: 66, resistance: 0, critBuff: -0.05,
      relicSet: Sets.PasserbyOfWanderingCloud, body: Stats.OHB, sphere: Stats.HP_P, rope: Stats.ERR },
    { name: 'natasha_enemy44_res0.2_noncrit', characterId: '1105', lightCone: '23013',
      hp: 1, enemyLevel: 44, resistance: 0.2, critBuff: -0.05,
      relicSet: Sets.PasserbyOfWanderingCloud, body: Stats.OHB, sphere: Stats.HP_P, rope: Stats.ERR },
    { name: 'natasha_enemy76_res0_noncrit', characterId: '1105', lightCone: '23013',
      hp: 1, enemyLevel: 76, resistance: 0, critBuff: -0.05,
      relicSet: Sets.PasserbyOfWanderingCloud, body: Stats.OHB, sphere: Stats.HP_P, rope: Stats.ERR },
    { name: 'natasha_enemy70_res0.2_noncrit', characterId: '1105', lightCone: '23013',
      hp: 1, enemyLevel: 70, resistance: 0.2, critBuff: -0.05,
      relicSet: Sets.PasserbyOfWanderingCloud, body: Stats.OHB, sphere: Stats.HP_P, rope: Stats.ERR },
    { name: 'natasha_enemy44_res0_noncrit', characterId: '1105', lightCone: '23013',
      hp: 1, enemyLevel: 44, resistance: 0, critBuff: -0.05,
      relicSet: Sets.PasserbyOfWanderingCloud, body: Stats.OHB, sphere: Stats.HP_P, rope: Stats.ERR },
    ...[0, 0.2].flatMap(resistance => [-0.05, 0.95].map(critBuff => ({
      name: `natasha_enemy40_res${resistance}_${critBuff < 0 ? 'noncrit' : 'crit'}`,
      characterId: '1105', lightCone: '23013', hp: 1, enemyLevel: 40, resistance, critBuff,
      relicSet: Sets.PasserbyOfWanderingCloud, body: Stats.OHB, sphere: Stats.HP_P, rope: Stats.ERR,
    }))),
    { name: 'skill_hp85_enemy10_expected', hp: 0.85, enemyLevel: 10, resistance: 0.2, critBuff: 0 },
    { name: 'basic_fullhp_enemy44_noncrit', hp: 1, enemyLevel: 44, resistance: 0, critBuff: -0.05 },
    { name: 'basic_fullhp_enemy44_crit', hp: 1, enemyLevel: 44, resistance: 0, critBuff: 0.95 },
    { name: 'basic_hit1_noncrit', hp: 1, enemyLevel: 44, resistance: 0, critBuff: -0.05, basicHitFraction: 0.3 },
    { name: 'basic_hit2_noncrit', hp: 1, enemyLevel: 44, resistance: 0, critBuff: -0.05, basicHitFraction: 0.7 },
    { name: 'basic_hit1_crit', hp: 1, enemyLevel: 44, resistance: 0, critBuff: 0.95, basicHitFraction: 0.3 },
    { name: 'basic_hit2_crit', hp: 1, enemyLevel: 44, resistance: 0, critBuff: 0.95, basicHitFraction: 0.7 },
    { name: 'natasha_heal', characterId: '1105', lightCone: '23013', hp: 1, enemyLevel: 44, resistance: 0.2, critBuff: 0,
      relicSet: Sets.PasserbyOfWanderingCloud, body: Stats.OHB, sphere: Stats.HP_P, rope: Stats.ERR },
    { name: 'serval_basic_noncrit', characterId: '1103', lightCone: '20006', hp: 1, enemyLevel: 70, resistance: 0, critBuff: -0.237,
      characterConditionals: { targetShocked: false, enemyDefeatedBuff: false } },
    { name: 'serval_basic_crit', characterId: '1103', lightCone: '20006', hp: 1, enemyLevel: 70, resistance: 0, critBuff: 0.763,
      characterConditionals: { targetShocked: false, enemyDefeatedBuff: false } },
    { name: 'march_shield', characterId: '1001', lightCone: '20003', hp: 1, enemyLevel: 44, resistance: 0.2, critBuff: 0,
      relicSet: Sets.KnightOfPurityPalace, ornamentSet: Sets.BelobogOfTheArchitects,
      body: Stats.DEF_P, sphere: Stats.DEF_P, rope: Stats.ERR, lightConeConditionals: { hp50DefBuff: false } },
    { name: 'march_shield_lowhp', characterId: '1001', lightCone: '20003', hp: 0.4, enemyLevel: 44, resistance: 0.2, critBuff: 0,
      relicSet: Sets.KnightOfPurityPalace, ornamentSet: Sets.BelobogOfTheArchitects,
      body: Stats.DEF_P, sphere: Stats.DEF_P, rope: Stats.ERR, lightConeConditionals: { hp50DefBuff: true } },
    { name: 'pela_basic_hit_noncrit', characterId: '1106', lightCone: '20004', hp: 1, enemyLevel: 74, resistance: 0, critBuff: -0.05,
      body: Stats.EHR, sphere: Stats.Ice_DMG, rope: Stats.ERR, basicHitFraction: 0.5,
      characterConditionals: { teamEhrBuff: true, enemyDebuffed: false, skillRemovedBuff: false, ultDefPenDebuff: false, e4SkillResShred: false } },
    { name: 'pela_basic_hit_crit', characterId: '1106', lightCone: '20004', hp: 1, enemyLevel: 74, resistance: 0, critBuff: 0.95,
      body: Stats.EHR, sphere: Stats.Ice_DMG, rope: Stats.ERR, basicHitFraction: 0.5,
      characterConditionals: { teamEhrBuff: true, enemyDebuffed: false, skillRemovedBuff: false, ultDefPenDebuff: false, e4SkillResShred: false } },
    { name: 'pela_ult_after_dispel_noncrit', characterId: '1106', lightCone: '20004', hp: 1, enemyLevel: 74, resistance: 0, critBuff: -0.05,
      body: Stats.EHR, sphere: Stats.Ice_DMG, rope: Stats.ERR,
      characterConditionals: { teamEhrBuff: true, enemyDebuffed: true, skillRemovedBuff: true, ultDefPenDebuff: true, e4SkillResShred: false } },
    { name: 'asta_basic_noncrit', characterId: '1009', lightCone: '20005', hp: 1, enemyLevel: 74, resistance: 0, critBuff: -0.117,
      sphere: Stats.Fire_DMG, rope: Stats.ERR,
      characterConditionals: { talentBuffStacks: 0, ultSpdBuff: false, fireDmgBoost: true } },
    { name: 'asta_basic_two_stacks_noncrit', characterId: '1009', lightCone: '20005', hp: 1, enemyLevel: 74, resistance: 0, critBuff: -0.117,
      sphere: Stats.Fire_DMG, rope: Stats.ERR,
      characterConditionals: { talentBuffStacks: 2, ultSpdBuff: false, fireDmgBoost: true } },
    ...[0.45, 0.55].flatMap(fraction => [-0.494, 0.506].map(critBuff => ({
      name: `danheng_basic_${fraction}_${critBuff < 0 ? 'noncrit' : 'crit'}`,
      characterId: '1002', lightCone: '20000', hp: 1, enemyLevel: 70, resistance: 0, critBuff,
      body: Stats.CR, sphere: Stats.Wind_DMG, rope: Stats.ATK_P, basicHitFraction: fraction,
      characterConditionals: { talentPenBuff: false, enemySlowed: false, spdBuff: false, e1EnemyHp50: false },
      lightConeConditionals: { critBuff: true },
    }))),
    { name: 'danheng_ult_slow_noncrit', characterId: '1002', lightCone: '20000', hp: 1, enemyLevel: 70, resistance: 0, critBuff: -0.494,
      body: Stats.CR, sphere: Stats.Wind_DMG, rope: Stats.ATK_P,
      characterConditionals: { talentPenBuff: false, enemySlowed: true, spdBuff: true, e1EnemyHp50: false },
      lightConeConditionals: { critBuff: true } },
    { name: 'danheng_skill_first_hit_pen_noncrit', characterId: '1002', lightCone: '20000', hp: 1, enemyLevel: 70, resistance: 0, critBuff: -0.494,
      body: Stats.CR, sphere: Stats.Wind_DMG, rope: Stats.ATK_P, skillHitFraction: 0.3,
      characterConditionals: { talentPenBuff: true, enemySlowed: false, spdBuff: false, e1EnemyHp50: false },
      lightConeConditionals: { critBuff: true } },
    { name: 'lynx_ultimate_heal', characterId: '1110', lightCone: '20008', hp: 0.5, enemyLevel: 70, resistance: 0, critBuff: 0,
      relicSet: Sets.PasserbyOfWanderingCloud, body: Stats.OHB, sphere: Stats.HP_P, rope: Stats.ERR,
      characterConditionals: { skillBuff: false } },
    ...[0.45, 0.55].flatMap(fraction => [-0.374, 0.626].map(critBuff => ({
      name: `danheng_slow_basic_${fraction}_${critBuff < 0 ? 'noncrit' : 'crit'}`,
      characterId: '1002', lightCone: '20000', hp: 1, enemyLevel: 70, resistance: 0, critBuff,
      body: Stats.CR, sphere: Stats.Wind_DMG, rope: Stats.ATK_P, basicHitFraction: fraction,
      characterConditionals: { talentPenBuff: false, enemySlowed: true, spdBuff: true, e1EnemyHp50: false },
      lightConeConditionals: { critBuff: false },
    }))),
    { name: 'seele_b1_ult_buffed_noncrit', characterId: '1102b1', lightCone: '20000', hp: 1, enemyLevel: 70, resistance: 0, critBuff: -0.374,
      body: Stats.CR, sphere: Stats.Quantum_DMG, rope: Stats.ATK_P,
      characterConditionals: { buffedState: true, speedBoostStacks: 1, dmgBoostStacks: 0, e1EnemyHp80CrBoost: false, e6UltTargetDebuff: false },
      lightConeConditionals: { critBuff: false } },
    ...[0.3, 0.7].flatMap(fraction => [-0.494, 0.506].map(critBuff => ({
      name: `seele_b1_basic_${fraction}_${critBuff < 0 ? 'noncrit' : 'crit'}`,
      characterId: '1102b1', lightCone: '20000', hp: 1, enemyLevel: 70, resistance: 0, critBuff,
      body: Stats.CR, sphere: Stats.Quantum_DMG, rope: Stats.ATK_P, basicHitFraction: fraction,
      characterConditionals: { buffedState: false, speedBoostStacks: 0, dmgBoostStacks: 0, e1EnemyHp80CrBoost: false, e6UltTargetDebuff: false },
      lightConeConditionals: { critBuff: true },
    }))),
    ...[-0.05, 0.95].map(critBuff => ({
      name: `danhengpt_basic_enemy80_${critBuff < 0 ? 'noncrit' : 'crit'}`,
      characterId: '1414', lightCone: '20003', hp: 1, enemyLevel: 80, resistance: 0, critBuff,
      attackBuff: 0.08, relicSet: Sets.MusketeerOfWildWheat,
      body: Stats.ATK_P, sphere: Stats.ATK_P, rope: Stats.ATK_P,
      lightConeConditionals: { hp50DefBuff: false },
    })),
    ...[-0.17, 0.83].map(critBuff => ({
      name: `aglaea_basic_enemy80_${critBuff < 0 ? 'noncrit' : 'crit'}`,
      characterId: '1402', lightCone: '20021', hp: 1, enemyLevel: 80, resistance: 0, critBuff,
      attackBuff: 0.08, body: Stats.ATK_P, sphere: Stats.Lightning_DMG, rope: Stats.ATK_P,
      characterConditionals: { supremeStanceState: false, seamStitch: false, memoSpdStacks: 0,
        cyreneSpecialEffect: false, e1Vulnerability: false, e2DefShredStacks: 0, e6Buffs: false },
    })),
    ...[-0.05, 0.95].map(critBuff => ({
      name: `memory_basic_enemy80_${critBuff < 0 ? 'noncrit' : 'crit'}`,
      characterId: '8007', lightCone: '20021', hp: 1, enemyLevel: 80, resistance: 0.2, critBuff,
      attackBuff: 0.08, body: Stats.CD, sphere: Stats.HP_P, rope: Stats.ERR,
      characterConditionals: { enhancedBasic: false, memoSkillHits: 4, teamCdBuff: false,
        memsSupport: false, energyTrueDmgValue: false, e1CrBuff: false, e4TrueDmgBoost: false, e6UltCrBoost: false },
    })),
  ]) {
  const form = generateFullDefaultForm(sample.characterId ?? '1008', sample.lightCone ?? '23002', 0, 1)
  Object.assign(form, {
    enemyLevel: sample.enemyLevel, enemyCount: 1, enemyResistance: sample.resistance,
    enemyElementalWeak: sample.resistance === 0, enemyWeaknessBroken: sample.broken ?? false,
    characterConditionals: sample.characterConditionals ?? (sample.characterId ? form.characterConditionals : { selfCurrentHpPercent: sample.hp }),
    lightConeConditionals: sample.lightConeConditionals ?? (sample.lightCone ? form.lightConeConditionals : { dmgBuff: false }),
    trace: true,
  })
  // Arlan and these sets have no CR threshold: forcing 0/100% isolates the
  // noncritical/critical branch without changing any other damage input.
  form.combatBuffs.CR = sample.critBuff
  form.combatBuffs.BOOST = sample.damageBuff ?? 0
  form.combatBuffs.ATK_P = sample.attackBuff ?? 0
  const simulation = {
    simType: StatSimTypes.SubstatRolls,
    request: {
      simRelicSet1: sample.relicSet ?? Sets.MusketeerOfWildWheat,
      simRelicSet2: sample.relicSet ?? Sets.MusketeerOfWildWheat,
      simOrnamentSet: sample.ornamentSet ?? Sets.FleetOfTheAgeless,
      simBody: sample.body ?? Stats.ATK_P, simFeet: Stats.SPD,
      simPlanarSphere: sample.sphere ?? Stats.Lightning_DMG, simLinkRope: sample.rope ?? Stats.ATK_P,
      stats: testStatSpread(0),
    },
  }
  const context = generateContext(form)
  // Fribbels combines basic hits. Supply the source hit fraction as an input
  // to its native calculator; this fraction is NOT an independently verified
  // parameter. No formula or resulting damage is supplied by the simulator.
  if (sample.basicHitFraction !== undefined) {
    const hits = new Set(context.allActions.filter(action => action.actionType === 'BASIC').flatMap(action => action.hits ?? []))
    for (const hit of hits) hit.atkScaling! *= sample.basicHitFraction
    expect(hits.size).toBeGreaterThan(0)
  }
  if (sample.skillHitFraction !== undefined) {
    const hits = new Set(context.allActions.filter(action => action.actionType === 'SKILL').flatMap(action => action.hits ?? []))
    for (const hit of hits) hit.atkScaling! *= sample.skillHitFraction
    expect(hits.size).toBeGreaterThan(0)
  }
  if (sample.ultimateHitFraction !== undefined) {
    const hits = new Set(context.allActions.filter(action => action.actionType === 'ULT').flatMap(action => action.hits ?? []))
    for (const hit of hits) hit.atkScaling! *= sample.ultimateHitFraction
    expect(hits.size).toBeGreaterThan(0)
  }
  const result = runStatSimulations([simulation] as any, form, context)[0]
  expect(Object.values(result.actionDamage!).every(Number.isFinite)).toBe(true)
  cases.push({
    sample,
    sourceCommit: 'd60f0375e6649cebbc82dc6f34b34d64fb0869d2',
    outputMode: sample.critBuff === 0 ? 'expected damage including critical probability' : 'forced critical branch',
    form, simulation,
    basicStats: Object.fromEntries(Object.entries(BasicKey).map(([key, index]) => [key, result.ca[index]])),
    primaryActionStats: result.primaryActionStats,
    actionDamage: result.actionDamage, actionBuffSnapshots: result.actionBuffSnapshots,
  })
  }
  writeFileSync('/tmp/hsr_v1_fribbels_references.json', JSON.stringify(cases, null, 2))
})

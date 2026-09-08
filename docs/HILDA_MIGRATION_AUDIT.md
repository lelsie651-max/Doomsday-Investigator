# Hilda Migration Audit

## 1. Canonical Identity

- Canonical ID: `hilda`
- Canonical display name: `希尔达`
- Deprecated character version: `zhoujie` / `周姐`
- Non-canonical PoC ID: `xida`

This audit is a preflight for `P0-2B`. It is not a production rename plan. Current production runtime still uses `zhoujie`, and that is intentional for `P0-2A`.

## 2. Confirmed Product Facts

Only the following Hilda facts are currently confirmed:

- 变异女高中生
- 表面张扬、满不在乎
- 爱约会、调侃僵尸凯子
- 内里极度缺乏安全感
- 越嘴硬越掩饰难过

No additional production personality, strategy, relationship, witness, gossip, extortion, or task-design fields should be inferred from this document.

## 3. Reference Inventory

| File | Reference | Category | Runtime impact | P0-2B action |
| --- | --- | --- | --- | --- |
| `backend/data/npc_profiles.json` | `zhoujie` profile key and display content | A, B | Production NPC identity and semantic source of truth | Replace only after confirmed Hilda production profile exists |
| `backend/data/npc_profiles.json` | `_initial_relationships` with `from/to = zhoujie` | A | Production relationship seed keys | Product decision required before migration |
| `backend/game_state.py` | Builds NPC states from `npc_profiles.json` keys | A | Production state instantiates `zhoujie` | Update only during formal runtime migration |
| `backend/data_loader.py` | Loads and serves profile fields from `npc_profiles.json` | A | Shared production data access path | Revalidate after production profile replacement |
| `backend/memory_system.py` | Observer and target memory keys derive from profile IDs | A | Production memory keys include `zhoujie` | Plan memory-key migration explicitly |
| `backend/game_controller.py` | Preferred NPC order contains `zhoujie` | A | Production ordering/display dependency | Update during runtime migration |
| `backend/vote_system.py` | Consumes `vote_strategy`, including `grudge` | A, B | Zhoujie semantic strategy affects production votes | Do not reuse without product-approved Hilda strategy |
| `backend/agent_service.py` | Reads identity and aim by runtime NPC ID | A | AI-side production context depends on runtime ID/profile | Update together with production profile migration |
| `backend/night_alliance_system.py` | Reads display and profile semantics | A | Production night text/context uses current profile | Revalidate during migration |
| `backend/data/fallback/f01_npc_task_reason.csv` | `zhoujie` task flavor text | B | Production fallback text bound to old character semantics | Rewrite for Hilda, do not rename |
| `backend/data/fallback/f05_duo_act2.csv` | `zhoujie` duo reaction text | B | Production fallback text bound to old character semantics | Rewrite for Hilda, do not rename |
| `backend/data/fallback/f08_vote_reason.csv` | `zhoujie` vote reasons | B | Production fallback text bound to grudge persona | Rewrite for Hilda, do not rename |
| `backend/data/fallback/f10_blackmail_reaction.csv` | `zhoujie` extortion reactions | B | Production fallback text bound to old character semantics | Rewrite for Hilda, do not rename |
| `backend/data/elements/random_accidents.csv` | Many `npc=zhoujie` events | B | Production semantic event content | Rewrite by character, not by string replacement |
| `backend/data/config/pua_templates.csv` | `zhoujie` manager interrogation reactions | B | Production semantic dialogue content | Rewrite for Hilda only after product approval |
| `backend/data/config/boss_npc_observations.csv` | `zhoujie` boss observation summaries | B | Production semantic observation flavor | Rewrite for Hilda |
| `backend/data/config/npc_anomaly_events.csv` | `zhoujie` anomaly lines, includes dirty `周杰伦` text | B, F | Semantic data and historical dirty evidence | Clean during formal migration review |
| `backend/data/npc_extended_profiles.json` | Empty `xida` placeholder; internal `希尔达` relationship text in `laowang` profile | C | PoC only, not in formal main loop | Safe `xida -> hilda` placeholder unification in `P0-2A` |
| `backend/test_daily_state_demo.py` | Uses `希尔达` in Daily State demo context | C, D | PoC/demo only | Keep aligned with PoC naming, not runtime proof |
| `test_module6.py` | Hardcoded `zhoujie` and grudge-vote expectation | D | Statistical/debug test depends on old identity and semantics | Update with product-approved Hilda voting semantics |
| `test_ws_client.py` | Hardcoded NPC ID list with `zhoujie` | D | Manual debug path | Update when runtime ID migrates |
| `backend/test_negotiation_behavior.py` | Hardcoded `zhoujie` / `周姐` | D | Real-AI manual behavior test | Update after Hilda production profile exists |
| `test_ai_pipeline.py` | Memory text mentions `周姐` | D | Test/debug text fixture | Update with runtime migration |
| `docs/debug_api_draft.md` | Debug examples contain `zhoujie` | D, F | Documentation/debug reference | Update when API examples are refreshed |
| `Godot前端工程/scripts/working_ui.gd` | `NPC_DISPLAY_NAMES["zhoujie"] = "周姐"` | E | Front-end runtime display dependency | Record now, update only in dedicated front-end round |
| `Godot前端工程/data/opening_scenes.csv` | Opening scene text says `半机械人周姐` | E | Front-end narrative dependency | Record now, update only in dedicated front-end round |
| `docs/CURRENT_STATE.md` | Describes current drift among `zhoujie` / `xida` / `hilda` | F | Baseline documentation | Keep synced with migration progress |

Category legend:

- A = Production runtime identity
- B = Production semantic character content
- C = PoC / experimental
- D = Tests / debug fixtures
- E = Godot/runtime front-end dependencies
- F = Historical evidence / archived logs / docs

## 4. Zhoujie-only Semantic Fields

Audit target: current `backend/data/npc_profiles.json` `zhoujie` block.

| Field | Assessment | Notes |
| --- | --- | --- |
| `name` | Clearly Zhoujie-specific | Current value is `周姐` |
| `species` | Clearly Zhoujie-specific | Current value is `半机械人`, conflicts with confirmed Hilda fact `变异女高中生` |
| `personality` | Clearly Zhoujie-specific | `赛博容嬷嬷` semantic package is old-character-specific |
| `vote_tendency` | Clearly Zhoujie-specific | Current text is explicit grudge persona |
| `hidden_goal` | Clearly Zhoujie-specific | Contains fake-accounting and corruption setting |
| `task_preferences` | Requires product decision | Numeric weights might be mechanically reusable, but no approved Hilda mapping exists |
| `aim` | Clearly Zhoujie-specific | Built around revenge and vote-cleansing agenda |
| `as_primary` | Clearly Zhoujie-specific | Full reaction matrix expresses Zhoujie values and tone |
| `identity` | Clearly Zhoujie-specific | Explicit half-cyborg and grudge identity |
| `display_name` | Clearly Zhoujie-specific | Current value is `周姐` |
| `aliases` | Clearly Zhoujie-specific | Current alias list is Zhoujie-only |
| `public_impression` | Clearly Zhoujie-specific | Scanning-accounting-veteran semantic package |
| `witness_default` | Requires product decision | Role of field is reusable, current wording is not |
| `witness_reaction` | Clearly Zhoujie-specific | Mechanical eye, grudge book, extortion tone |
| `gossip_chance` | Requires product decision | Numeric value exists but no approved Hilda behavior mapping |
| `extortion_price_min/max` | Requires product decision | Mechanical numeric reuse cannot be assumed |
| `gossip_style` | Clearly Zhoujie-specific | Current tone belongs to old persona |
| `vote_strategy` | Requires product decision | Runtime strategy choice is gameplay-significant and not approved for Hilda |
| `identity_2p` | Clearly Zhoujie-specific | 2P identity is explicit old persona |
| `aim_2p` | Clearly Zhoujie-specific | 2P aim is explicit old revenge/vote logic |

Conclusion: the current `zhoujie` block is not just an obsolete ID. It is a complete deprecated semantic character package and must not be renamed into Hilda.

## 5. Relationship Migration

Current production seeded relationship references in `backend/data/npc_profiles.json`:

- `zhoujie -> xiaoli`: `affinity = -25`, `suspicion = 15`
- `xiaoli -> zhoujie`: `affinity = -10`, `suspicion = 20`
- `zhoujie -> boss`: `affinity = 5`, `suspicion = 10`
- `boss -> zhoujie`: `affinity = -5`, `suspicion = 25`

Other relationship-style references discovered:

- `backend/data/npc_extended_profiles.json`: `laowang` PoC relationship anchors and daily attitudes already use `希尔达` by name
- `backend/test_daily_state_demo.py`: Daily State demo text uses `希尔达`

This round only inventories these references. Whether any numeric relationships should transfer to Hilda is a product decision and must not be assumed.

## 6. Test / Debug Impact

The following assets must be reviewed when `P0-2B` formally migrates production identity and character semantics:

- `test_module6.py`
- `test_ws_client.py`
- `backend/test_negotiation_behavior.py`
- `test_ai_pipeline.py`
- `docs/debug_api_draft.md`

Additional regression paths to re-run during `P0-2B`:

- `test_time_baseline.py`
- `test_scenario_matrix.py`
- `test_bystander_memory_regression.py`

## 7. Godot Impact

Confirmed front-end dependencies:

- `Godot前端工程/scripts/working_ui.gd`: hardcoded display mapping for `zhoujie -> 周姐`
- `Godot前端工程/data/opening_scenes.csv`: opening narrative explicitly names `半机械人周姐`

These are runtime-facing front-end references, but this round must not modify Godot.

## 8. P0-2B Preconditions

Formal production migration should not start until product confirms required Hilda production fields, especially:

- production `name` / `display_name` baseline if any distinction is intended
- production `species`
- production `personality`
- production `vote_tendency`
- production `hidden_goal`
- production `task_preferences`
- production `aim`
- production `as_primary`
- production `identity`
- production `aliases`
- production `public_impression`
- production `witness_default`
- production `witness_reaction`
- production `gossip_chance`
- production `extortion_price_min/max`
- production `gossip_style`
- production `vote_strategy`
- production `identity_2p`
- production `aim_2p`
- relationship policy for current `zhoujie` links and whether any values transfer
- fallback semantic asset policy for CSV-based reactions, vote reasons, accidents, and boss observations
- memory-key migration policy for `zhoujie` observer/target keys
- front-end rename plan for Godot display strings and opening scene text

Until those inputs exist, `P0-2B` must not be executed as a mechanical rename.

# Behavior Truth Audit

## 1. Scope
- This is a behavior truth audit for pre-refactor stabilization.
- It records current code facts, current regression fingerprints, and test-truth classification.
- It is not a final gameplay design document.
- `CURRENT CODE FACT` does not automatically mean `PRODUCT-CONFIRMED INVARIANT`.
- Any behavior that product has not re-confirmed stays under `PENDING FLOW REDESIGN`.

## 2. Current Regression Fingerprint
- Offline baseline before audit:
  - `test_ai_runtime_baseline.py`: PASS
  - `test_time_baseline.py`: PASS
  - `test_scenario_matrix.py`: PASS
  - `test_bystander_memory_regression.py`: `PASS {4,8}` / `FAIL {1,2,3,5,6,7}`
- This audit did not change runtime code or tests.

## 3. Bystander Checkpoint Matrix
| # | Expectation | Current runtime | Classification | Root cause area | Product status |
| --- | --- | --- | --- | --- | --- |
| 1 | Room-local same-task NPC pairing emits template interaction log | Current code does emit `[NPC_NPC_TEMPLATE]` from `_resolve_npc_npc_template_interaction()` when same-task NPC pairing happens in settlement | `TEST_HARNESS_DRIFT` | Shared checkpoint `1/2/3` helper aborts on later memory assertion, so checkpoint 1 is reported failed even though the log path is live | `CURRENT CODE FACT ONLY` |
| 2 | Both NPCs write mutual impression memories | Current code writes both directions, but writes structured memory entries as `{"text": ..., "sealed": ...}` instead of raw strings | `TEST_HARNESS_DRIFT` | `test_bystander_memory_regression.py` still treats memory entries as plain strings | `CURRENT CODE FACT ONLY` |
| 3 | Both NPCs mutate affinity / suspicion after interaction | Current code mutates both directions in `_resolve_npc_npc_template_interaction()` | `TEST_HARNESS_DRIFT` | Shared checkpoint `1/2/3` exits on checkpoint 2 before relation assertions run | `CURRENT CODE FACT ONLY` |
| 4 | Blackmail broadcast skips NPC-NPC pairing | Current code explicitly short-circuits pairing when `is_blackmail=True` and logs `skip pairing due to blackmail` | `CURRENT_BEHAVIOR_BUT_NOT_LOCKED` | Hour-settlement guard | `CURRENT CODE FACT ONLY` |
| 5 | Group blackmail writes two memories per listener | Current code writes one listener -> player memory and one listener -> subject memory per listener, but test injects non-production `subject_judgement` values and still reads structured memory as raw strings | `TEST_HARNESS_DRIFT` | Structured memory schema + blackmail payload shape drift | `CURRENT CODE FACT ONLY` |
| 6 | Bystander memory should use `witness_default` template | Current formal route for `case 3/10` writes bystander memory through `play_solo_action_with_ai()`, but uses `witness_reaction` phrasing, not `witness_default`; direct raw helper call writes nothing for this case | `OBSOLETE_PRODUCT_EXPECTATION` | Bystander template source changed; test also bypasses required frontstage route | `PENDING FLOW REDESIGN` |
| 7 | S5 should pick only one participant and convert the rest into bystanders | Current code can produce `1 participant + remaining observers`, but the test constructs `player + 3 same-task NPCs`, which is not current formal `S5`; it also reads structured memories as raw strings and expects old `注意到...` wording | `TEST_HARNESS_DRIFT` | Scenario construction drift + structured memory schema drift + bystander text drift | `CURRENT CODE FACT ONLY` |
| 8 | NPC-NPC templates must come from CSV, not hardcoded strings | Current code loads `backend/data/fallback/f13_npc_npc_interaction.csv` through `DataLoader.get_npc_npc_interaction_template()` | `CURRENT_BEHAVIOR_BUT_NOT_LOCKED` | Fallback CSV data source | `CURRENT CODE FACT ONLY` |

## 4. Shared Root-cause Clusters
### Cluster A — Structured memory entry migration
- Checkpoints `2`, `5`, and part of `7` still read memory entries as if they were plain strings.
- Current `MemorySystem.add_impression()` stores dict entries with `text` / `sealed`.
- This also indirectly makes checkpoint `1` and `3` look failed because the shared `1/2/3` helper aborts at the first stale memory assertion.

### Cluster B — Bystander settlement semantics drift
- Current bystander settlement is no longer one single legacy path.
- `_apply_observer_effects()` is explicitly deprecated.
- Formal settlement now splits across:
  - `_resolve_hour_bystander_and_npc_pairs()`
  - `play_solo_action_with_ai()` for `case 3/10`
  - blackmail direct-settlement builders
- Old expectations built around `witness_default` and `注意到...` no longer match all current routes.

### Cluster C — Scenario setup drift vs formal room routing
- Checkpoint `6` directly calls `_resolve_hour_bystander_and_npc_pairs()` without going through the frontstage room-case dispatcher.
- Checkpoint `7` claims to test formal `S5`, but actually constructs a room where all three NPCs share the player's task; that is not current formal `S5`.
- Current formal `S5` means: at least one matched coworker plus at least one non-matched coworker.

### Cluster D — Blackmail payload shape drift
- Production blackmail flow normalizes `player_judgement` / `subject_judgement` to the closed set:
  - `增加怀疑`
  - `减少怀疑`
  - `无感`
- Checkpoint `5` injects free-form natural-language judgements and then expects them to appear verbatim in stored subject memories.
- That no longer reflects the production payload contract.

## 5. Test Assertion Truth Map
### `test_module2.py`
- `Task pool shape (12 tasks / 2-3 evidence / room <= 4)`: `CURRENT_BEHAVIOR_LOCK_CANDIDATE`
- `NPC gets 5 selected tasks and current_room follows task[0]`: `CURRENT_BEHAVIOR_LOCK_CANDIDATE`
- `Player must select exactly 5 tasks; over-pick / duplicate / empty rejected`: `CURRENT_BEHAVIOR_LOCK_CANDIDATE`
- `EvidenceConverter strips internal evidence tags from AI/frontend-facing context`: `CURRENT_BEHAVIOR_LOCK_CANDIDATE`
- `Daily setup -> prompt context -> advance_task -> frontend task pool safety`: `CURRENT_BEHAVIOR_LOCK_CANDIDATE`
- `Two generated pools may differ` print-only observation: `DEBUG_OBSERVATION`
- `大壮房间分布偏向 warehouse` print-only observation: `DEBUG_OBSERVATION`

### `test_module3.py`
- `Boss office constants / initial boss room`: `CURRENT_BEHAVIOR_LOCK_CANDIDATE`
- `Boss hourly plan has 5 hours and valid enum items`: `CURRENT_BEHAVIOR_LOCK_CANDIDATE`
- `Boss hourly plan may contain <= 1 PUA`: `OBSOLETE_EXPECTATION`
- `execute_boss_hour(PATROL / SHADY)` result structure: `CURRENT_BEHAVIOR_LOCK_CANDIDATE`
- `execute_boss_hour(PUA)` direct call behavior: `LEGACY_BUT_USEFUL`
- `get_player_coworkers()` / `get_room_snapshot()` / `advance_hour()` structure checks: `CURRENT_BEHAVIOR_LOCK_CANDIDATE`
- `handle_pua_interruption()` player/NPC relocation: `CURRENT_BEHAVIOR_LOCK_CANDIDATE`
- `get_all_positions()` returns valid room values: `CURRENT_BEHAVIOR_LOCK_CANDIDATE`
- `day5 average patrol > day1 average patrol`: `STATISTICAL_BEHAVIOR`

### `test_module4.py`
- `Legacy EVENT_TEMPLATES / RESULT_TEMPLATES table shape`: `LEGACY_BUT_USEFUL`
- `Legacy 3-bucket combo expectations`: `OBSOLETE_EXPECTATION`
- `Legacy select_event() repeat-avoidance behavior`: `LEGACY_BUT_USEFUL`
- `StateManager.trigger_event()` / `resolve_player_cards()` through legacy event path: `LEGACY_BUT_USEFUL`
- `use_record_card_on_event()` status transitions and duplicate rejection: `CURRENT_BEHAVIOR_LOCK_CANDIDATE`
- `Legacy evidence hint injection into build_event_display()`: `LEGACY_BUT_USEFUL`

### `test_module6.py`
- `NPC/boss vote tendency sampled over 100 runs`: `STATISTICAL_BEHAVIOR`
- `execute_vote()` response structure and vote_details shape: `CURRENT_BEHAVIOR_LOCK_CANDIDATE`
- `Cannot vote self / boss / eliminated NPC`: `CURRENT_BEHAVIOR_LOCK_CANDIDATE`
- `Player eliminated branch may occur`: `STATISTICAL_BEHAVIOR`
- `Frontend vote candidate list shape and elimination filtering`: `CURRENT_BEHAVIOR_LOCK_CANDIDATE`

### `test_module7.py`
- `new_game()` / `get_game_status()` baseline structure: `CURRENT_BEHAVIOR_LOCK_CANDIDATE`
- `Full 5-day random simulation loop`: `DEBUG_OBSERVATION`
- `submit_task_selection(min(6, len(pool))) should succeed`: `OBSOLETE_EXPECTATION`
- `Old synchronous night transition via enter_night_phase()`: `OBSOLETE_EXPECTATION`
- `Task-selection empty / fake-task rejection`: `CURRENT_BEHAVIOR_LOCK_CANDIDATE`
- `Task selection -> working -> voting -> night coarse phase order`: `LEGACY_BUT_USEFUL`

## 6. Confirmed Behavior-lock Candidates
- `MemorySystem.add_impression()` stores structured entries and downstream tests must unpack them instead of reading raw dicts.
- NPC-NPC same-task settlement writes both directions of memory and applies both directions of relation deltas.
- Group blackmail settlement writes listener -> player and listener -> subject entries separately.
- `TaskSystem.validate_player_selection()` enforces exactly 5 tasks and rejects duplicates / empty picks.
- `get_task_pool_for_frontend()` must not leak `evidence_tag` or `evidence_type`.
- Current room-route preview still maps to the 5-scenario matrix used by `test_scenario_matrix.py`.
- NPC-NPC interaction templates are loaded from fallback CSV, not hardcoded in the settlement path.

## 7. Bugs Worth Fixing Before Refactor
- No `CONFIRMED_PRODUCTION_BUG` was proven from the current `test_bystander_memory_regression.py` failure set.
- The six failing checkpoints are currently explained by a mix of:
  - stale test harness assumptions,
  - structured-memory schema drift,
  - route-construction drift,
  - obsolete expectation about `witness_default`.

## 8. Expectations Requiring Product Decision
- Should `S3/S4` solo routes always create a bystander memory, or is “no witness memory unless stronger interaction happens” acceptable?
- If solo-route bystander memory stays, should the text source be `witness_reaction`, `witness_default`, or a third dedicated template family?
- For blackmail memory, should the stored subject-side reaction preserve normalized judgement buckets only, or preserve a richer natural-language reaction line?
- Should group same-task NPC clustering with one chosen participant and the rest as observers be treated as a formal player-facing rule, or only as current implementation detail?

## 9. P1-0B Recommendation
- First split `test_bystander_memory_regression.py` into isolated checkpoints instead of the current shared `1/2/3` bundle.
- Add characterization tests that assert on unpacked memory text, not raw container objects.
- Add formal-route characterization for:
  - `case 3` solo-route witness memory
  - `S5` one-participant / remaining-observer settlement
  - group blackmail dual-memory writes
- Only after those characterization tests exist, reconsider whether any remaining gap is a real runtime regression worth fixing before `GameController` refactor.

# Legacy / Compatibility Runtime Audit

## 1. Scope and Definitions
- This audit classifies current legacy-looking paths by runtime reachability, not by naming style.
- `ACTIVE_PRODUCTION`: currently reachable from `Godot -> WebSocket -> server.py -> GameController` and affects real gameplay.
- `ACTIVE_COMPATIBILITY_NOOP`: still called by the formal chain, but now acts as a compatibility shell / placeholder and no longer performs its original business role.
- `ACTIVE_FALLBACK`: not the preferred path, but still production-reachable when the primary path is unavailable or returns no data.
- `UNREACHABLE_LEGACY_IMPLEMENTATION`: implementation still exists, but current production call graph does not reach it.
- `DEBUG_OR_MANUAL_ONLY`: reachable only from debug UI, standalone scripts, CLI, or manual probes.
- `ARCHIVED_REFERENCE`: historical docs / scan reports only; not executable runtime.
- `AMBIGUOUS`: code evidence is insufficient to safely decide whether the path is removable.

## 2. Production Entry Points
- Current formal runtime chain is `Godot -> WebSocket -> server.py -> GameController -> StateManager / EventSystem / TaskSystem / MovementSystem / VoteSystem / NightAllianceSystem / AI helpers`.
- `server.py` is the only formal backend network entry for current production gameplay.
- Current formal player flow is:
  `new_game -> select_tasks -> start_move -> movement_done -> play_cards / choose_work_mode / respond_negotiation / record / scout -> cast_vote -> enter_night -> next_day / get_ending_summary`.
- `backend/play.py` is a separate CLI path and is not part of the formal WebSocket production chain.

## 3. Active Compatibility Paths
| Path | Caller | Current behavior | Side effects | Classification |
| --- | --- | --- | --- | --- |
| `AgentService.all_agents_select_tasks()` | `GameController.submit_task_selection()` | Returns a compatibility payload with empty `npc_selections` and `boss_plan={"patrol_rooms": [], "reason": "deprecated_by_boss_pua_plan"}` | No DeepSeek call, no RNG, no gameplay state change by itself | `ACTIVE_COMPATIBILITY_NOOP` |
| `GameController._apply_agent_selections()` | `GameController.submit_task_selection()` after `all_agents_select_tasks()` | Still runs if `_agent_results` exists, but empty `boss_plan.patrol_rooms` makes the body effectively skip the old boss application | Reads `_agent_results`; current audited path produces no boss schedule write | `ACTIVE_COMPATIBILITY_NOOP` |
| `NetworkManager.start_move()` | Legacy client-side alias wrapper | Thin alias to `start_movement()` | Same websocket message as current path if manually used | `ACTIVE_COMPATIBILITY_NOOP` |
| `NetworkManager.movement_done()` | Legacy client-side alias wrapper | Thin alias to `notify_movement_done()` | Same websocket message as current path if manually used | `ACTIVE_COMPATIBILITY_NOOP` |

## 4. Unreachable Legacy Implementations
| Function / module | Last known purpose | Current callers | Classification | Future action |
| --- | --- | --- | --- | --- |
| `AgentService.npc_select_tasks()` | Old AI NPC daytime task selection | No production callers; no test/manual caller found in current repo | `UNREACHABLE_LEGACY_IMPLEMENTATION` | `CANDIDATE FOR P1 REMOVAL` |
| `AgentService.boss_plan_day()` | Old manager route planning | No production callers; only mentioned in comments inside `all_agents_select_tasks()` | `UNREACHABLE_LEGACY_IMPLEMENTATION` | `CANDIDATE FOR P1 REMOVAL` |
| `GameController.trigger_agent_decisions()` | Old pre-decision bridge for task stage | No callers found | `UNREACHABLE_LEGACY_IMPLEMENTATION` | `CANDIDATE FOR P1 REMOVAL` |
| `GameController.record_scout_evidence()` | Old “record scout as evidence only” shortcut | No callers found; server already routes to `record_scout_evidence_v2()` | `UNREACHABLE_LEGACY_IMPLEMENTATION` | `NEEDS BEHAVIOR LOCK FIRST` |
| `NetworkManager.record_scout_evidence()` | Old Godot helper for evidence-only scout recording | No current `.gd` caller found; current UI uses `record_scout_evidence_v2()` | `UNREACHABLE_LEGACY_IMPLEMENTATION` | `NEEDS BEHAVIOR LOCK FIRST` |

## 5. Active Fallback Paths
| Path | Primary path | Fallback condition | Current behavior | Classification |
| --- | --- | --- | --- | --- |
| `GameController.trigger_event_v2() -> StateManager.trigger_event()` | Skeleton event pipeline | `StateManager.trigger_skeleton_event()` returns `None` | Falls back to old template event selection and display generation | `ACTIVE_FALLBACK` |
| `StateManager.trigger_event()` | Skeleton event pipeline | Called only by the above fallback | Uses `EventSystem.select_event()` + `EventSystem.build_event_display()` | `ACTIVE_FALLBACK` |
| `EventSystem.select_event()` / `EventSystem.build_event_display()` | `select_skeleton_event()` / `build_event_display_v2()` | Old event template fallback | Still production-reachable through `trigger_event_v2()` fallback | `ACTIVE_FALLBACK` |

Do not remove these fallback paths without a behavior lock first.

## 6. Debug / Manual-only Paths
| Path | Evidence | Current role | Classification |
| --- | --- | --- | --- |
| `backend/play.py` | Standalone CLI entry via `if __name__ == "__main__"`; not routed from `server.py` | Manual local play path | `DEBUG_OR_MANUAL_ONLY` |
| `GameController.enter_night_phase()` | Called by `backend/play.py` and `test_module7.py`; production server calls `enter_night_phase_v2()` instead | Old simple night transition | `DEBUG_OR_MANUAL_ONLY` |
| `server.py:get_status` route | Used by `game_ui.gd` debug NPC status popup and `test_network.gd`; not part of normal player progression | Runtime inspection / debug surface | `DEBUG_OR_MANUAL_ONLY` |
| `server.py:debug_seed_work_snapshot` route | Used by debug document and debug tooling only | Scenario injection / debug surface | `DEBUG_OR_MANUAL_ONLY` |
| `test_ws_client.py` | Requires a running websocket server and simulates a client session | Manual integration probe, not a canonical baseline test | `DEBUG_OR_MANUAL_ONLY` |
| `test_ai_pipeline.py` | Explicitly requires real API key for AI half | Manual AI observation script | `DEBUG_OR_MANUAL_ONLY` |

## 7. Server / WebSocket Compatibility
### Current production protocol
- Current production message types exposed by `server.py` and used by current Godot flow:
  - `new_game`
  - `select_tasks`
  - `start_move`
  - `movement_done`
  - `choose_work_mode`
  - `play_cards`
  - `respond_negotiation`
  - `use_record_card`
  - `use_blame_card`
  - `use_blackmail`
  - `scout_dispatch`
  - `record_scout`
  - `skip_record`
  - `cast_vote`
  - `enter_night`
  - `night_open_door`
  - `night_respond`
  - `night_seek_alliance`
  - `night_scout`
  - `buy_item`
  - `get_shop`
  - `next_day`
  - `get_ending_summary`

### Compatibility / debug routes
- `get_status` is still publicly routed by `server.py`, but current evidence shows it is used by the NPC status debug popup, not by the ordinary player progression.
- `debug_seed_work_snapshot` is a debug-only route used for scenario forcing.
- `scout_room` is still publicly routed by `server.py` and `NetworkManager` still exposes a wrapper, but current Godot UI call sites use `dispatch_scout()` instead. This is not dead code, but current repo evidence cannot prove whether any out-of-repo older client still depends on it.

### Explicit protocol drift findings
- Current Godot night flow uses:
  `enter_night -> night_open_door / night_respond / night_seek_alliance / night_scout`.
- Current Godot ending flow uses:
  `next_day` game-over flag -> `get_ending_summary`.
- Old `game_over` push-style route is not part of the current formal protocol.
- `cleanup_scan_report.md` mentions `_handle_spy_chat` / `_handle_record_chat`, but these handlers do not exist in current `server.py`; that report is historical reference, not current routing truth.

## 8. Test Asset Truth Map
- File-level labels are safe only for the fully deterministic baseline tests.
- For mixed legacy files, block-level truth mapping now lives in `docs/BEHAVIOR_TRUTH_AUDIT.md`.

| Asset | Truth category | Why |
| --- | --- | --- |
| `test_ai_runtime_baseline.py` | `CURRENT_BASELINE` | Deterministic offline guard for DeepSeek runtime config and helper invariants |
| `test_time_baseline.py` | `CURRENT_BASELINE` | Protects current 5-slot time baseline |
| `test_scenario_matrix.py` | `CURRENT_BASELINE` | Protects current work-route scenario matrix and debug seeding assumptions |
| `test_bystander_memory_regression.py` | `CURRENT_KNOWN_FAILING_BASELINE` | Known fingerprint is intentionally recorded as `PASS {4,8} / FAIL {1,2,3,5,6,7}`; truth classification now lives in `docs/BEHAVIOR_TRUTH_AUDIT.md` |
| `test_module2.py` | `MIXED — SEE BEHAVIOR_TRUTH_AUDIT` | Contains current low-level invariants plus debug-only observations; no longer safe to classify at whole-file granularity |
| `test_module3.py` | `MIXED — SEE BEHAVIOR_TRUTH_AUDIT` | Contains current structural checks, statistical behavior, and obsolete boss-plan expectations |
| `test_module4.py` | `MIXED — SEE BEHAVIOR_TRUTH_AUDIT` | Contains useful fallback coverage plus obsolete legacy-combo expectations |
| `test_module6.py` | `MIXED — SEE BEHAVIOR_TRUTH_AUDIT` | Contains both current vote-structure invariants and statistical tendency checks |
| `test_module7.py` | `MIXED — SEE BEHAVIOR_TRUTH_AUDIT` | Mixes current baseline structure, debug observation loops, and obsolete old-flow assumptions |
| `test_ws_client.py` | `DEBUG_TOOL` | Manual websocket client probe, not a canonical regression baseline |
| `test_ai_pipeline.py` | `MANUAL_AI` | Explicitly contains real-model path and human observation intent |
| `backend/test_daily_state_demo.py` | `MANUAL_AI` | Demo / PoC AI script, not a baseline regression test |
| `backend/test_negotiation_behavior.py` | `MANUAL_AI` | Real AI sampling / observation path |

## 9. P1 Cleanup Candidates
### SAFE_CANDIDATE
- `AgentService.npc_select_tasks()`
- `AgentService.boss_plan_day()`
- `GameController.trigger_agent_decisions()`

### BEHAVIOR_LOCK_REQUIRED
- `GameController.record_scout_evidence()`
- `NetworkManager.record_scout_evidence()`
- `EventSystem.select_event()` / `build_event_display()` fallback cluster

### FLOW_DECISION_REQUIRED
- `server.py:scout_room` compatibility route
- `NetworkManager.scout_room()` compatibility wrapper
- `backend/play.py` CLI flow

### DO_NOT_REMOVE_FALLBACK
- `GameController.trigger_event_v2() -> StateManager.trigger_event()` fallback bridge
- `StateManager.trigger_event()`
- `EventSystem.select_event()` / `build_event_display()` while v2 skeleton coverage is not behavior-locked

## 10. Open Questions
- Should `server.py:scout_room` remain as an externally supported compatibility route for older clients, or be formally demoted to manual-only after a protocol cut?
- Should `backend/play.py` remain as a maintained CLI debug flow, or be treated as disposable after websocket/web tooling fully replaces it?
- Should old event-template fallback behavior receive explicit regression locks before any P1 removal decision?

## Agent Task / Boss Plan Chain Notes
- `GameController.submit_task_selection()` still has a production caller from `server.py:_handle_select_tasks()`.
- `GameController._assign_npc_tasks_by_rule_engine()` is the current production daytime NPC assignment path.
- `GameController._invoke_boss_pua_planning()` is the current production manager-planning path.
- `AgentService.all_agents_select_tasks()` is still called by `submit_task_selection()`, but the function now returns an empty compatibility payload and does not call `npc_select_tasks()` or `boss_plan_day()`.
- `_apply_agent_selections()` still receives that compatibility payload, but empty `patrol_rooms` means the old boss-plan application branch is skipped.
- Current compatibility-chain side effects:
  - API call: none
  - RNG consumption: none inside the compatibility shell itself
  - state mutation: `_agent_results` cache is assigned; current audited payload does not change boss patrol state
  - logs: none specific to this shell
  - latency: one extra async compatibility call frame, but no model call
- If the shell is removed in the future, likely observable changes are small but not literally zero:
  - `_agent_results` would stop being populated with the placeholder payload
  - `_apply_agent_selections()` would no longer be entered from this path
  - any debug inspection depending on `_agent_results["boss_plan"]["reason"] == "deprecated_by_boss_pua_plan"` would disappear
  - gameplay behavior should remain the same only after a behavior lock confirms those assumptions

## Event Legacy Chain Notes
- `trigger_event_v2()` is the formal production event entry from current `GameController`.
- Old event-template code is still production-reachable only as a fallback when skeleton selection fails.
- `test_module4.py` mainly validates the old template/event API directly; it is not a direct proof of the current v2 main path.

## Memory Deprecated API Notes
- `MemorySystem.add_memory()` has only test/manual callers in current repo.
- `MemorySystem.add_event_memory_for_witnesses()` has only test/manual callers in current repo.
- `MemorySystem.get_memories()` and `MemorySystem.build_npc_info_for_ai()` still have production callers in `GameController`.
- `MemorySystem.generate_event_summary()` still has a production caller in `GameController`.
- Repo-wide search found no `getattr(...)` / `hasattr(...)`-based indirect access for the explicitly audited deprecated memory methods.

## GameController Legacy Noise Inventory
- Task-selection old bridge: `all_agents_select_tasks()` compatibility shell plus `_agent_results` cache
- Event bridge: `trigger_event_v2()` fallback into old `StateManager.trigger_event()`
- Sync/async compatibility: old CLI path still uses old sync-style flow around `play.py`
- Old apply methods: `_apply_agent_selections()` remains in the controller even though the current payload is a shell
- Debug routes: scout/status/debug-seeding helpers still surface through controller-driven websocket routes

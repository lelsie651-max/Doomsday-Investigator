# Doomsday Investigator — Current State

## 1. Recovery Baseline
- Branch: `develop`
- Recovery code baseline: `d6b43f7 update the demo version`
- R2 baseline document commit: `3ac22e5 Create CURRENT_STATE.md`
- Current phase: `P0-4B — Legacy / Compatibility Runtime Audit`
- Purpose: this file is the required starting point for every future development round. It records current code facts plus product-confirmed baseline decisions, not future implementation plans.

## 2. Current Production Technical Structure
- Current production runtime chain is: `Godot -> WebSocket -> server.py -> GameController -> subsystems`.
- `server.py` is the actual network entry and message router.
- `backend/game_controller.py` is the orchestration center for the day loop, event flow, card flow, voting, night flow, pending states, and cross-system handoff.
- Main subsystems already separated from controller include `StateManager`, `TaskSystem`, `MovementSystem`, `MemorySystem`, `NightAllianceSystem`, `VoteSystem`, `EventSystem`, and AI-related services.
- Current production frontend is still Godot, but Godot UI is frozen during Recovery / P0 / P1. Near-term R&D direction is `Python core + Web dev/test UI` for validation and observability, then later parallel migration back into formal Godot presentation.

## 3. Current Production Game Loop
- Actual production entry is `new_game -> task selection -> working -> voting -> night -> next_day -> ending`.
- `GameController.new_game()` creates `GameState`, `StateManager`, and `MemorySystem`.
- Day start uses `StateManager` and task pool generation; player task selection is validated by `TaskSystem`.
- NPC daytime work is currently assigned by `GameController._assign_npc_tasks_by_rule_engine(max_tasks=5)`.
- Working phase is driven by movement + room/event dispatch + card/negotiation/scout/record handling inside `GameController`.
- Voting phase still calls AI-backed NPC vote reasoning through `AgentService.all_agents_vote(...)`.
- Night phase uses `enter_night_phase_v2()` and `NightAllianceSystem`; current production night flow is alliance / visitors / door response / night scout, not old night chat routing.
- Rules vs AI boundary today:
  - Mostly rule-driven: task validation, task pool, room movement, state advance, voting tally, night alliance calculation.
  - AI-assisted: Act text generation, negotiation text/decision, vote reasoning, selected night dialogue generation, recap/summary text.

## 4. Current Production Rules Baseline
- Formal game length remains `5 days`.
- Formal daily structure is `5 work slots / 5 work tasks per day`.
- Any `8-hour` wording in code, tests, comments, or helper defaults is historical drift and is not current baseline behavior.
- Current NPC daytime work in the formal main loop is assigned by rule engine, not by formal AI task selection.
- Canonical target NPC set for the product baseline is:
  - `laowang`
  - `xiaoli`
  - `ahua`
  - `dazhuang`
  - `hilda`
  - `boss`
- Current codebase has not completed the `hilda` production migration yet and still uses `zhoujie` in production data and logic.
- The old `xida` PoC placeholder in extended profiles has already been safely unified to `hilda` during `P0-2A`.
- `P0-2` is split into `P0-2A` and `P0-2B`.
- `P0-2A` completed the safe unification of the empty PoC placeholder `xida` to `hilda` inside `npc_extended_profiles.json`.
- Production runtime still uses `zhoujie` deliberately during `P0-2A`.
- Reason: the current `zhoujie` block contains deprecated Zhoujie-specific semantic content that must not be mechanically inherited by `hilda`.
- `P0-2B` must wait for product-confirmed required production-profile fields for `hilda` before formal migration can start.

## 5. AI Current State
- Production baseline model is now `deepseek-v4-flash`.
- Compatibility mode is explicit non-thinking via Chat Completions `extra_body={"thinking":{"type":"disabled"}}`.
- DeepSeek V4 Flash Chat Completions now route through a shared non-thinking helper, and the helper forcibly preserves `thinking={"type":"disabled"}` even if a caller passes conflicting `extra_body`.
- Business modules still depend directly on `DEEPSEEK_MODEL` and the shared helper; provider / logger / routing still do not form a formal abstraction layer.
- Timeout / prompt / logger / parse / fallback behavior is only partially centralized. `AIService` covers many paths, but provider usage is not yet fully converged.
- `base_url` remains `https://api.deepseek.com` and Chat Completions remains the active API surface.
- Provider / logger consolidation is still deferred to `P1`; this round only establishes the V4 Flash non-thinking compatibility baseline.

## 5A. Environment Baseline
- Canonical dependencies are defined by `requirements.txt`.
- Clean-environment verification passed in a repo-external temporary venv using Python `3.13.5`.
- Declared OpenAI SDK version for the reproducible baseline is `openai==2.15.0`.
- Clean-environment verification confirmed that `openai 2.15.0` supports the current helper's required `extra_body` capability.
- Developer-local environments may differ from the canonical baseline; the locally installed `openai 2.30.0` is drift, not the canonical requirement.

## 6. NPC Daily Context / Daily State PoC — EXPERIMENTAL / NOT PRODUCT-APPROVED
- `DailyStateService` must be treated as:
  - `EXPERIMENTAL POC`
  - `NOT PRODUCT-APPROVED`
  - `NOT IN MAIN GAME LOOP`
- Verified today:
  - NPC extended profile loading from `npc_extended_profiles.json`
  - external prompt/schema definition
  - AI JSON generation
  - fallback generation
  - returned structured payload
- Not formally designed or integrated:
  - persistent production state storage
  - run/day/npc lifecycle ownership
  - actor context trimming
  - relation to formal `GameState` / `models.DailyState`
  - relation to formal `MemorySystem`
  - connection to the production main loop
  - `leakable_details` lifecycle
  - `passive / observable / scoutable` trigger rules
  - release / consumed / dedup / repeated leak handling
  - connection to observation flow
  - connection to scout flow
  - connection to future clue systems
- Important boundary: do not prematurely define `inner_attitudes_toward_others` or `midterm_goal_state` as permanently system-private. The clearly access-controlled area today is `leakable_details`; final actor-context policy for the other fields is still pending separate architecture design.

## 7. Current Major Version Drift
- `zhoujie / hilda`: current running code still centers `zhoujie`, while product canonical target is `hilda`; the old `xida` PoC placeholder has already been unified to `hilda`.
- `5 slots / 8 hours`: formal production paths and time-baseline regression coverage now use 5 work slots; remaining 8-hour mentions are legacy or archived residue, not current production rules.
- `deepseek-v4-flash / provider consolidation`: model baseline is now aligned, but provider / logger usage is still not fully consolidated.
- Deprecated AI task selection path: NPC daytime work in production is rule-assigned, while old AI selection code still remains as compatibility/deprecated residue.
- Tests and protocol drift: some scripts and documents still reflect old assumptions, old routes, or old hour counts rather than the current production chain.
- Compatibility / dead-path residue still exists in cleanup targets and some older interfaces; file existence alone does not mean active production usage.
- `legacy != dead`: active fallback and compatibility shells still exist in current runtime and must not be removed without behavior locks.

## 7A. Legacy Runtime Audit
- Runtime legacy / compatibility audit is tracked in `docs/LEGACY_RUNTIME_AUDIT.md`.
- Current audit confirms that legacy-looking code splits across active production paths, active compatibility shells, active fallback paths, debug/manual-only routes, unreachable implementations, and archived references.
- Active fallback must not be treated as dead code.
- Compatibility shells should only be removed after behavior is locked and the formal flow decision is explicit.

## 8. Current Test Asset Status
- Keepable deterministic / regression assets:
  - `test_bystander_memory_regression.py`
- Statistical tests:
  - `test_module6.py`
- Debug scenario assets:
  - `test_scenario_matrix.py`
  - `docs/scenario_acceptance_v1.md`
  - `docs/debug_api_draft.md`
- Real AI manual tests:
  - `test_ai_pipeline.py`
  - `backend/test_daily_state_demo.py`
  - `backend/test_negotiation_behavior.py`
- Clearly drifted legacy scripts:
  - `test_module2.py`
  - `test_module3.py`
  - other older protocol/compatibility-oriented scripts should not be assumed to match the current main loop without revalidation.

## 9. Recovery Sequence
- `R1 — Project Recovery Audit`: completed
- `R2 — Current State Baseline`: completed
- `P0-1 — 5-slot time baseline unification`: completed
- `P0-2A — Hilda migration preflight`: completed
- `P0-2B — formal Hilda production migration`: pending product profile confirmation
- `P0-3 — DeepSeek V4 Flash compatibility baseline`: completed
- `P0-3.1 — DeepSeek Non-Thinking Invariant Closure`: completed
- `P0-4A — Environment Reproducibility Baseline`: completed
- `P0-4B — Legacy / Compatibility Runtime Audit`: completed
- `P0 — version / rules unification`
- `P1 — existing system consolidation`, including:
  - `GameController` behavior baseline
  - `GameController` modular extraction
  - AI provider / logger consolidation
  - legacy test and protocol asset cleanup
- After `P0 / P1`:
  - re-confirm final game flow
  - `NPC Daily Context Architecture`
  - `Simulation / Eval` automation infrastructure
  - new gameplay development
- No new formal gameplay should be added before `P0 / P1` are finished.

## 10. Architecture Debt — GameController
- `backend/game_controller.py` is currently over 7000 lines and carries cross-phase orchestration, pending state handling, AI handoff, and major gameplay flow control.
- This is a confirmed high-priority architecture debt.
- Large-scale rewrite is currently forbidden.
- Handling principles:
  1. `P0` first completes version / rules unification.
  2. `P1` first establishes behavior regression baselines for critical phase handoff.
  3. Under regression protection, extract `GameController` one functional domain at a time.
  4. Each round extracts only one independently reviewable module.
  5. One-shot rewrite of `GameController` is not allowed.
  6. Splitting work must not change current gameplay behavior.

## 11. Trae Working Rules
1. Read `CURRENT_STATE.md` before starting any new round.
2. Re-read the actual code relevant to the current task.
3. Do not modify based on memory or prior chat assumptions alone.
4. Each round should target one independently reviewable goal.
5. Each round prompt must explicitly define forbidden changes.
6. Run the tests requested for that round.
7. Report test results or sample results explicitly.
8. `develop` is the active R&D branch; `main` is not for direct development right now.
9. Do not call paid AI APIs without explicit authorization.
10. Do not invent or freeze product design decisions that product has not confirmed.

# NucleusVM: Full Plan and Research Findings

This is the complete plan this project was built from, including the
cross-language research it's based on. Written so a fresh session picking
this project up — possibly with no memory of the conversation that produced
it — has everything needed without depending on any external memory/plan
store. `README.md` and `PROGRESS.md` are shorter pointers into this file;
this is the source of truth for *why* things are designed the way they are.

## Context

Leopard (a sibling Python-hosted teaching-language project, in this same
`Programming_Tools/LANGUAGES/` directory) went through a multi-session
interpreter-performance journey: (1) tree-walker dispatch-cache fixes
(~1.7x), then (2) an extensive solution-code worst-offender review of its
Project Euler solutions — including several deliberately
non-reference-matching algorithm rewrites (e.g. one problem went from an
O(n⁴) brute force to O(n²) direct counting, ~450x) — landing Leopard's full
100-problem benchmark around **~800s total**. The owner wants STEPS and
FragBASIC (two more Python-hosted teaching languages, both used for the
same Project Euler exercise, both currently much slower — see the
per-language `LANGUAGE_LIMITATIONS.md`/solutions-review docs in each of
their own repos) brought to a similarly "OK, not great" tier, and asked
whether a **single shared bytecode VM** — written once in Python, reused
across languages via a per-language compiler front-end — could get there
more efficiently than optimizing each tree-walker separately, given how
much interpreter work would otherwise need repeating per language.

Research (3 parallel codebase-survey agents reading STEPS/FragBASIC/Leopard
source directly, then a validation pass) confirmed this is architecturally
sound, with FragBASIC-then-STEPS as the right build order. Leopard and BARE
(a fourth Python-hosted language in the same family) are **explicitly out
of scope** — mentioned only so the VM core isn't designed in a way that
would preclude them adopting it later.

**Scope/time honesty**: this is genuinely large — comparable to or bigger
than Leopard's own multi-session journey, since it's building a new
execution engine (not just tuning an existing one) for two languages.
Expect multiple sessions. The plan is phased specifically so there's a
real, independently-valuable, fully-shippable win (Phase 1, FragBASIC)
before any commitment to Phase 2 (STEPS).

## Key research findings

- **FragBASIC's biggest lever isn't dispatch overhead, it's call
  convention**: every SUB/FUNCTION call does `saved_vars =
  self.variables.copy()` — a full shallow copy of *every currently-live
  variable in the program*, not just params — before the call, and
  restores the whole dict after (confirmed directly:
  `FragBASIC/src/fragbasic_core/interpreter_functions.py:350,405` for SUB,
  similar for FUNCTION). Cost scales with total live-variable count, not
  call complexity. `FragBASIC/.../pe87.bas`'s recursive `merge_sort` over
  ~1.14M array elements pays this on every recursive call. This alone is
  likely FragBASIC's single largest available win, bigger in isolation
  than the general "VM vs tree-walker" argument.
- **FragBASIC's control flow is already flattened**: `visit_block` is an
  index-based `while i < len(statements)` loop over a flat statement list,
  not recursive-per-statement AST evaluation — already close to
  bytecode-shaped. Combined with zero GUI and the call-convention win
  above, this is why FragBASIC is the right Phase 1 target, not STEPS.
- **STEPS variable scoping is dynamic, not lexical, and this is pervasive
  (not an edge case)**: `push_scope()`
  (`STEPS/src/steps/environment.py:188-191`) parents every new call's
  scope on the **caller's current scope**, not a definition-time lexical
  scope — so STEPS variable names generally cannot be resolved to
  compile-time slots the way BARE/Leopard/FragBASIC's can. The VM's
  dynamic-scope opcode family (`LOAD_NAME`/`STORE_NAME_DYNAMIC`) is
  load-bearing for essentially all of STEPS's variable access, not just
  the documented undeclared-`set` leak quirk — size and de-risk Phase 2
  accordingly (see below).
- **A prior doc's claim that STEPS has "arbitrary-precision numbers" is
  wrong** — `STEPS/src/steps/types.py` confirms `StepsNumber.value: float`,
  plain Python float, no native bignum. Corroborated by STEPS solutions
  using hand-rolled `bignum_add`/`bignum_mul_small` helpers for
  large-number problems, which would be pointless if native bignum
  existed. Doesn't change the VM design (float-backed numbers are simple
  to handle) but is worth correcting anywhere else this claim appears in
  either project's docs.
- **Value unboxing is safe and is its own real win**, on top of the VM
  itself: STEPS's `StepsNumber`/`StepsText`/`StepsBoolean` wrap plain
  Python float/str/bool — recoverable via `type(x) is ...` (not
  `isinstance`, since `bool` is an `int` subclass — the same fix class as
  Leopard's own `isinstance`→`type() is` win, ~18% measured there).
  STEPS's `fixed` (immutability) flag already lives on `Scope`, not on the
  value, so unboxing doesn't lose it. **FragBASIC's `Variable(value,
  var_type)` needs one audit before unboxing**: confirm whether
  `var_type` tags like `'INTEGER'` vs `'SINGLE'` only affect display
  formatting (safe to drop, infer from Python int/float) or also affect
  arithmetic truncation/coercion (must be preserved as a real tag) — first
  task of Phase 1, not an afterthought.
- **Leopard has an existing explicit "no bytecode VM" decision** in its
  own `Leopard/dev-docs/IMPLEMENTATION_PLAN.md` ("teaching language,
  performance was never a design goal... non-goal for this pass") — an
  earlier-session decision under different assumptions, predating the
  STEPS/FragBASIC state described here. Not relevant to this plan (Leopard
  is out of scope), but if Leopard is ever pulled into a shared VM later,
  that doc should be updated explicitly rather than silently overridden.

## Architecture

**One shared VM core**: one bytecode chunk format, one dispatch loop, one
operand stack, one call-frame stack. `Frame = {locals: dict, parent:
Optional[Frame], caller: Optional[Frame], return_ip: int}` — `parent` is
generic enough for all four languages' scoping models: BARE (`parent`
always `None`), Leopard (depth ≤2), FragBASIC post-fix (`parent = None`,
all slots statically declared), STEPS (real chain, walked at runtime by
`LOAD_NAME`/`STORE_NAME_DYNAMIC`). `caller`/`return_ip` are separate,
VM-internal call-stack bookkeeping used by `CALL`/`RETURN`, independent of
whatever `parent` is doing for language-level scoping. The *per-language
compiler*, not the VM, decides which opcode family to emit for a given
variable reference — the same three-tier split CPython's own compiler
already uses (`LOAD_FAST` vs `LOAD_GLOBAL` vs `LOAD_NAME`), not a novel
design.

**Value representation**: unboxed native Python values on the operand
stack (float/str/bool/list/dict/None), using `type(x) is ...` as the type
tag. Builtins/native calls get a thin wrap/unwrap adapter at the
`CALL_NATIVE` boundary during transition, rather than rewriting every
existing builtin function's internals up front (defer that cleanup).

**Dispatch**: a dict keyed by `Op` enum member → bound handler method for
opcodes that only touch the stack/frame locals. Opcodes that need to move
the instruction pointer itself (jumps, `CALL`/`RETURN`, `HALT`,
`SAFETY_TICK`, `BEGIN_ATTEMPT`/`END_ATTEMPT`) are handled directly in
`run()`'s loop instead, since a handler called through the dict has no way
to affect the caller's `ip` variable. This mirrors the exact "cache the
resolved handler instead of re-deriving it per node" fix already proven
necessary in *every one* of the tree-walkers this VM replaces (Leopard,
STEPS, FragBASIC all independently found and fixed this same anti-pattern
before this project existed) — NucleusVM is built with that lesson already
applied, not left to be rediscovered.

### Opcode set

See `src/nucleus_vm/opcodes.py` for the authoritative enum and
`dev-docs/DESIGN.md` for the opcode table with implementation notes. The
opcode set as designed:

| Opcode | Notes |
|---|---|
| `LOAD_CONST`, `POP_TOP`, `DUP_TOP`, `SWAP` | stack hygiene, all languages |
| `LOAD_FAST` / `STORE_FAST` (slot idx) | resolved locals — BARE, Leopard, FragBASIC (post-fix) |
| `LOAD_GLOBAL` / `STORE_GLOBAL` (name) | module/top-level dict, all |
| `LOAD_NAME` (name) | dynamic chain-walk read — **STEPS only** |
| `STORE_NAME_DECL` (name) | always binds in current frame — STEPS `declare:`/param-bind |
| `STORE_NAME_DYNAMIC` (name) | walk chain, mutate first existing binding else create locally — STEPS plain `set` |
| `BINARY_ADD/SUB/MUL/DIV/IDIV/MOD/POW`, `UNARY_NEG/NOT` | all |
| `COMPARE_EQ/NE/LT/LE/GT/GE` | all |
| `JUMP`, `JUMP_IF_FALSE`, `JUMP_IF_TRUE` | if/while/for compile down to these directly, no dedicated loop opcode |
| `JUMP_IF_FALSE_OR_POP` / `JUMP_IF_TRUE_OR_POP` | CPython-style short-circuit and/or |
| `SAFETY_TICK` (counter slot) | reads current iteration-limit from mutable VM state each tick (STEPS's runtime-adjustable `set iteration limit to`); doubles as a free runaway-loop guard for all four |
| `BUILD_LIST` / `BUILD_TABLE` (count) | STEPS lists/tables, FragBASIC arrays |
| `INDEX_GET` / `INDEX_SET` | arrays/lists, all |
| `GET_ATTR` / `SET_ATTR` (name) | STEPS table fields; Leopard's non-GUI fallback (list `.add()`) before GUI dispatch, if Leopard ever adopts this |
| `CALL` (argcount) | proc/step/sub call; frame push/pop implicit |
| `RETURN` | replaces Python-exception-based returns (STEPS/Leopard/BARE all currently use exceptions here) — real perf win, not just cleanup |
| `CALL_NATIVE` (name, argcount) | the one generic builtin/file-I/O/CSV/serial/TUI hook |
| `BEGIN_ATTEMPT` / `END_ATTEMPT` (handler target) | **STEPS only**; thin compiler-inserted markers around a Python try/except in the VM loop — not a general exception-as-opcode mechanism, `attempt` isn't hot-loop code |
| `HALT` | program end |

Explicitly not included: any GUI-specific opcodes (out of scope, Leopard
only, and its existing `GET_ATTR`/`SET_ATTR`/`CALL` shape already covers
the general dispatch pattern if it's ever needed); a dedicated
`FOR_ITER`/iterator opcode (compile counted/while loops from existing
opcodes; design a `for-each` iterator opcode pair against a real
language's actual grammar when that compiler is being built, not
speculatively now).

## Phasing

**Phase 0 — generic VM core, no language front-end. DONE, see
`PROGRESS.md`.** Bytecode chunk format, dispatch loop, operand stack,
call-frame stack, disassembler — the resolved opcode family plus
`LOAD_NAME`/`STORE_NAME_DYNAMIC`. Validated with hand-assembled bytecode
(no compiler exists yet) rather than risking a core design flaw surfacing
only after a full compiler depends on it.

**Phase 1 — FragBASIC compiler + VM (largest phase, ships
independently).** Not started yet.
- Resolve the `INTEGER`/`SINGLE` tag question (see Key Findings) first.
- New AST→bytecode compiler consuming FragBASIC's existing `Node`/
  `NodeType` tree unchanged — lexer/parser untouched. Only
  `interpreter_core.py`, `interpreter_control.py`, `interpreter_functions.py`,
  `interpreter_expressions.py` get a compiler+VM alternative *added
  alongside* them.
- New compile-time symbol-resolution pass per SUB/FUNCTION (scan `DIM` +
  params to build the slot table) — genuinely new work, FragBASIC has
  never had real scopes.
- `GOSUB`/labels compile to plain `JUMP` with compile-time-resolved
  addresses, replacing the current linear runtime label search (free win,
  folds into the `JUMP` opcode, no dedicated label opcode needed).
- ~35 builtins route through `CALL_NATIVE`, wrapping the existing
  `interpreter_functions.py` implementations largely as-is.
- Keep the tree-walker in FragBASIC's codebase behind an
  engine-selection switch; don't delete it until Phase 1 is fully green.

**Phase 2 — STEPS compiler + VM, reusing Phase 0/1's core.** Not started.
Not just "wire a proven core to a new front-end" — Phase 1 only exercises
the *resolved*-slot opcode family. The *dynamic* `LOAD_NAME`/
`STORE_NAME_DYNAMIC` family (what STEPS actually needs for nearly all its
variable access) gets exercised by a real compiler for the first time
here, even though the opcodes themselves were implemented in Phase 0.
De-risk the same way as Phase 0: hand-build a small bytecode chunk
exercising nested dynamic-scope reads/mutations *before* wiring the full
STEPS compiler to it.
- `attempt`/`unsuccessful` as thin try/except markers (`BEGIN_ATTEMPT`/
  `END_ATTEMPT`, already implemented in the VM), not a general exception
  mechanism.
- **Preserve `is_recursive`'s exact semantics**
  (`STEPS/src/steps/environment.py:380`) — it counts *occurrences of the
  same step name in the call stack*, not overall depth. A generic `CALL`
  opcode must replicate this per-name-reentrancy check, or
  deep-but-non-recursive call chains could behave differently under the VM
  even at similar total depth. Write a targeted test for this
  specifically — the 100-solution regression diff may not exercise it.
- 56 builtins (incl. file/CSV/serial/TUI) through `CALL_NATIVE` unchanged.
- Multi-file `.building`/`floor` loading (`loader.py`) untouched — only
  the executed body per `.step` file changes; this is a clean seam.
- Expect this phase's win to be real but more modest than Phase 1's
  headline number — exception-based-return elimination + unboxing +
  dispatch/recursion removal all still apply, but the dynamic chain-walk
  cost itself is structural to STEPS's semantics and doesn't go away.

**Out of scope for this plan**: Leopard (GUI re-entrancy is a real,
harder, separate problem — Qt callbacks re-invoke interpreter execution
against persistent global state, needing a "resume VM at persistent
state" entry point this plan doesn't design) and BARE (simplest of the
four, no parent chain at all — the VM design doesn't preclude it, just
not requested).

## Protecting the existing languages while this work happens

This is genuinely large, experimental, multi-session work touching
languages that are currently working, verified, and (per each repo's own
git remote) potentially relied on outside this one project.

1. **New files, not in-place edits, until a phase is proven.** The
   compiler module and an engine-selection switch are *added* alongside
   `interpreter_core.py`/`interpreter.py` etc. — those existing files are
   never modified until their language's phase is fully verified. The
   tree-walker stays the default the entire time.
2. **Git branch isolation, per language repo.** All STEPS/FragBASIC-side
   integration work happens on a feature branch in *that language's own
   repo* — never on `main`/`master`. `main` stays exactly as it is,
   installable and working, until the owner explicitly reviews and merges.
   NucleusVM itself develops on its own `main` from the start since it has
   no prior working state to protect.
3. **The dual-run, byte-for-byte verification harness** (below) is a
   protection mechanism, not just a test — nothing is proposed for
   promotion to "default engine" without every one of that language's 100
   existing Euler solutions proving identical stdout first.
4. **Checkpoint commits at safe milestones**, not one long unreviewable
   branch — e.g. "Phase 0 core validated," "Phase 1 FragBASIC VM passing
   all 100 solutions on the feature branch" — so there's always a clean,
   inspectable point to stop, review, or revert to.
5. **Nothing here touches how the languages are currently installed/used**
   (e.g. STEPS's installed CLI/IDE, FragBASIC's editor plugin) unless and
   until the owner decides to merge a proven feature branch.

## Verification strategy

- Extend `PROJECT_EULER/euler_benchmark.py` (already exists, already runs
  both languages' 100-problem suites) with a dual-run mode: legacy
  tree-walker vs VM, **diffing stdout byte-for-byte**, not just the final
  numeric answer — output-order/formatting bugs would otherwise hide
  behind a coincidentally-correct final value. Keep this harness
  permanently as a regression net, not just a one-time migration gate.
- One `run_program(..., engine="vm"|"tree")` seam per language, so the
  other entry points beyond the CLI (STEPS has `steps_repl` and an IDE;
  FragBASIC has an editor plugin) don't each need individual updates when
  the default flips. Note: `steps_repl` executes statement-by-statement
  with persistent state across chunks — a smaller cousin of Leopard's
  re-entrancy problem; a Phase 2 design question, not a blocker.
- Use small subsets/synthetic stress scripts for iterative validation
  during development, not full 100-problem runs; reserve a full-suite
  benchmark for confirming each phase's real end-to-end win once it's
  believed done (matches the wider Project Euler project's own standing
  benchmark-methodology rule — long unattended full-suite runs are
  explicitly something the owner wants to avoid during iteration).
- Correctness gate before any phase is considered complete: all of that
  language's existing Project Euler solutions produce byte-identical
  stdout under the VM vs. the tree-walker.

## How this connects to the wider Project Euler cross-language project

STEPS and FragBASIC both live in this same `Programming_Tools/LANGUAGES/`
directory and are also used to write Project Euler solutions in a separate
sibling repo (`PROJECT_EULER/`, specifically `PROJECT_EULER/my-languages/
steps_euler/` and `PROJECT_EULER/my-languages/fragbasic_euler/`) as part of
a broader cross-language interpreter-performance teaching exercise. That
repo's `euler_benchmark.py` is the existing tool this plan's verification
strategy extends, and `PROJECT_EULER/dev-docs/INTERPRETER_DESIGNS.md` has
the fuller cross-language architecture survey this plan was built on top
of. NucleusVM itself has no dependency on that repo and doesn't need it
present to build/test — the connection is one-directional (NucleusVM feeds
into that project's benchmark once a phase is done), not the other way.

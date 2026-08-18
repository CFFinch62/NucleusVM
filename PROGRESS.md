# NucleusVM — Progress Log

Tracking status the way sibling projects (e.g. `STEPS/PROGRESS.md`) do —
read this first when picking this project back up, before `dev-docs/`.

## Where this came from, in one paragraph

Leopard (a sibling language project) went through a two-stage performance
journey: interpreter dispatch-cache fixes, then an extensive solution-code
worst-offender review, landing its full 100-problem Project Euler benchmark
around ~800s total. The owner wants STEPS and FragBASIC (two more
Python-hosted teaching languages, both currently much slower) brought to a
similarly "OK, not great" tier, and decided a **shared bytecode VM** — built
once here, reused by each language via its own compiler front-end — is a
better path than tuning each language's tree-walker separately. Full
rationale, research findings, and the phased plan are in
`dev-docs/PLAN.md` — **read that file before doing anything else**, it has
everything a fresh session needs that isn't obvious from the code alone.

## Status: Phase 0 complete

**Commit `96c7c15`, 2026-08-17, on `main`.** Built and tested the generic
VM core with no language compiler yet (validated via hand-assembled
bytecode, per the plan):

- `src/nucleus_vm/opcodes.py` — the full opcode set (see `dev-docs/PLAN.md`
  for the table with per-opcode rationale)
- `src/nucleus_vm/chunk.py` — bytecode chunk format (constants pool +
  instruction list)
- `src/nucleus_vm/vm.py` — the dispatch loop, operand stack, and call-frame
  stack. Implements the full "resolved" opcode family the plan scoped for
  Phase 0, **plus** `LOAD_NAME`/`STORE_NAME_DYNAMIC` (originally scoped for
  Phase 2/STEPS, but simple enough to build now — see `dev-docs/PLAN.md`'s
  note on this). `BEGIN_ATTEMPT`/`END_ATTEMPT` are also implemented (thin
  try/except markers), not just stubbed.
- `src/nucleus_vm/disassembler.py` — human-readable bytecode dump
- `tests/test_vm_core.py` — 6 passing tests: a range-sum loop (proves
  globals/arithmetic/comparison/jumps), recursive Fibonacci via real
  CALL/RETURN, a call chain 2000 frames deeper than Python's own default
  recursion limit (**confirms VM call depth is not bounded by Python's
  stack** — a real architectural benefit, directly verified, not just
  claimed), a native-call round trip, list build/index, and an
  undefined-global error case.

Run tests: `cd NucleusVM && source venv/bin/activate && pytest -v`

## Status: Phase 1 first vertical slice built, 2026-08-18

Read `dev-docs/PLAN.md`'s "Phase 1" section for the full task list — this
session did **not** finish Phase 1, it built a deliberately-scoped first
slice (see that session's plan, reconstructed below since plan files
aren't persisted in-repo).

1. ~~Audit `FragBASIC/src/fragbasic_core/variable.py`'s `Variable(value,
   var_type)` tags~~ **Done.** Result: `var_type` is *not* purely cosmetic
   (it gates the int-vs-float arithmetic branch in `+`/`-`/`*`,
   `interpreter_expressions.py:26,36,46`, and sigil-forced coercion on
   assignment, `interpreter_core.py:245-250`) — but it's fully redundant
   with the value's native Python type: `INTEGER`/`LONG` variables always
   hold a Python `int`, `SINGLE`/`DOUBLE` always hold a `float`. So
   NucleusVM's existing `type(x) is int` vs `type(x) is float` runtime
   tagging already reproduces what `var_type` encodes — no separate type
   tag needed in the compiled output.
2. **Done: first vertical slice of the AST→bytecode compiler**, in
   FragBASIC's own repo on branch `feature/nucleus-vm-compiler` (new files
   only — `interpreter_core.py`/`interpreter_functions.py`/etc. untouched),
   under `FragBASIC/src/fragbasic_core/vm_compiler/`
   (`compiler.py`/`symbols.py`/`natives.py`). Covers: scalars (global at
   top level, real `LOAD_FAST`/`STORE_FAST` locals inside SUB/FUNCTION —
   see the symbols.py note below for what "local" actually means here),
   arithmetic/comparison/logical operators, `IF`/`IF_ELSE`/`ELSEIF`,
   `FOR`/`NEXT` (with `STEP`), `WHILE`/`WEND`, `DIM` (scalar + 1D/2D/3D
   array, both legacy and typed forms), `PRINT`, `SUB`/`FUNCTION`/`CALL`
   via the VM's real `CALL`/`RETURN` frame chain, and the 12 builtins
   (`LEN`/`MID$`/`CHR$`/`ASC`/`VAL`/`INT`/`SQR`/`RND`/`RIGHT$`/`LEFT$`/
   `STR$`/`LOG`/`ABS`) that a survey of all 100 FragBASIC Project Euler
   solutions showed are the ones actually used. `GOSUB`/`SELECT CASE`/
   `DO`/`LOOP`/`DATA`/`READ`/`RESTORE`/`INPUT` are unimplemented on
   purpose (raise `NotImplementedError`) — none of the 100 solutions use
   them either. `run_source()` gained an `engine="tree"|"vm"` parameter
   (default `"tree"`, so nothing existing changes).
   - **A real bug this slice caught and fixed**: the first version of
     `symbols.py` only treated `DIM`'d names as SUB/FUNCTION locals. But
     the tree-walker's save/restore scoping (`interpreter_functions.py`'s
     `call_sub`/`call_function`) makes *any* scalar name assigned inside a
     body call-local, `DIM`'d or not — a bare `i = lo` is just as
     call-scoped as a `DIM`'d one. Missing this made `pe87.bas`'s
     recursive `merge_sort` SUB's undeclared loop counters (`i`/`j`/`k`/
     `mid`/`m`) compile as VM globals, so nested recursive calls clobbered
     each other's copies — caught by diffing VM output against the
     tree-walker's on a scaled-down copy of that exact solution (full-scale
     `pe87.bas` is too slow to iterate on directly — see below). Fixed by
     scanning for every scalar assignment target and `FOR` induction
     variable in the body, not just `DIM`s.
   - **Verified**: `pe01.bas` byte-identical between engines at full scale.
     `pe87.bas` (recursive SUB + 3 arrays + nested `WHILE`) is too slow to
     run start-to-finish under *either* engine within a session (both
     exceed 90s at the real 50,000,000 limit — not a VM-specific
     regression, confirmed by timing the tree-walker alone first) — verified
     instead on a scaled-down copy (`LIMIT = 100000`) that exercises the
     identical code paths, byte-identical between engines. 21 new tests in
     `FragBASIC/tests/test_vm_compiler.py` cover the slice's full feature
     list directly, including the recursion-depth fix (VM succeeds past
     depth 3000; the tree-walker errors around depth ~80-100, bounded by
     Python's own recursion limit since SUB/FUNCTION calls recurse through
     real Python function calls — see `dev-docs/PLAN.md`'s research notes).
     All 56 of FragBASIC's tests (35 existing + 21 new) pass.
   - **Not yet done**: a broader sweep across the full 100-solution corpus
     (beyond the two verification targets above) was attempted ad hoc this
     session with a 3s-per-file timeout and appeared to hang around
     `pe46`/`pe47` — confirmed afterward this is *not* a VM bug: `pe47`,
     `pe49`, `pe50`, `pe51`, `pe52` all individually exceed an 8s budget
     under the **tree-walker too** (checked directly). The corpus just has
     more multi-second-to-multi-minute problems than a quick ad hoc sweep
     budget accounted for — exactly why `dev-docs/PLAN.md`'s own
     verification strategy already says to avoid full-suite runs during
     iteration and reserve them for confirming a phase is done.
3. **Not started**: extending `PROJECT_EULER/euler_benchmark.py` with a
   proper dual-run mode (diffing stdout byte-for-byte across all 100
   solutions) — deferred until slice coverage is wide enough that most of
   the 100 actually compile (many still hit the `NotImplementedError`s
   above).

## Status: widening Phase 1 slice coverage, 2026-08-18 (later same day)

Picked back up per the "next concrete task" above. The earlier sweep-hang
concern was fully explained (multi-second-to-multi-minute problems, not a
bug — see above), so this pass went straight to a properly-paced sweep
(12s/file, real OS-level `timeout` per subprocess rather than
`signal.alarm`, which is what made the first attempt unreliable) to find
real coverage gaps instead of guessing:

- **Builtin usage re-survey** (the first session's grep undercounted —
  case-sensitive pattern missed lowercase source and required a directly-
  following paren): `INT` (114 uses), `VAL` (81), `LEN` (68), `STR$` (67),
  `MID$` (43), `CHR$` (36), `ASC` (20), `SQR` (9) were already covered.
  **New real gaps found**: `FIX` (9 uses), `SGN` (4), `STRING$` (2) —
  added to `natives.py`/`compiler.py`'s `BUILTIN_ARITY`, ported 1:1 from
  `interpreter_functions.py`'s `FIX`/`SGN`/`STRING$` branches.
- **`DATA`/`READ`/`RESTORE`** — the sweep's actual headline finding: 17 of
  the 100 solutions use `DATA`, 16 use `READ` (`INPUT` is still genuinely
  unused, 0 solutions). This was wrongly bucketed with `SELECT CASE`/
  `DO`/`LOOP` as "0 usage, skip" in the first session because the original
  corpus grep only checked for those three specific keywords, not
  `DATA`/`READ` separately. Implemented as a compile-time-folded constant
  pool (`compiler.py`'s `_fold_data_value`, mirroring
  `collect_definitions`'s exact DATA-collection scope: top-level only, not
  reachable from inside a SUB/FUNCTION body, same as the tree-walker) plus
  a runtime cursor (`\0data_pool`/`\0data_index` synthetic VM globals,
  `_read_next` native). `symbols.py` also needed a matching fix — `READ`
  targets inside a SUB/FUNCTION body are call-local exactly like
  `VAR_ASSIGN` targets are (same class of bug as the `merge_sort` one
  above, fixed proactively this time instead of by a failing test).
- **Verified**: all 4 of the DATA-using solutions checked directly
  (`pe11`, `pe13`, `pe18`, `pe22`) are byte-identical between engines. 4
  new targeted tests for `FIX`/`SGN`/`STRING$` and `DATA`/`READ`/`RESTORE`
  (including a negative-number `DATA` literal and an array `READ` target)
  — 25 of `test_vm_compiler.py`'s tests pass, 56 total in FragBASIC's
  suite.
- **Full-corpus sweep: complete.** 12s/file/engine budget, all 100
  solutions: **52 `MATCH`, 0 `DIFFER`**, 4 `VM_FAIL` (all stale —
  `pe11`/`pe13`/`pe18`/`pe22`, logged before the `DATA` fix landed mid-sweep;
  already independently re-verified passing, see above), 44 `TREE_FAIL`
  (exceeded the 12s budget under the tree-walker too — heavy problems, not
  a VM-specific slowdown; PROJECT_EULER's own euler_benchmark.py, not this
  ad hoc script, is the right tool for a patient confirming run per
  `dev-docs/PLAN.md`'s verification strategy). **Zero correctness
  divergences found anywhere in the corpus this pass.**

**Next concrete task**: of the 100 solutions, only the 44 slow ones remain
genuinely unverified (everything that completes within a reasonable budget
now matches). Either extend `PROJECT_EULER/euler_benchmark.py` with the
dual-run mode `dev-docs/PLAN.md` describes and let it run those 44
unattended for real confirmation, or keep widening coverage first.
`SELECT CASE` and `DO`/`LOOP` are confirmed genuinely unused by all 100
solutions (real corpus grep, not assumption) so they're low priority unless
requested for completeness; same for `INPUT`. `GOSUB`/`RETURN` still needs
the shared-VM-opcode work (`JUMP_SUB`/`RETURN_SUB` — jump-and-remember-
return-address *without* swapping to a new call frame, since `GOSUB`
shares its caller's exact variable scope) whenever it's picked up; still 0
corpus usage so it's not gating anything.

## Decision log

- **2026-08-17**: named "NucleusVM" (owner's choice); located at
  `Programming_Tools/LANGUAGES/NucleusVM/`, sibling to the language
  projects rather than nested inside any one of them, specifically so it
  can be a shared dependency (`pip install -e`) rather than vendored code.
- **2026-08-17**: FragBASIC chosen over STEPS as the Phase 1 (first)
  target — its control flow is already flattened/iterative (close to
  bytecode-shaped already), it has zero GUI complexity, and it has an
  unusually large, easy-to-demonstrate win available (the O(n)
  dict-copy-per-call bug, see `dev-docs/PLAN.md`). STEPS's dynamic scoping
  model is harder to get right and is deliberately saved for Phase 2, once
  the core VM is already proven on a simpler language.
- **2026-08-17**: Leopard and BARE are explicitly out of scope for this
  effort (not requested by the owner) — the VM design doesn't preclude
  either adopting it later, see `dev-docs/PLAN.md`.

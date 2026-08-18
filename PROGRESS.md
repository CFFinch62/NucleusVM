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

## Status: performance investigation and fix, 2026-08-18 (same day, later still)

**The owner's actual goal for this whole project is performance — FragBASIC
is explicitly the least important of the languages this VM is for and was
called out as disposable if it doesn't deliver real gains.** Prompted by a
direct question ("did this help performance by any real measure?"), this
pass actually measured instead of assuming, found the honest answer was
briefly **no**, then fixed the real, root cause — a change to the shared
VM core, not just the FragBASIC compiler, so it benefits every future
consuming language (STEPS included), not just this one.

**First measurement (before this pass's fixes) — mixed, and net negative
for the common case**:
- Recursive `fib(24)` (~150k calls, call-heavy): VM already **34% faster**
  (2.10s vs tree's 3.18s) — the call-frame/no-Python-recursion win was
  real from the start.
- Tight arithmetic/comparison loop, 2M iterations, no calls (far more
  representative of what a Project Euler solution actually looks like):
  VM was **60% slower** (42.57s vs tree's 26.62s).
- Scaled `pe87.bas` (arrays + recursion + comparisons): VM slower
  (4.25s vs tree's 3.46s).

**Root-caused via `cProfile`, not guessing**: two real, separate causes,
found by profiling the loop case directly.
1. **Compiler-level**: FragBASIC's classic-BASIC `-1`/`0` comparison/
   logical-op convention (not Python `True`/`False`) was routed through
   `CALL_NATIVE` *unconditionally*, even when a comparison only ever fed a
   branch condition — the overwhelmingly common case. Fixed:
   `compiler.py`'s new `_compile_condition` compiles a comparison used
   only for its truthiness (an `IF`/`WHILE` condition, or nested inside
   `AND`/`OR`/`NOT`) via NucleusVM's raw `COMPARE_*` opcodes instead —
   safe because `JUMP_IF_FALSE`/`AND`/`OR`/`NOT`'s own truthiness test
   (`bool(x)`/`_to_single(x) != 0`) agrees for a Python bool or a BASIC
   -1/0 alike; the exact `-1`/`0` representation is only materialized when
   a comparison's result is actually stored, printed, or otherwise
   escapes as a real value. Also resolved a FOR loop's `STEP` sign at
   compile time when it's a literal (or the default, implicit `+1`) rather
   than calling a native `_for_should_exit` helper every single iteration
   — covers the large majority of real loops. **Impact alone: modest**
   (42.57s → 39.22s, ~8%) — not the main story.
2. **Shared VM core**: profiling showed `vm.py`'s own dispatch loop was
   **38% of total runtime** on its own, dominant over every native call
   combined. Two compounding causes, both fixed in `vm.py`/`opcodes.py`:
   - `Op` was a plain `Enum` — hashing an Enum member (needed for every
     single `dispatch.get(op)` dict lookup) measurably costs more than
     hashing a plain int in CPython. Changed to `IntEnum` (5.96M `__hash__`
     calls on a 300k-iteration profiled run *disappeared* from the
     profile entirely). Alone: loop 39.22s → 31.92s; `fib(24)` 2.10s →
     1.63s.
   - `run()`'s main loop checked ~10 sequential `if op == Op.X` cases for
     ip-affecting instructions (jumps, `CALL`/`RETURN`, `HALT`, ...)
     *before* falling through to the dict dispatch — so every single
     instruction paid that cost regardless of which kind it was, even
     though the dict-dispatched family (loads/stores/arithmetic/
     comparisons/`CALL_NATIVE`/...) is the large majority of instructions
     in any real program. Reordered: try the dict first (now a cheap
     int-hash lookup thanks to the `IntEnum` change), fall through to the
     ip-affecting if-chain only on a miss. Verified no opcode is covered
     by both paths or by neither (`set` check against all `Op` members).
     Alone (combined with the `IntEnum` change already in place): loop
     31.92s → **15.46s**; `fib(24)` 1.63s → **0.89s**.

**Final numbers, same benchmarks, tree-walker unchanged throughout**:

| Workload | tree-walker | VM (before this pass) | VM (after) |
|---|---|---|---|
| `fib(24)`, call-heavy | 3.30s | 2.10s (34% faster) | **0.89s (3.7x faster)** |
| 2M-iteration arithmetic/comparison loop | 26.89s | 42.57s (60% slower) | **15.46s (42% faster)** |

**Correctness re-verified after the core VM surgery** (this touched
`vm.py`'s hot dispatch loop, not just the FragBASIC compiler, so this
mattered more than usual): full 100-solution corpus sweep re-run —
**56 `MATCH`, 0 `DIFFER`, 0 `VM_FAIL`** (even better than the pre-surgery
sweep, since the earlier run's 4 stale `DATA`-related failures are now
gone too). All 60 of FragBASIC's own tests and all 6 of NucleusVM's own
tests still pass.

**Bottom line for the owner's actual question**: yes, NucleusVM now
delivers real, measured, verified performance gains on both the call-heavy
and loop-heavy shapes of code Project Euler solutions actually take — but
only after this profiling pass; the first, uninvestigated answer would
have been the wrong one to act on (or to report as evidence the project's
premise was working). The `IntEnum` + dispatch-reorder fixes are core VM
changes, so **STEPS inherits both of these for free** whenever Phase 2
starts — they aren't FragBASIC-specific work that would need repeating.

## Status: closed the MOD/\/AND/OR native-call gap, 2026-08-18 (same day, later still)

The previous status update flagged one remaining known gap: `MOD`/`\`
(truncate-both-operands-first) and `AND`/`OR` (must stay eager — no
short-circuit) still routed through `CALL_NATIVE`, and closing it would
need new shared VM opcodes. Asked to close it, so: two new opcodes added
to `opcodes.py`/`vm.py` (both dispatch-table-eligible, no `ip` handling
needed) and documented in `dev-docs/DESIGN.md`'s opcode table:

- **`TO_INT`**: `int(x)` — a generic cast opcode, not BASIC-specific
  (plenty of languages have C-style truncating integer division). Lets
  `\`/`MOD` compile as `TO_INT`, `TO_INT`, raw `BINARY_IDIV`/`BINARY_MOD`
  instead of a native wrapper — the zero-check ("division by zero") was
  already built into those raw opcodes, so nothing was lost by dropping
  the native.
- **`LOGICAL_AND`/`LOGICAL_OR`**: eager (non-short-circuit) truthiness
  combination of two *already-evaluated* operands, returning a Python
  `bool` — explicitly distinct from the short-circuit and/or
  `JUMP_IF_*_OR_POP` already provides (which never evaluates the second
  operand at all). A consuming language needing BASIC's `-1`/`0`
  convention converts the result itself: `UNARY_NEG` on a bool already
  gives exactly `-1`/`0` for free (`-True == -1`), no third opcode needed.

Checked real usage before deciding what to fix: `AND` (53 files), `OR`
(21), `MOD` (50), `\` (63) vs. `XOR`/`EQV`/`IMP` combined in 1 file — so
those three stayed on the `CALL_NATIVE` path (`natives.py`'s now-dead
`_idiv`/`_mod`/`_logical_and`/`_logical_or`/`_logical_not` were deleted,
not left as unreachable code). In FragBASIC's compiler,
`_compile_condition` (added last pass for comparisons used only as branch
tests) now also compiles `AND`/`OR`/`NOT` via the raw opcodes when only
truthiness is needed, with `_compile_expr`'s general-value-context path
using the same raw opcodes plus a trailing `UNARY_NEG` when the exact
`-1`/`0` is actually observable (stored, printed, or otherwise escapes).

**Result**: loop benchmark 15.46s → **14.63s** (a further ~5%, on top of
the previous pass's much larger dispatch-loop fix — now **47% faster**
than the tree-walker's 27.77s, up from 42%). `fib(24)` essentially
unchanged (0.89s → 0.96s, within noise — expected, that benchmark barely
uses `MOD`/`AND`/`OR`). Directly verified the trickiest case by hand
(`AND`/`OR`/`NOT` used as a stored/printed *value*, not just a branch
condition, including the classic `total = total + (x > 5)` arithmetic
idiom) — byte-identical against the tree-walker. Full 100-solution corpus
re-swept a third time: **56 `MATCH`, 0 `DIFFER`, 0 `VM_FAIL`** — identical
to the post-dispatch-fix sweep, confirming zero regressions from this
change too. New unit tests for `TO_INT`/`LOGICAL_AND`/`LOGICAL_OR` in
NucleusVM's own `tests/test_vm_core.py` (9 tests now, up from 6).

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
corpus usage so it's not gating anything. No other known performance gaps
flagged as of this update — `+`/`^`/`XOR`/`EQV`/`IMP` remain on
`CALL_NATIVE` but are all either genuinely polymorphic (`+`) or rare
enough in the corpus (the rest) that a dedicated opcode isn't obviously
justified without more profiling evidence than exists yet.

## Status: Phase 2 (STEPS) first vertical slice, 2026-08-18 (same day, still)

FragBASIC's slice had done its job: correctness and real performance gains
verified, premise validated. Moved to STEPS per `dev-docs/PLAN.md`'s own
plan — chosen specifically because its dynamic scoping (each call's scope
parents on the *caller's live scope*, not its definition site) is the one
real architectural risk FragBASIC's static/resolved-slot scoping never
touched. Three parallel research passes against STEPS' actual source and
its own 100-problem Project Euler corpus (`PROJECT_EULER/my-languages/
steps_euler/`) grounded a scoped plan before any code was written — full
findings in the session's plan file; headline ones below.

**A real gap this research caught before writing any compiler code**:
`vm.py`'s `CALL` handler hardcoded `parent=None` on every new `Frame` —
never exercised by a real dynamically-scoped compiler before now, so it
went uncaught since Phase 0. Fixed: `parent=self.frame` (the calling
frame, at `CALL` time) — exactly the re-parenting STEPS' own
`push_scope()` does. Verified safe for FragBASIC (full suite + 100-
solution corpus re-sweep, 56 matches, 0 divergences, identical to before).
De-risked properly, mirroring Phase 0's own methodology and the plan's
explicit instruction for this phase: four new hand-assembled bytecode
tests in `tests/test_vm_core.py` (no compiler involved) proving the exact
dynamic-scoping patterns a real compiler would need — reading an outer
frame's variable through two nested calls, a bare dynamic store mutating
an outer frame's binding in place (STEPS' "leak" pattern), a declared name
shadowing without leaking back — all before writing STEPS compiler code.

**A genuinely pleasant surprise once that fix landed**: NucleusVM's
existing `LOAD_NAME`/`STORE_NAME_DECL`/`STORE_NAME_DYNAMIC` semantics —
designed in Phase 0 from written research, never exercised by a real
compiler — matched STEPS' actual `Scope.get`/`declare_variable`/bare-`set`
behavior almost exactly, with zero redesign needed. Better still, STEPS
turned out to need *less* compiler machinery than FragBASIC, not more:
its arithmetic is strictly numeric (no polymorphic `+` — text concat is
a separate `added to` operator), comparisons already return a plain
Python-compatible bool (not FragBASIC's `-1`/`0` convention), and `and`/
`or`/`not` are eager with truthiness matching Python's own `bool(x)`
exactly — so almost every operator compiles to a raw NucleusVM opcode
directly, no `CALL_NATIVE` wrapper at all (unlike FragBASIC, where that
wrapping was the whole first-pass performance problem). STEPS statement
bodies are also genuinely nested (real child-list AST fields), unlike
FragBASIC's flat sibling-scanned FOR/NEXT — no structural pairing pass
needed either. Net effect: the STEPS compiler slice
(`STEPS/src/steps/vm_compiler/{compiler.py,natives.py}`, new files only,
on branch `feature/nucleus-vm-compiler`) is architecturally simpler than
FragBASIC's despite STEPS itself having a much larger AST (~50 dataclass
node types vs. a handful of `NodeType` values).

**Two real design decisions, not obvious in advance**:
- Top-level `building.body` needs an active call frame too —
  `LOAD_NAME`/`STORE_NAME_DYNAMIC` both require one, but `VM.run()` starts
  with `self.frame = None`. STEPS has no "globals" tier distinct from its
  root `Scope` — top level is just the outermost link in the same dynamic
  chain a step call extends. Fixed by compiling the whole program so the
  first instruction is a zero-arg `CALL` to the building's own body (ending
  in `RETURN`), giving it a real frame before any dynamic-scope opcode runs.
- `environment.steps` (populated by the existing, untouched `Loader`)
  holds the *entire* loaded stdlib, not just what a given program actually
  uses — compiling all of it unconditionally both wastes work and fails
  outright the moment any unreachable stdlib step touches an unsupported
  construct (hit immediately on the very first test: an unrelated stdlib
  step used `split by`, which wasn't even in scope yet, and broke
  compilation of a program that never called it). Fixed with reachability-
  driven, on-demand compilation: a worklist seeded by `building.body`,
  growing as `CallStatement`s to not-yet-compiled steps are discovered
  during compilation, draining until empty — only what's actually
  reachable ever gets compiled.

**Scope, set by real corpus usage** (100-problem STEPS Euler corpus,
corrected from an earlier "104" estimate): `repeat while` is the
overwhelmingly dominant loop (99/100 problems, 530 occurrences) and needs
no scope push at all — `if`/`otherwise`/`otherwise if`; `exit`; `return`;
`call` for steps/risers/the 11 actually-used builtins (of 56 registered —
`create_list`/`characters`/`slice`/`sqrt`/`index_of`/`read_file`/
`replace`/`list_sum`/`sqr`/`pow`/`log10`/`log`); lists (literals,
indexing, `add`/`remove`); arithmetic/comparison/boolean operators; `as
number`/`as text`/`as boolean` (647 combined occurrences — higher than
any registry builtin); `length of` (180); `added to`; `split by` (13),
`character at` (20), `contains`/`is in` (1/3) — added once corpus grep
showed real usage, on top of the pre-planned scope; display — all in.
**Explicitly deferred, each with the evidence behind it**: `attempt`/
`unsuccessful` (0 corpus usage, plus needs a real exception-unwind design
this VM has no primitive for); tables (0 usage); `repeat for each` (1
use — needs a lightweight non-`CALL` scope-push primitive that doesn't
exist yet, a real design question worth its own checkpoint); `repeat <N>
times` (3 uses); `fixed` type-locking (0 *real* usage — the only 8 corpus
hits are the English word inside `note:` comments, confirmed by reading
every occurrence); the 45 unused builtins; the REPL (`steps_repl` keeps
one live `Environment` across an unbounded number of future input chunks —
a fundamentally different, not-yet-compilable model, unrelated to this
slice's scope).

**Verified**: `problem_01` matched on the very first end-to-end run — no
iteration needed, a strong signal the dynamic-scoping architecture was
right from the start (unlike FragBASIC's session, which caught a real
symbol-resolution bug on its first recursive-SUB test). Full 100-problem
corpus sweep (12s/problem/engine budget, same methodology already proven
for FragBASIC): **55 `MATCH`, 0 `DIFFER`**, 1 `VM_FAIL` (`problem_22`,
the deliberately-deferred `repeat for each` — expected, not a bug), 44
`TREE_FAIL` (exceeded the budget under the tree-walker too — heavy
problems, not VM-specific, same pattern as FragBASIC's own sweep). Zero
correctness divergences found anywhere. 13 new tests in STEPS' own
`tests/unit/test_vm_compiler.py` (mirroring FragBASIC's `test_vm_compiler.py`
style) cover this slice's constructs directly, including — deliberately,
as the single most important test this phase produces — a step whose bare
`set` mutates a variable that only exists in its *caller's* scope,
confirmed byte-identical against the tree-walker, not just at the raw
opcode level. All 450 of STEPS' own tests (437 existing + 13 new) and all
12 of NucleusVM's own tests pass throughout.

**Next concrete task**: same shape as FragBASIC's own next step — either
extend `PROJECT_EULER/euler_benchmark.py`'s dual-run mode to also cover
STEPS' 44 slow problems for a real patient confirmation, or keep widening
coverage (`repeat for each`'s lightweight scope-push design is the most
architecturally interesting remaining gap — likely wants its own
checkpoint rather than folding in casually). No STEPS performance
measurement has been done yet — worth doing once coverage is wide enough
to be representative, the same way FragBASIC's initial "is this actually
faster" question turned out to matter more than assumed.

## Status: STEPS performance measured, 2026-08-18 (same day, still)

Same two benchmark shapes used for FragBASIC, for a direct comparison:

| Workload | tree-walker | VM |
|---|---|---|
| Recursive `fib(24)`, call-heavy | 4.04s | **1.29s — 3.1x faster** |
| 2M-iteration `repeat while` loop, `modulo`/comparisons, loop-heavy | 22.92s | **12.44s — 46% faster** |

Unlike FragBASIC, this worked well **on the first pass** — no separate
optimization investigation was needed. Profiling confirmed why: this
slice's arithmetic/comparisons/booleans already compile to raw NucleusVM
opcodes with no `CALL_NATIVE` wrapper at all (see the compiler's own
status entry above — STEPS needed *less* compiler machinery than
FragBASIC, not more), so it never had FragBASIC's original problem
(native-call overhead dominating hot loops). It also inherits the
`IntEnum`/dispatch-loop-reorder core fixes from FragBASIC's investigation
for free, as expected going in.

One further attempt, reported honestly as a negative result rather than
omitted: profiling flagged `_op_load_name` doing two dict lookups per
frame level (`if arg in node.locals: node.locals[arg]`) where a
try/except would do one. Rewrote it, reran the loop benchmark three times
— no measurable change (12.27s → 12.30s, within noise). For top-level
code the lookup already succeeds on the very first try either way, so
there was no real redundant-lookup cost to remove in this benchmark's
shape. Reverted rather than keep the added complexity unjustified; worth
revisiting if a future benchmark actually exercises deep dynamic-scope
chains where the miss-then-walk path is hot.

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

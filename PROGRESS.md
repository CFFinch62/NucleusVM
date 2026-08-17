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

## Next: Phase 1 (FragBASIC compiler + VM)

Read `dev-docs/PLAN.md`'s "Phase 1" section for the full task list. First
concrete task, in order:

1. **Audit `FragBASIC/src/fragbasic_core/variable.py`'s `Variable(value,
   var_type)` tags** (`'INTEGER'` vs `'SINGLE'` etc.) — confirm whether they
   only affect display formatting (safe to drop when unboxing to plain
   Python int/float) or also affect arithmetic truncation/coercion (must be
   preserved as a real tag somewhere in the compiled output). This decision
   gates the value-representation design for the whole FragBASIC compiler,
   so do it first, not as an afterthought.
2. New AST→bytecode compiler module in FragBASIC's own repo, on a feature
   branch, added *alongside* the existing tree-walker files — never editing
   `interpreter_core.py`/`interpreter_functions.py`/etc. in place until the
   new engine is fully verified. See `dev-docs/PLAN.md`'s "Protecting the
   existing languages" section for exactly why and how.
3. Extend `PROJECT_EULER/euler_benchmark.py` with a dual-run mode (old
   tree-walker vs. new VM, diffing stdout byte-for-byte across all 100
   FragBASIC Euler solutions) before considering Phase 1 done.

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

# NucleusVM Design

## Goals

A single, generic bytecode VM core, reusable across multiple Python-hosted
teaching languages, each of which currently pays the cost of tree-walking
its own AST directly. The VM itself must stay language-agnostic — all
language-specific behavior (scoping rules, builtin functions, syntax) lives
in each consuming language's own AST-to-bytecode compiler, not in this repo.

## Architecture

**Stack machine**: bytecode instructions push/pop values from an operand
stack, rather than an AST-to-register model — simpler to compile to, and
matches CPython's own bytecode design philosophy.

**Value representation**: unboxed native Python values (`float`, `str`,
`bool`, `list`, `dict`, `None`) on the operand stack, tagged by `type(x) is
...` at runtime rather than a boxed wrapper object per value. This avoids
per-operation value allocation, a real, separately-measured cost in more
than one of the languages this VM is meant to replace.

**Frames**: `Frame = {locals: dict[str, Any], parent: Optional[Frame]}`.
Deliberately generic — different consuming languages have different
scoping models (no parent chain at all; a fixed two-level module+call-frame
split; a real, dynamically-parented scope chain), and `parent` being
optional/chainable accommodates all of them. The VM's job is just to walk
`parent` links when an opcode asks it to — *which* opcode a given language's
compiler emits for a given variable reference (resolved-slot vs.
dynamic-name-lookup) is entirely a compile-time decision made by that
language's own compiler, not something the VM decides.

**Native calls**: builtins, file I/O, and any other host-effectful
operation are never opcodes — they're invoked through one generic
`CALL_NATIVE(name, argcount)` opcode that looks up a name in an
injectable native-function table and calls it with `argcount` values
popped off the stack. Each consuming language supplies its own native
table; NucleusVM never needs to know what's in it.

## Opcode set

| Opcode | Operands | Stack effect | Notes |
|---|---|---|---|
| `LOAD_CONST` | const idx | `→ v` | |
| `POP_TOP` | — | `v →` | |
| `DUP_TOP` | — | `v → v, v` | |
| `SWAP` | — | `a, b → b, a` | |
| `LOAD_FAST` | slot idx | `→ v` | resolved local, current frame only |
| `STORE_FAST` | slot idx | `v →` | |
| `LOAD_GLOBAL` | name | `→ v` | top-level/module frame |
| `STORE_GLOBAL` | name | `v →` | |
| `LOAD_NAME` | name | `→ v` | walk `parent` chain from current frame, read first binding found |
| `STORE_NAME_DECL` | name | `v →` | always binds in the *current* frame, no chain walk |
| `STORE_NAME_DYNAMIC` | name | `v →` | walk `parent` chain looking for an existing binding to mutate; create in current frame only if none found anywhere up the chain |
| `BINARY_ADD` / `SUB` / `MUL` / `DIV` / `IDIV` / `MOD` / `POW` | — | `a, b → r` | |
| `UNARY_NEG` / `UNARY_NOT` | — | `a → r` | |
| `COMPARE_EQ` / `NE` / `LT` / `LE` / `GT` / `GE` | — | `a, b → bool` | |
| `JUMP` | addr | — | unconditional |
| `JUMP_IF_FALSE` / `JUMP_IF_TRUE` | addr | `v →` | pops, conditional |
| `JUMP_IF_FALSE_OR_POP` / `JUMP_IF_TRUE_OR_POP` | addr | branch-dependent | CPython-style short-circuit and/or: jumps *without* popping if the condition matches, pops and falls through otherwise |
| `SAFETY_TICK` | counter slot | — | increments a VM-state counter, traps (raises) if it exceeds the VM's *current* iteration-limit field; a runaway-loop guard, checked once per loop iteration by compiler convention, not enforced by the VM's own loop structure |
| `BUILD_LIST` | count | `v1..vN → list` | |
| `BUILD_TABLE` | count | `k1,v1..kN,vN → dict` | |
| `INDEX_GET` | — | `obj, idx → v` | |
| `INDEX_SET` | — | `obj, idx, v →` | |
| `GET_ATTR` | name | `obj → v` | |
| `SET_ATTR` | name | `obj, v →` | |
| `CALL` | argcount | `callee, a1..aN → ret` | user-defined function/proc call; frame push/pop implicit |
| `RETURN` | — | `v →` | unwinds the current frame, leaves `v` for the caller |
| `CALL_NATIVE` | name, argcount | `a1..aN → ret` | the one generic native/builtin escape hatch |
| `BEGIN_ATTEMPT` | handler addr | — | pushes a Python-level try/except marker in the VM loop |
| `END_ATTEMPT` | — | — | pops the marker |
| `HALT` | — | — | stops the VM |

Not included: a dedicated loop/iterator opcode (`FOR_ITER`-style) — counted
and conditional loops compile from `JUMP`/`JUMP_IF_FALSE`/comparison/
increment directly. If a consuming language needs a `for-each-over-a-
collection` construct, design its opcode(s) when that language's compiler
is actually being built, against its real semantics, rather than guessing
the shape here.

Also not included (by design, out of scope for a generic core): any
GUI/graphics-specific opcodes. A language with GUI needs (e.g. property
get/set and method-call dispatch on live widget objects) can build that as
its own small set of additional opcodes on top of this core — `GET_ATTR`/
`SET_ATTR`/`CALL` already cover the general shape (attribute access, method
call); a GUI-specific opcode would only be needed if a language's escape
hatch requires dispatch logic beyond what those three already express.

## What's intentionally *not* decided here

Everything about how a specific language maps its own AST onto this opcode
set — including which of `LOAD_FAST`/`LOAD_GLOBAL`/`LOAD_NAME` a given
variable reference compiles to — is a per-language compiler decision, made
in that language's own repo, informed by that language's own scoping rules.
This file describes the VM's capabilities, not any one language's use of
them.

"""NucleusVM's core execution engine: dispatch loop, operand stack, call
frames. See dev-docs/DESIGN.md for the opcode set and the reasoning behind
each design choice (unboxed values, dict-based frames, dict-dispatch loop).

Truthiness convention: JUMP_IF_FALSE/JUMP_IF_TRUE/JUMP_IF_*_OR_POP use
Python's own bool() semantics (None/False/0/""/[]/{} are falsy). A
consuming language whose truthiness rules differ (e.g. BARE, where only
False and None are falsy) is responsible for compiling its own conditions
into a genuine boolean (via COMPARE_*, or an explicit "is not None"-style
check) before emitting a JUMP_IF_* — the VM does not special-case any one
language's truthiness rules.

Function calls do NOT use Python's own call stack. CALL/RETURN swap an
explicit Frame chain within run()'s single, non-recursive while loop, so a
consuming language's own call/recursion depth is bounded by available
memory, not by Python's (comparatively shallow) recursion limit — a real,
architectural improvement over each of the tree-walkers this VM is meant to
replace, not just a side effect of the rewrite.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .chunk import Chunk
from .opcodes import Op


class NucleusRuntimeError(Exception):
    """Any VM-level runtime error: bad opcode, undefined name, stack
    underflow, native-call failure, iteration-limit exceeded, etc."""


@dataclass
class Frame:
    """One call's local variable storage.

    `parent` is the *language-level* scoping chain, walked by LOAD_NAME/
    STORE_NAME_DYNAMIC — what it's set to on a CALL is a per-language
    compiler decision (None for an isolated-scope language; the module
    frame for a fixed two-level language; the calling frame for a fully
    dynamic-scoping language), never decided by the VM itself.

    `caller`/`return_ip` are separate, VM-internal call-stack bookkeeping
    (which frame and instruction to resume once this one RETURNs) — always
    set on every CALL regardless of what `parent` is doing, since restoring
    the right caller is not a scoping decision.
    """

    locals: dict[Any, Any] = field(default_factory=dict)
    parent: Optional["Frame"] = None
    caller: Optional["Frame"] = None
    return_ip: int = 0


class VM:
    def __init__(
        self,
        natives: Optional[dict[str, Callable[..., Any]]] = None,
        iteration_limit: int = 10_000_000,
    ):
        self.natives: dict[str, Callable[..., Any]] = natives or {}
        self.iteration_limit = iteration_limit

        self.stack: list[Any] = []
        self.globals: dict[str, Any] = {}
        self.frame: Optional[Frame] = None
        self._constants: list[Any] = []
        self._safety_counters: dict[Any, int] = {}
        self._attempt_stack: list[tuple[int, int]] = []

        # Opcodes that only push/pop values or touch frame-local state go
        # through this dispatch table (dict-keyed on the Op enum member —
        # the same "cache the handler, don't re-derive it per instruction"
        # fix already proven necessary in every one of the tree-walkers
        # this VM replaces; Op is an IntEnum specifically so this lookup
        # hashes as a plain int rather than paying Enum's slower default
        # __hash__ — measured as the single largest chunk of run()'s own
        # overhead on a comparison/arithmetic-heavy loop before this
        # change). Opcodes that need to move `ip` itself (jumps, CALL/
        # RETURN, HALT, SAFETY_TICK, BEGIN/END_ATTEMPT) are handled
        # directly in run()'s loop instead, since a handler called through
        # this table has no way to affect the caller's `ip` variable —
        # run() tries this dict first and only falls through to that
        # explicit if-chain on a miss, since the dict covers the large
        # majority of opcodes in any real program and an IntEnum-keyed
        # dict lookup beats paying up to ~10 sequential equality checks on
        # every single instruction regardless of which kind it is.
        self._dispatch: dict[Op, Callable[[Any], None]] = {
            Op.LOAD_CONST: self._op_load_const,
            Op.POP_TOP: self._op_pop_top,
            Op.DUP_TOP: self._op_dup_top,
            Op.SWAP: self._op_swap,
            Op.LOAD_FAST: self._op_load_fast,
            Op.STORE_FAST: self._op_store_fast,
            Op.LOAD_GLOBAL: self._op_load_global,
            Op.STORE_GLOBAL: self._op_store_global,
            Op.LOAD_NAME: self._op_load_name,
            Op.STORE_NAME_DECL: self._op_store_name_decl,
            Op.STORE_NAME_DYNAMIC: self._op_store_name_dynamic,
            Op.BINARY_ADD: self._op_binary_add,
            Op.BINARY_SUB: self._op_binary_sub,
            Op.BINARY_MUL: self._op_binary_mul,
            Op.BINARY_DIV: self._op_binary_div,
            Op.BINARY_IDIV: self._op_binary_idiv,
            Op.BINARY_MOD: self._op_binary_mod,
            Op.BINARY_POW: self._op_binary_pow,
            Op.UNARY_NEG: self._op_unary_neg,
            Op.UNARY_NOT: self._op_unary_not,
            Op.TO_INT: self._op_to_int,
            Op.LOGICAL_AND: self._op_logical_and,
            Op.LOGICAL_OR: self._op_logical_or,
            Op.COMPARE_EQ: self._op_compare_eq,
            Op.COMPARE_NE: self._op_compare_ne,
            Op.COMPARE_LT: self._op_compare_lt,
            Op.COMPARE_LE: self._op_compare_le,
            Op.COMPARE_GT: self._op_compare_gt,
            Op.COMPARE_GE: self._op_compare_ge,
            Op.BUILD_LIST: self._op_build_list,
            Op.BUILD_TABLE: self._op_build_table,
            Op.INDEX_GET: self._op_index_get,
            Op.INDEX_SET: self._op_index_set,
            Op.GET_ATTR: self._op_get_attr,
            Op.SET_ATTR: self._op_set_attr,
            Op.CALL_NATIVE: self._op_call_native,
        }

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self, chunk: Chunk) -> Any:
        """Execute a chunk from instruction 0 until HALT, returning
        whatever value HALT leaves on top of the stack (None if empty)."""
        self.stack = []
        self.globals = {}
        self.frame = None
        self._constants = chunk.constants
        self._safety_counters = {}
        self._attempt_stack = []

        code = chunk.code
        dispatch = self._dispatch
        ip = 0

        while True:
            instr = code[ip]
            op = instr.op
            arg = instr.arg
            ip += 1

            # Try the dict-dispatched majority (loads/stores/arithmetic/
            # comparisons/CALL_NATIVE/...) first — with Op as an IntEnum
            # this is a single cheap int-hash dict lookup, and it covers
            # most instructions in any real program. The chain of ip-
            # affecting ops below (jumps, CALL/RETURN, HALT, ...) is the
            # minority by instruction count even though it's frequently
            # *taken* in a loop-heavy program, so checking it second
            # (only on a dispatch miss) beats paying ~10 sequential
            # equality checks on every single instruction regardless of
            # which kind it is.
            handler = dispatch.get(op)
            if handler is not None:
                try:
                    handler(arg)
                except NucleusRuntimeError:
                    if self._attempt_stack:
                        handler_ip, stack_depth = self._attempt_stack.pop()
                        del self.stack[stack_depth:]
                        ip = handler_ip
                        continue
                    raise
                continue

            if op == Op.JUMP:
                ip = arg
                continue
            if op == Op.JUMP_IF_FALSE:
                if not self._truthy(self.stack.pop()):
                    ip = arg
                continue
            if op == Op.JUMP_IF_TRUE:
                if self._truthy(self.stack.pop()):
                    ip = arg
                continue
            if op == Op.JUMP_IF_FALSE_OR_POP:
                if not self._truthy(self.stack[-1]):
                    ip = arg
                else:
                    self.stack.pop()
                continue
            if op == Op.JUMP_IF_TRUE_OR_POP:
                if self._truthy(self.stack[-1]):
                    ip = arg
                else:
                    self.stack.pop()
                continue
            if op == Op.SAFETY_TICK:
                count = self._safety_counters.get(arg, 0) + 1
                self._safety_counters[arg] = count
                if count > self.iteration_limit:
                    raise NucleusRuntimeError(
                        f"iteration limit ({self.iteration_limit}) exceeded "
                        f"at loop {arg!r}"
                    )
                continue
            if op == Op.CALL:
                target, argcount = arg
                if argcount:
                    args = self.stack[-argcount:]
                    del self.stack[-argcount:]
                else:
                    args = []
                new_frame = Frame(
                    locals={i: v for i, v in enumerate(args)},
                    # Parents the new frame on the *caller's* current frame
                    # (dynamic re-parenting per call, not per definition
                    # site) — this is what makes LOAD_NAME/STORE_NAME_DYNAMIC
                    # walk a real, call-chain-shaped scope for a language
                    # that needs one (e.g. STEPS). Harmless for a language
                    # whose compiler never emits those opcodes (e.g.
                    # FragBASIC): LOAD_FAST/STORE_FAST/LOAD_GLOBAL/
                    # STORE_GLOBAL never read `.parent`, so this is a
                    # zero-behavior-change field for them either way.
                    parent=self.frame,
                    caller=self.frame,
                    return_ip=ip,
                )
                self.frame = new_frame
                ip = target
                continue
            if op == Op.RETURN:
                value = self.stack.pop()
                if self.frame is None:
                    raise NucleusRuntimeError("RETURN with no active call frame")
                ip = self.frame.return_ip
                self.frame = self.frame.caller
                self.stack.append(value)
                continue
            if op == Op.BEGIN_ATTEMPT:
                self._attempt_stack.append((arg, len(self.stack)))
                continue
            if op == Op.END_ATTEMPT:
                if self._attempt_stack:
                    self._attempt_stack.pop()
                continue
            if op == Op.HALT:
                return self.stack.pop() if self.stack else None

            raise NucleusRuntimeError(f"unknown opcode {op!r} at ip={ip - 1}")

    @staticmethod
    def _truthy(value: Any) -> bool:
        return bool(value)

    def _require_frame(self) -> Frame:
        if self.frame is None:
            raise NucleusRuntimeError(
                "opcode requires an active call frame, but none is active "
                "(compiler bug: LOAD_FAST/STORE_FAST/LOAD_NAME/STORE_NAME_* "
                "must only be emitted inside a compiled function/proc body)"
            )
        return self.frame

    # ------------------------------------------------------------------
    # Opcode handlers
    # ------------------------------------------------------------------

    def _op_load_const(self, arg: int) -> None:
        self.stack.append(self._constants[arg])

    def _op_pop_top(self, arg: Any) -> None:
        self.stack.pop()

    def _op_dup_top(self, arg: Any) -> None:
        self.stack.append(self.stack[-1])

    def _op_swap(self, arg: Any) -> None:
        self.stack[-1], self.stack[-2] = self.stack[-2], self.stack[-1]

    def _op_load_fast(self, arg: Any) -> None:
        frame = self._require_frame()
        try:
            self.stack.append(frame.locals[arg])
        except KeyError:
            raise NucleusRuntimeError(f"local slot {arg!r} not set") from None

    def _op_store_fast(self, arg: Any) -> None:
        frame = self._require_frame()
        frame.locals[arg] = self.stack.pop()

    def _op_load_global(self, arg: str) -> None:
        try:
            self.stack.append(self.globals[arg])
        except KeyError:
            raise NucleusRuntimeError(f"global {arg!r} is not defined") from None

    def _op_store_global(self, arg: str) -> None:
        self.globals[arg] = self.stack.pop()

    def _op_load_name(self, arg: str) -> None:
        node = self._require_frame()
        while node is not None:
            if arg in node.locals:
                self.stack.append(node.locals[arg])
                return
            node = node.parent
        if arg in self.globals:
            self.stack.append(self.globals[arg])
            return
        raise NucleusRuntimeError(f"name {arg!r} is not defined")

    def _op_store_name_decl(self, arg: str) -> None:
        frame = self._require_frame()
        frame.locals[arg] = self.stack.pop()

    def _op_store_name_dynamic(self, arg: str) -> None:
        frame = self._require_frame()
        value = self.stack.pop()
        node = frame
        while node is not None:
            if arg in node.locals:
                node.locals[arg] = value
                return
            node = node.parent
        if arg in self.globals:
            self.globals[arg] = value
            return
        frame.locals[arg] = value

    def _op_binary_add(self, arg: Any) -> None:
        b = self.stack.pop()
        a = self.stack.pop()
        self.stack.append(a + b)

    def _op_binary_sub(self, arg: Any) -> None:
        b = self.stack.pop()
        a = self.stack.pop()
        self.stack.append(a - b)

    def _op_binary_mul(self, arg: Any) -> None:
        b = self.stack.pop()
        a = self.stack.pop()
        self.stack.append(a * b)

    def _op_binary_div(self, arg: Any) -> None:
        b = self.stack.pop()
        a = self.stack.pop()
        if b == 0:
            raise NucleusRuntimeError("division by zero")
        self.stack.append(a / b)

    def _op_binary_idiv(self, arg: Any) -> None:
        b = self.stack.pop()
        a = self.stack.pop()
        if b == 0:
            raise NucleusRuntimeError("division by zero")
        self.stack.append(a // b)

    def _op_binary_mod(self, arg: Any) -> None:
        b = self.stack.pop()
        a = self.stack.pop()
        if b == 0:
            raise NucleusRuntimeError("modulo by zero")
        self.stack.append(a % b)

    def _op_binary_pow(self, arg: Any) -> None:
        b = self.stack.pop()
        a = self.stack.pop()
        self.stack.append(a**b)

    def _op_unary_neg(self, arg: Any) -> None:
        self.stack.append(-self.stack.pop())

    def _op_unary_not(self, arg: Any) -> None:
        self.stack.append(not self._truthy(self.stack.pop()))

    def _op_to_int(self, arg: Any) -> None:
        self.stack.append(int(self.stack.pop()))

    def _op_logical_and(self, arg: Any) -> None:
        """Eager (non-short-circuit) logical AND — distinct from
        JUMP_IF_FALSE_OR_POP's short-circuit AND. Both operands are
        expected to already be on the stack (the compiler decides whether
        evaluating both unconditionally matters for its language, e.g.
        FragBASIC's AND/OR always do); this only combines their
        truthiness. Result is a Python bool — a consuming language whose
        boolean convention differs (e.g. BASIC-style -1/0) converts it
        itself (UNARY_NEG on a bool already gives exactly -1/0)."""
        b = self.stack.pop()
        a = self.stack.pop()
        self.stack.append(self._truthy(a) and self._truthy(b))

    def _op_logical_or(self, arg: Any) -> None:
        """Eager (non-short-circuit) logical OR — see _op_logical_and."""
        b = self.stack.pop()
        a = self.stack.pop()
        self.stack.append(self._truthy(a) or self._truthy(b))

    def _op_compare_eq(self, arg: Any) -> None:
        b = self.stack.pop()
        a = self.stack.pop()
        self.stack.append(a == b)

    def _op_compare_ne(self, arg: Any) -> None:
        b = self.stack.pop()
        a = self.stack.pop()
        self.stack.append(a != b)

    def _op_compare_lt(self, arg: Any) -> None:
        b = self.stack.pop()
        a = self.stack.pop()
        self.stack.append(a < b)

    def _op_compare_le(self, arg: Any) -> None:
        b = self.stack.pop()
        a = self.stack.pop()
        self.stack.append(a <= b)

    def _op_compare_gt(self, arg: Any) -> None:
        b = self.stack.pop()
        a = self.stack.pop()
        self.stack.append(a > b)

    def _op_compare_ge(self, arg: Any) -> None:
        b = self.stack.pop()
        a = self.stack.pop()
        self.stack.append(a >= b)

    def _op_build_list(self, arg: int) -> None:
        count = arg
        if count:
            items = self.stack[-count:]
            del self.stack[-count:]
        else:
            items = []
        self.stack.append(list(items))

    def _op_build_table(self, arg: int) -> None:
        """arg is the number of key-value *pairs* (not raw stack slots)."""
        count = arg
        d: dict[Any, Any] = {}
        if count:
            items = self.stack[-2 * count :]
            del self.stack[-2 * count :]
            for i in range(0, len(items), 2):
                d[items[i]] = items[i + 1]
        self.stack.append(d)

    def _op_index_get(self, arg: Any) -> None:
        idx = self.stack.pop()
        obj = self.stack.pop()
        try:
            self.stack.append(obj[idx])
        except (IndexError, KeyError, TypeError) as e:
            raise NucleusRuntimeError(f"index {idx!r} not found/out of range") from e

    def _op_index_set(self, arg: Any) -> None:
        value = self.stack.pop()
        idx = self.stack.pop()
        obj = self.stack.pop()
        obj[idx] = value

    def _op_get_attr(self, arg: str) -> None:
        obj = self.stack.pop()
        try:
            self.stack.append(obj[arg])
        except (KeyError, TypeError) as e:
            raise NucleusRuntimeError(f"attribute {arg!r} not found") from e

    def _op_set_attr(self, arg: str) -> None:
        value = self.stack.pop()
        obj = self.stack.pop()
        obj[arg] = value

    def _op_call_native(self, arg: tuple[str, int]) -> None:
        name, argcount = arg
        if argcount:
            args = self.stack[-argcount:]
            del self.stack[-argcount:]
        else:
            args = []
        fn = self.natives.get(name)
        if fn is None:
            raise NucleusRuntimeError(f"native function {name!r} is not registered")
        self.stack.append(fn(*args))

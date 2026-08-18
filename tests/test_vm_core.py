"""Phase 0 validation: hand-assembled bytecode exercising the VM core
*without* any language compiler existing yet — constants, globals, locals,
arithmetic, comparisons, jumps (loops), CALL/RETURN (including recursion),
and CALL_NATIVE. See dev-docs/DESIGN.md for the opcode semantics.
"""
from nucleus_vm import VM, Chunk, Op, NucleusRuntimeError
import pytest


def test_range_sum_loop():
    """sum(1..100) via a hand-assembled while loop over globals — proves
    LOAD_CONST/GLOBAL, BINARY_ADD, COMPARE_LE, and JUMP/JUMP_IF_FALSE."""
    chunk = Chunk("range_sum")
    n = 100
    n_idx = chunk.add_constant(n)
    zero_idx = chunk.add_constant(0)
    one_idx = chunk.add_constant(1)

    # total = 0
    chunk.emit(Op.LOAD_CONST, zero_idx)
    chunk.emit(Op.STORE_GLOBAL, "total")
    # i = 1
    chunk.emit(Op.LOAD_CONST, one_idx)
    chunk.emit(Op.STORE_GLOBAL, "i")

    loop_start = chunk.here()
    # while i <= n:
    chunk.emit(Op.LOAD_GLOBAL, "i")
    chunk.emit(Op.LOAD_CONST, n_idx)
    chunk.emit(Op.COMPARE_LE)
    jump_end = chunk.emit(Op.JUMP_IF_FALSE, None)

    # total = total + i
    chunk.emit(Op.LOAD_GLOBAL, "total")
    chunk.emit(Op.LOAD_GLOBAL, "i")
    chunk.emit(Op.BINARY_ADD)
    chunk.emit(Op.STORE_GLOBAL, "total")

    # i = i + 1
    chunk.emit(Op.LOAD_GLOBAL, "i")
    chunk.emit(Op.LOAD_CONST, one_idx)
    chunk.emit(Op.BINARY_ADD)
    chunk.emit(Op.STORE_GLOBAL, "i")

    chunk.emit(Op.JUMP, loop_start)

    chunk.patch_arg(jump_end, chunk.here())
    chunk.emit(Op.LOAD_GLOBAL, "total")
    chunk.emit(Op.HALT)

    result = VM().run(chunk)
    assert result == sum(range(1, n + 1))


def test_fibonacci_recursive():
    """fib(10) via real CALL/RETURN recursion (not Python recursion) —
    proves LOAD_FAST (arg slots), the CALL/RETURN frame swap, and that
    recursive calls correctly nest via the VM's own frame chain."""
    chunk = Chunk("fib")
    one = chunk.add_constant(1.0)
    two = chunk.add_constant(2.0)
    arg_n = chunk.add_constant(10.0)

    # main: push 10, call fib, halt
    chunk.emit(Op.LOAD_CONST, arg_n)
    call_main = chunk.emit(Op.CALL, None)  # patched once fib's address is known
    chunk.emit(Op.HALT)

    # fib(n): slot 0 = n
    fib_start = chunk.here()
    chunk.emit(Op.LOAD_FAST, 0)
    chunk.emit(Op.LOAD_CONST, two)
    chunk.emit(Op.COMPARE_LT)
    skip_base = chunk.emit(Op.JUMP_IF_FALSE, None)
    # if n < 2: return n
    chunk.emit(Op.LOAD_FAST, 0)
    chunk.emit(Op.RETURN)
    chunk.patch_arg(skip_base, chunk.here())

    # return fib(n - 1) + fib(n - 2)
    chunk.emit(Op.LOAD_FAST, 0)
    chunk.emit(Op.LOAD_CONST, one)
    chunk.emit(Op.BINARY_SUB)
    chunk.emit(Op.CALL, (fib_start, 1))
    chunk.emit(Op.LOAD_FAST, 0)
    chunk.emit(Op.LOAD_CONST, two)
    chunk.emit(Op.BINARY_SUB)
    chunk.emit(Op.CALL, (fib_start, 1))
    chunk.emit(Op.BINARY_ADD)
    chunk.emit(Op.RETURN)

    chunk.patch_arg(call_main, (fib_start, 1))

    result = VM().run(chunk)
    assert result == 55.0  # fib(10)


def test_fibonacci_recursion_depth_not_bounded_by_python_stack():
    """A large-enough fib(n) would blow Python's own recursion limit if
    CALL/RETURN were implemented via real Python function calls — confirms
    they aren't, by running a call chain deeper than Python's default
    recursion limit via a simple non-branching recursive countdown."""
    import sys

    chunk = Chunk("deep_countdown")
    one = chunk.add_constant(1.0)
    zero = chunk.add_constant(0.0)
    depth = sys.getrecursionlimit() + 2000
    arg_n = chunk.add_constant(float(depth))

    chunk.emit(Op.LOAD_CONST, arg_n)
    call_main = chunk.emit(Op.CALL, None)
    chunk.emit(Op.HALT)

    # countdown(n): if n <= 0: return n; else return countdown(n - 1)
    start = chunk.here()
    chunk.emit(Op.LOAD_FAST, 0)
    chunk.emit(Op.LOAD_CONST, zero)
    chunk.emit(Op.COMPARE_GT)
    skip_base = chunk.emit(Op.JUMP_IF_FALSE, None)
    chunk.emit(Op.LOAD_FAST, 0)
    chunk.emit(Op.LOAD_CONST, one)
    chunk.emit(Op.BINARY_SUB)
    chunk.emit(Op.CALL, (start, 1))
    chunk.emit(Op.RETURN)
    chunk.patch_arg(skip_base, chunk.here())
    chunk.emit(Op.LOAD_FAST, 0)
    chunk.emit(Op.RETURN)

    chunk.patch_arg(call_main, (start, 1))

    result = VM().run(chunk)
    assert result == 0.0


def test_call_native():
    """CALL_NATIVE — the one generic builtin escape hatch every consuming
    language routes its own function library through."""
    chunk = Chunk("native_call")
    a_idx = chunk.add_constant(3)
    b_idx = chunk.add_constant(4)

    chunk.emit(Op.LOAD_CONST, a_idx)
    chunk.emit(Op.LOAD_CONST, b_idx)
    chunk.emit(Op.CALL_NATIVE, ("max", 2))
    chunk.emit(Op.HALT)

    vm = VM(natives={"max": max})
    assert vm.run(chunk) == 4


def test_list_build_and_index():
    chunk = Chunk("list_ops")
    for v in (10, 20, 30):
        chunk.emit(Op.LOAD_CONST, chunk.add_constant(v))
    chunk.emit(Op.BUILD_LIST, 3)
    chunk.emit(Op.LOAD_CONST, chunk.add_constant(1))
    chunk.emit(Op.INDEX_GET)
    chunk.emit(Op.HALT)

    assert VM().run(chunk) == 20


def test_undefined_global_raises():
    chunk = Chunk("bad_global")
    chunk.emit(Op.LOAD_GLOBAL, "does_not_exist")
    chunk.emit(Op.HALT)

    with pytest.raises(NucleusRuntimeError):
        VM().run(chunk)


def test_to_int_truncates_toward_zero():
    chunk = Chunk("to_int")
    chunk.emit(Op.LOAD_CONST, chunk.add_constant(-3.9))
    chunk.emit(Op.TO_INT)
    chunk.emit(Op.HALT)

    result = VM().run(chunk)
    assert result == -3
    assert type(result) is int


def test_logical_and_or_are_eager_and_return_bool():
    """LOGICAL_AND/OR combine two already-evaluated operands' truthiness —
    distinct from JUMP_IF_*_OR_POP's short-circuit and/or, which never
    evaluates the second operand at all when the first already decides
    the result. Both operands here are unconditionally on the stack
    before the opcode runs, by construction."""
    for op, a, b, expected in [
        (Op.LOGICAL_AND, 1, 1, True),
        (Op.LOGICAL_AND, 1, 0, False),
        (Op.LOGICAL_AND, 0, 0, False),
        (Op.LOGICAL_OR, 0, 0, False),
        (Op.LOGICAL_OR, 1, 0, True),
        (Op.LOGICAL_OR, 0, 1, True),
    ]:
        chunk = Chunk("logical")
        chunk.emit(Op.LOAD_CONST, chunk.add_constant(a))
        chunk.emit(Op.LOAD_CONST, chunk.add_constant(b))
        chunk.emit(op)
        chunk.emit(Op.HALT)
        result = VM().run(chunk)
        assert result is expected, f"{op.name}({a}, {b})"


def test_logical_and_result_converts_to_basic_style_minus_one_zero():
    """A consuming language whose truthy/falsy convention is -1/0 rather
    than Python bool (e.g. classic BASIC) converts LOGICAL_AND/OR's bool
    result with a plain UNARY_NEG — -True == -1, -False == 0."""
    chunk = Chunk("logical_to_basic")
    chunk.emit(Op.LOAD_CONST, chunk.add_constant(1))
    chunk.emit(Op.LOAD_CONST, chunk.add_constant(1))
    chunk.emit(Op.LOGICAL_AND)
    chunk.emit(Op.UNARY_NEG)
    chunk.emit(Op.HALT)

    assert VM().run(chunk) == -1


# ----------------------------------------------------------------------
# Phase 2 de-risking: CALL's new frame must parent on the *caller's*
# current frame (dynamic re-parenting per call), not always None, or
# LOAD_NAME/STORE_NAME_DYNAMIC have no real chain to walk across a call
# boundary at all — the exact scoping model a dynamically-scoped language
# (e.g. STEPS) needs for nearly all its variable access. These hand-
# assemble the same three patterns Phase 0 validated resolved-scope
# opcodes with, before any STEPS compiler exists to exercise them for
# real. See dev-docs/PLAN.md's Phase 2 section for why this had to be
# checked directly rather than assumed from the opcode's original design.
# ----------------------------------------------------------------------

def test_nested_call_reads_outer_frames_variable_via_load_name():
    """Two levels deep: `inner`'s frame parents on `middle`'s, which
    parents on `main`'s — LOAD_NAME in `inner` must walk both hops to
    reach a variable only `main` ever declared.

    `main` itself is entered via a bootstrap CALL rather than running
    inline at ip 0 — LOAD_NAME/STORE_NAME_DECL both require an active
    frame (`_require_frame`), and `run()` starts with `self.frame = None`,
    so top-level code needs the same "wrap it in its own call" treatment
    a real compiler for a dynamically-scoped language gives its program's
    top level (see dev-docs/PLAN.md's Phase 2 section)."""
    chunk = Chunk("dynamic_scope_read")

    call_main = chunk.emit(Op.CALL, None)
    chunk.emit(Op.HALT)

    main_start = chunk.here()
    chunk.emit(Op.LOAD_CONST, chunk.add_constant(7.0))
    chunk.emit(Op.STORE_NAME_DECL, "z")
    call_middle = chunk.emit(Op.CALL, None)
    chunk.emit(Op.RETURN)

    middle_start = chunk.here()
    call_inner = chunk.emit(Op.CALL, None)
    chunk.emit(Op.RETURN)  # passes inner's return value through unchanged

    inner_start = chunk.here()
    chunk.emit(Op.LOAD_NAME, "z")  # not in inner's or middle's own locals
    chunk.emit(Op.RETURN)

    chunk.patch_arg(call_main, (main_start, 0))
    chunk.patch_arg(call_middle, (middle_start, 0))
    chunk.patch_arg(call_inner, (inner_start, 0))

    assert VM().run(chunk) == 7.0


def test_bare_dynamic_store_mutates_outer_frames_binding():
    """The classic STEPS "leak" pattern: a bare `set` on a name that
    already exists in an *enclosing* call's frame mutates it there,
    in place, rather than creating a new local — exactly
    STORE_NAME_DYNAMIC's contract, now proven across a real CALL
    boundary instead of only within a single hand-built frame."""
    chunk = Chunk("dynamic_scope_leak")

    call_main = chunk.emit(Op.CALL, None)
    chunk.emit(Op.HALT)

    main_start = chunk.here()
    chunk.emit(Op.LOAD_CONST, chunk.add_constant(10.0))
    chunk.emit(Op.STORE_NAME_DECL, "x")
    call_inner = chunk.emit(Op.CALL, None)
    chunk.emit(Op.POP_TOP)  # discard inner's return value
    chunk.emit(Op.LOAD_NAME, "x")  # read back x from main's own frame
    chunk.emit(Op.RETURN)

    inner_start = chunk.here()
    chunk.emit(Op.LOAD_NAME, "x")  # walks to main's frame: 10.0
    chunk.emit(Op.LOAD_CONST, chunk.add_constant(5.0))
    chunk.emit(Op.BINARY_ADD)
    chunk.emit(Op.STORE_NAME_DYNAMIC, "x")  # not local -> mutates main's x
    chunk.emit(Op.LOAD_CONST, chunk.add_constant(0.0))
    chunk.emit(Op.RETURN)

    chunk.patch_arg(call_main, (main_start, 0))
    chunk.patch_arg(call_inner, (inner_start, 0))

    assert VM().run(chunk) == 15.0


def test_declared_name_shadows_without_leaking_back():
    """The complementary case: STORE_NAME_DECL always binds in the
    *current* frame with no chain walk, even when a same-named binding
    already exists in an enclosing frame — it must shadow, not mutate,
    and the shadow must vanish (not leak back) once that frame's call
    returns."""
    chunk = Chunk("dynamic_scope_shadow")

    call_main = chunk.emit(Op.CALL, None)
    chunk.emit(Op.HALT)

    main_start = chunk.here()
    chunk.emit(Op.LOAD_CONST, chunk.add_constant(99.0))
    chunk.emit(Op.STORE_NAME_DECL, "y")
    call_inner = chunk.emit(Op.CALL, None)
    chunk.emit(Op.POP_TOP)  # discard inner's return value
    chunk.emit(Op.LOAD_NAME, "y")  # main's own y, untouched by inner
    chunk.emit(Op.RETURN)

    inner_start = chunk.here()
    chunk.emit(Op.LOAD_CONST, chunk.add_constant(999.0))
    chunk.emit(Op.STORE_NAME_DECL, "y")  # shadows in inner's own frame only
    chunk.emit(Op.LOAD_CONST, chunk.add_constant(0.0))
    chunk.emit(Op.RETURN)

    chunk.patch_arg(call_main, (main_start, 0))
    chunk.patch_arg(call_inner, (inner_start, 0))

    assert VM().run(chunk) == 99.0

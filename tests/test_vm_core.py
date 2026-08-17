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

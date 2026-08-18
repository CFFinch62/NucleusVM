"""The NucleusVM opcode set.

See dev-docs/DESIGN.md for the full opcode table and the reasoning behind
each one. This module only defines the enum — behavior lives in vm.py.
"""
from enum import IntEnum, auto


class Op(IntEnum):
    # Stack hygiene
    LOAD_CONST = auto()
    POP_TOP = auto()
    DUP_TOP = auto()
    SWAP = auto()

    # Variable access
    LOAD_FAST = auto()
    STORE_FAST = auto()
    LOAD_GLOBAL = auto()
    STORE_GLOBAL = auto()
    LOAD_NAME = auto()
    STORE_NAME_DECL = auto()
    STORE_NAME_DYNAMIC = auto()

    # Arithmetic / logic
    BINARY_ADD = auto()
    BINARY_SUB = auto()
    BINARY_MUL = auto()
    BINARY_DIV = auto()
    BINARY_IDIV = auto()
    BINARY_MOD = auto()
    BINARY_POW = auto()
    UNARY_NEG = auto()
    UNARY_NOT = auto()
    TO_INT = auto()
    LOGICAL_AND = auto()
    LOGICAL_OR = auto()

    # Comparison
    COMPARE_EQ = auto()
    COMPARE_NE = auto()
    COMPARE_LT = auto()
    COMPARE_LE = auto()
    COMPARE_GT = auto()
    COMPARE_GE = auto()

    # Control flow
    JUMP = auto()
    JUMP_IF_FALSE = auto()
    JUMP_IF_TRUE = auto()
    JUMP_IF_FALSE_OR_POP = auto()
    JUMP_IF_TRUE_OR_POP = auto()

    # Runaway-loop guard
    SAFETY_TICK = auto()

    # Collections
    BUILD_LIST = auto()
    BUILD_TABLE = auto()
    INDEX_GET = auto()
    INDEX_SET = auto()
    GET_ATTR = auto()
    SET_ATTR = auto()

    # Calls
    CALL = auto()
    RETURN = auto()
    CALL_NATIVE = auto()

    # Error handling (STEPS's attempt/unsuccessful)
    BEGIN_ATTEMPT = auto()
    END_ATTEMPT = auto()

    HALT = auto()

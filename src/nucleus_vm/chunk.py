"""Bytecode chunk format: a constants pool plus an instruction stream.

Instructions are stored as a plain list of Instruction objects rather than
packed bytes — this is a Python-hosted VM, so there is no benefit to a raw
byte encoding (Python list/attribute access is already the primitive cost
unit here), and a structured instruction is much easier to inspect/debug
while compilers are still being built for each consuming language.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .opcodes import Op


@dataclass
class Instruction:
    op: Op
    arg: Any = None
    line: int = 0


class Chunk:
    """One compiled unit of bytecode. A jump/call target is simply an index
    into `code` — there is no separate address translation step."""

    def __init__(self, name: str = "<chunk>"):
        self.name = name
        self.code: list[Instruction] = []
        self.constants: list[Any] = []

    def emit(self, op: Op, arg: Any = None, line: int = 0) -> int:
        """Append an instruction, returning its index — useful for later
        backpatching a jump/call target once it's known (e.g. the end of a
        loop body, or a function's entry point compiled after the call
        site that references it)."""
        self.code.append(Instruction(op, arg, line))
        return len(self.code) - 1

    def patch_arg(self, index: int, new_arg: Any) -> None:
        """Rewrite a previously-emitted instruction's operand in place —
        used for backpatching jump targets and forward call references."""
        instr = self.code[index]
        self.code[index] = Instruction(instr.op, new_arg, instr.line)

    def add_constant(self, value: Any) -> int:
        """Append a value to the constants pool, returning its index.

        Deliberately does not dedupe identical values: Python's `==`
        conflates types that must stay distinct here (`True == 1`), so a
        naive `constants.index(value)` reuse could silently substitute the
        wrong type. Dedup is a size optimization, not a correctness
        requirement — not worth the footgun at this stage.
        """
        self.constants.append(value)
        return len(self.constants) - 1

    def here(self) -> int:
        """The index the *next* emitted instruction will land at — the
        natural target for a jump that should land "right after this
        point", e.g. patching a loop-exit jump once the loop body is done."""
        return len(self.code)

    def __len__(self) -> int:
        return len(self.code)

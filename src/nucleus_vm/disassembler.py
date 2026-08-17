"""Human-readable disassembly of a NucleusVM Chunk, for debugging
compilers as each consuming language builds one."""
from __future__ import annotations

from .chunk import Chunk
from .opcodes import Op


def disassemble(chunk: Chunk) -> str:
    lines = [f"== {chunk.name} =="]
    for i, instr in enumerate(chunk.code):
        arg_repr = ""
        if instr.arg is not None:
            if instr.op is Op.LOAD_CONST:
                arg_repr = f"{instr.arg} ({chunk.constants[instr.arg]!r})"
            else:
                arg_repr = repr(instr.arg)
        lines.append(f"{i:5d}  L{instr.line:<4d} {instr.op.name:<22s} {arg_repr}")
    return "\n".join(lines)

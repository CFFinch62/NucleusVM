# NucleusVM

A shared, generic bytecode virtual machine core, written in Python, meant
to be reused as the execution engine for multiple Python-hosted teaching
languages ([STEPS](https://github.com/CFFinch62/Steps), FragBASIC, and
potentially others later) instead of each language maintaining its own
separate tree-walking interpreter.

## Why

Several of these languages' interpreters are Python-hosted AST tree-walkers.
Tree-walking pays a real, structural cost per AST node visited (a recursive
Python function call per node, even after dispatch-lookup is cached) that a
bytecode VM avoids by compiling the AST into a flat instruction stream once
and executing it with a single dispatch loop over an explicit stack. Rather
than build a separate VM per language, NucleusVM is a **single, generic VM
core** — each language contributes only its own compiler (AST → NucleusVM
bytecode), not its own execution engine.

See `dev-docs/` for the design rationale and the fuller cross-language
research this project is built on.

## What lives here vs. what doesn't

**In this repo**: the bytecode chunk format, the opcode set, the VM's
dispatch loop / operand stack / call-frame stack, and a disassembler.
Nothing language-specific.

**Not in this repo**: any particular language's lexer, parser, AST,
compiler, or builtin function library. Each consuming language keeps all
of that in its own repo, and adds a new "compile AST to NucleusVM bytecode"
module of its own — this repo doesn't know STEPS or FragBASIC exist.

## Status

Early — Phase 0 (core VM loop, no language compiler yet). See
`dev-docs/DESIGN.md` for the opcode set and the phased plan this project is
following.

## Using NucleusVM from a language project

```bash
pip install -e /path/to/NucleusVM
```

Editable local install — a consuming language's own repo records this as a
path dependency in its `pyproject.toml`. Changes here are picked up
immediately without reinstalling.

## Development

```bash
pip install -e ".[dev]"
pytest
```

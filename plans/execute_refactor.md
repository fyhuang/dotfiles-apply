# Refactor: Uniform Plan/Execute Pattern for All Filesystem Operations

## Context

The `--dry-run` flag for `apply` had a bug where `ensure_customs_symlink` still created a symlink. This was fixed with an ad-hoc `dry_run` parameter, but `ensure_customs_symlink` and `build_include_d` still interleave planning and execution, making dry-run correctness fragile. The existing `LinkOperations` class already demonstrates a clean plan/execute separation. This refactoring extends that pattern to all filesystem-modifying code, making dry-run correctness structural rather than per-function.

## Plan

### Step 1: Add `execute_operation()`, `print_operation()`, `apply_plan()`

Three new standalone functions in apply.py:

- **`execute_operation(op: Operation)`** — Handles all action types: `"noop"` (skip), `"create"` (mkdir parents + symlink), `"replace"` (remove existing + mkdir parents + symlink), `"wipe_dir"` (shutil.rmtree). Replaces `LinkOperations.execute_link()`.
- **`print_operation(op: Operation)`** — Uses `ls -l` style format: `dest_path -> source_path`. Examples:
  - noop: `  ok: .../customs -> all_customs/x`
  - create: `  create: .../customs -> all_customs/x`
  - replace: `  replace: .../customs -> all_customs/x`
  - wipe_dir: `  wipe: .../include.d`
- **`apply_plan(plan: list[Operation], dry_run: bool = False)`** — Print all ops, then if not dry_run, execute all ops.

### Step 2: Convert `LinkOperations` class to standalone `plan_links(config)` function

Move `plan_links()` out of the class, taking `config` as a parameter. Delete the `LinkOperations` class. Simplify `apply_links()` to just `apply_plan(plan_links(config), dry_run)`.

Update `test_plan_execute()`: replace `LinkOperations(config)` / `link_ops.plan_links()` / `link_ops.execute_link(op)` with `plan_links(config)` / `execute_operation(op)`.

### Step 3: Extract `plan_customs_symlink(config)` from `ensure_customs_symlink()`

Returns `list[Operation]`:
- Symlink already correct → `[Operation("noop", None, customs_link)]`
- Symlink points elsewhere → `[Operation("replace", target, customs_link)]`
- Doesn't exist → `[Operation("create", target, customs_link)]`
- Exists but not a symlink → raise Exception (not plannable)
- `customs_name is None` → `[]`

Simplify `ensure_customs_symlink()` to just `apply_plan(plan_customs_symlink(config), dry_run)`.

### Step 4: Extract `plan_include_d(config)` from `build_include_d()`

Returns `list[Operation]`:
- If `include.d/` exists → `Operation("wipe_dir", None, include_d)` first
- Then `Operation("create", source.absolute(), include_d / relpath)` for each entry (sorted)

Simplify `build_include_d()` to just `apply_plan(plan_include_d(config), dry_run)`.

### Step 5: Inline thin wrappers into `main()`

Since `ensure_customs_symlink()`, `build_include_d()`, and `apply_links()` are now one-liners calling `apply_plan(plan_fn(config), dry_run)`, inline them directly into `main()` instead of keeping the wrapper functions. The `apply` command in `main()` becomes:

```python
elif args.command == "apply":
    config = MachineConfig(top=args.top, customs_name=args.customs)
    apply_plan(plan_customs_symlink(config), args.dry_run)
    apply_plan(plan_include_d(config), args.dry_run)
    apply_plan(plan_links(config), args.dry_run)
```

The `build-includes` command similarly becomes:
```python
elif args.command == "build-includes":
    config = MachineConfig(top=args.top, customs_name=args.customs)
    apply_plan(plan_include_d(config), args.dry_run)
```

Delete the old wrapper functions (`ensure_customs_symlink`, `build_include_d`, `apply_links`).

### Step 6: Update tests

- Update `test_plan_execute` for removed `LinkOperations` class
- Update `test_build_include_d_*` and `test_ensure_customs_symlink_*` to call `apply_plan(plan_fn(config))` instead of the deleted wrappers

## Files to modify

- `apply.py` — all production changes
- `test_apply.py` — update for removed class + inlined wrappers

## Verification

Run `uv run pytest` after each step to confirm all 16 tests pass.

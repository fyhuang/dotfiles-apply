#!/usr/bin/env python3

import sys

if sys.version_info[0] < 3:
    raise Exception("Python 3 required")

import os
import os.path
import argparse
import base64
import shutil
from enum import Enum
from pathlib import Path
from collections import namedtuple
from typing import NamedTuple, assert_never


################################
# Data Classes
################################

DotfileEntry = namedtuple(
    "DotfileEntry", ["source_path", "target_path", "relative_path"]
)

IncludeEntry = namedtuple(
    "IncludeEntry", ["source_path", "relative_path"]
)


class Action(Enum):
    NOOP = "noop"
    CREATE = "create"
    REPLACE = "replace"
    WIPE_DIR = "wipe_dir"


class Operation(NamedTuple):
    action: Action
    source_path: Path | None
    dest_path: Path


class MachineConfig:
    def __init__(self, top=None, dest=None, customs_name: str | None = None):
        if top is None:
            #top = Path(os.path.realpath(__file__)).parent
            top = Path.cwd()
        self.top = Path(top)

        if dest is None:
            dest = Path.home()
        self.dest = Path(dest)

        self.customs_name = customs_name

    def homelinks(self) -> Path:
        return self.top / "homelinks"

    def customs_dir(self) -> Path | None:
        if self.customs_name is not None:
            return self.top / "all_customs" / self.customs_name
        # Fallback: customs/ symlink (backward compat)
        customs_path = self.top / "customs"
        if customs_path.exists():
            return customs_path
        return None

    def tags(self) -> list[str]:
        cd = self.customs_dir()
        if cd is None:
            return []
        tags_file = cd / "tags"
        if not tags_file.exists():
            return []
        return [line.strip() for line in open(tags_file) if line.strip()]

    def path_overrides(self) -> dict:
        base = read_path_overrides(self.top / "path_overrides")
        cd = self.customs_dir()
        custom = read_path_overrides(cd / "path_overrides") if cd else {}
        return base | custom


################################
# Pure Functions
################################


def read_path_overrides(filepath: Path) -> dict:
    if not filepath.exists():
        return {}
    with open(filepath) as f:
        return dict(line.strip().split(":", maxsplit=1) for line in f if ":" in line)


def get_dotfile_entries_from(config: MachineConfig, source_dir: Path) -> list[DotfileEntry]:
    """Walk a homelinks-style directory and return entries with resolved target paths."""
    overrides = config.path_overrides()
    entries: list[DotfileEntry] = []

    def search_recur(top: Path):
        for child in top.iterdir():
            if child.name == "_link_individual":
                continue

            if child.is_dir():
                # we'll link the whole dir, unless _link_individual file is present
                if (child / "_link_individual").exists():
                    search_recur(child)
                    continue

            relpath = child.relative_to(source_dir)

            # apply path overrides
            if str(relpath) in overrides:
                target = config.dest / overrides[str(relpath)]
            else:
                target = config.dest / relpath

            entries.append(DotfileEntry(child, target, relpath))

    search_recur(source_dir)
    return entries


def get_all_dotfile_entries(config: MachineConfig) -> list[DotfileEntry]:
    """Collect from homelinks/ + homelinks-<tag>/ for each active tag."""
    entries = get_dotfile_entries_from(config, config.homelinks())
    for tag in config.tags():
        tag_homelinks = config.top / f"homelinks-{tag}"
        if tag_homelinks.is_dir():
            entries += get_dotfile_entries_from(config, tag_homelinks)
    return entries


def get_available_customs(config: MachineConfig) -> list[str]:
    return [p.name for p in config.top.glob("all_customs/*")]


def collect_include_entries(config: MachineConfig) -> list[IncludeEntry]:
    """Collect include files. Raises on conflicts."""
    tags = config.tags()
    seen: dict[Path, str] = {}  # relpath -> source_dir name (for conflict detection)
    entries: list[IncludeEntry] = []
    source_dirs = [config.top / "include"] + [config.top / f"include-{t}" for t in tags]
    for source_dir in source_dirs:
        if not source_dir.is_dir():
            continue
        for f in source_dir.rglob("*"):
            if f.is_file():
                relpath = f.relative_to(source_dir)
                if relpath in seen:
                    raise Exception(
                        f"Conflict: {relpath} provided by both "
                        f"{seen[relpath]} and {source_dir.name}"
                    )
                seen[relpath] = source_dir.name
                entries.append(IncludeEntry(f, relpath))
    return entries


def plan_include_d(config: MachineConfig) -> list[Operation]:
    """Plan include.d/ rebuild from include/ + include-<tag>/ for active tags."""
    include_d = config.top / "include.d"
    entries = collect_include_entries(config)
    plan: list[Operation] = []

    # Wipe existing include.d/
    if include_d.exists():
        plan.append(Operation(Action.WIPE_DIR, None, include_d))

    # Create symlinks
    for entry in sorted(entries, key=lambda e: e.relative_path):
        plan.append(Operation(Action.CREATE, entry.source_path.absolute(), include_d / entry.relative_path))

    return plan


def generate_bundle(config: MachineConfig) -> str:
    """Generate a self-contained shell script for deploying dotfiles."""
    tags = config.tags()
    lines: list[str] = []
    lines.append("#!/bin/sh")
    lines.append(f"# Generated by apply.py bundle")
    lines.append(f"# Customs: {config.customs_name}")
    lines.append(f"# Tags: {', '.join(tags)}")
    lines.append("set -e")
    lines.append("")
    lines.append("VERBOSE=0")
    lines.append('if [ "$1" = "-v" ]; then')
    lines.append("  VERBOSE=1")
    lines.append("fi")
    lines.append("")
    lines.append("install_file() {")
    lines.append('  mkdir -p "$(dirname "$1")"')
    lines.append('  base64 -d > "$1"')
    lines.append('  chmod "$2" "$1"')
    lines.append('  if [ "$VERBOSE" = "1" ]; then')
    lines.append('    echo "$1"')
    lines.append("  fi")
    lines.append("}")
    lines.append("")

    def add_file(target_template: str, source_path: Path):
        content = source_path.read_bytes()
        b64 = base64.b64encode(content).decode()
        lines.append(f"install_file \"{target_template}\" 644 << 'ENDOFFILE'")
        lines.append(b64)
        lines.append("ENDOFFILE")
        lines.append("")

    # Homelinks
    lines.append("# Homelinks")
    entries = get_all_dotfile_entries(config)
    for entry in entries:
        if entry.source_path.is_dir():
            # Directory linked as a whole — bundle each file inside it
            for f in sorted(entry.source_path.rglob("*")):
                if f.is_file():
                    rel_target = entry.target_path / f.relative_to(entry.source_path)
                    add_file(f"$HOME/{rel_target.relative_to(config.dest)}", f)
        else:
            rel_target = entry.target_path.relative_to(config.dest)
            add_file(f"$HOME/{rel_target}", entry.source_path)

    # Includes (merged)
    lines.append("# Includes")
    include_entries = collect_include_entries(config)
    for entry in sorted(include_entries, key=lambda e: e.relative_path):
        add_file(f"$HOME/dotfiles/include.d/{entry.relative_path}", entry.source_path)

    # Customs
    cd = config.customs_dir()
    if cd is not None:
        lines.append("# Customs")
        for f in sorted(cd.rglob("*")):
            if f.is_file():
                relpath = f.relative_to(cd)
                add_file(f"$HOME/dotfiles/customs/{relpath}", f)

    return "\n".join(lines) + "\n"


################################
# Plan/Execute
################################


def execute_operation(op: Operation) -> None:
    action = op.action
    match action:
        case Action.NOOP:
            return
        case Action.WIPE_DIR:
            shutil.rmtree(op.dest_path)
        case Action.CREATE | Action.REPLACE:
            assert op.source_path is not None
            if os.path.lexists(op.dest_path):
                os.remove(op.dest_path)
            # make parent directories if necessary
            os.makedirs(op.dest_path.parent, exist_ok=True)
            os.symlink(op.source_path, op.dest_path)
        case _ as unreachable:
            assert_never(unreachable)


def print_operation(op: Operation) -> None:
    action = op.action
    match action:
        case Action.NOOP:
            print(f"  ok: {op.dest_path} -> {op.source_path}")
        case Action.CREATE:
            print(f"  create: {op.dest_path} -> {op.source_path}")
        case Action.REPLACE:
            print(f"  replace: {op.dest_path} -> {op.source_path}")
        case Action.WIPE_DIR:
            print(f"  wipe: {op.dest_path}")
        case _ as unreachable:
            assert_never(unreachable)


def apply_plan(plan: list[Operation], dry_run: bool = False) -> None:
    for op in plan:
        print_operation(op)
    if dry_run:
        return
    for op in plan:
        execute_operation(op)


def plan_links(config: MachineConfig) -> list[Operation]:
    entries = get_all_dotfile_entries(config)
    plan = []
    for entry in entries:
        abs_source_path = entry.source_path.absolute()
        if entry.target_path.is_symlink():
            # Check symlinks first (handles both valid and broken symlinks)
            if entry.target_path.readlink() != abs_source_path:
                plan.append(Operation(Action.REPLACE, abs_source_path, entry.target_path))
            else:
                plan.append(Operation(Action.NOOP, None, entry.target_path))
        elif os.path.exists(entry.target_path):
            # exists and is not a symlink
            plan.append(Operation(Action.REPLACE, abs_source_path, entry.target_path))
        else:
            plan.append(Operation(Action.CREATE, abs_source_path, entry.target_path))

    return plan


def plan_customs_symlink(config: MachineConfig) -> list[Operation]:
    """Plan customs/ symlink to point to all_customs/<name>/."""
    if config.customs_name is None:
        return []
    customs_link = config.top / "customs"
    target = Path("all_customs") / config.customs_name
    if customs_link.is_symlink():
        if customs_link.readlink() == target:
            return [Operation(Action.NOOP, target, customs_link)]
        return [Operation(Action.REPLACE, target, customs_link)]
    elif customs_link.exists():
        raise Exception(f"customs/ exists and is not a symlink: {customs_link}")
    return [Operation(Action.CREATE, target, customs_link)]


################################
# CLI Interface
################################


def main():
    parser = argparse.ArgumentParser(description="Dotfile Symlink Manager")
    parser.add_argument("--top", default=None, help="Path to dotfiles repo (default: cwd)")
    subparsers = parser.add_subparsers(dest="command")

    # apply
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--customs", required=True)
    apply_parser.add_argument("--dry-run", action="store_true")

    # build-includes
    bi_parser = subparsers.add_parser("build-includes")
    bi_parser.add_argument("--customs", required=True)
    bi_parser.add_argument("--dry-run", action="store_true")

    # bundle
    bundle_parser = subparsers.add_parser("bundle")
    bundle_parser.add_argument("--customs", required=True)
    bundle_parser.add_argument("--output", required=True)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()

    elif args.command == "apply":
        config = MachineConfig(top=args.top, customs_name=args.customs)
        apply_plan(plan_customs_symlink(config), args.dry_run)
        apply_plan(plan_include_d(config), args.dry_run)
        apply_plan(plan_links(config), args.dry_run)

    elif args.command == "build-includes":
        config = MachineConfig(top=args.top, customs_name=args.customs)
        apply_plan(plan_include_d(config), args.dry_run)

    elif args.command == "bundle":
        config = MachineConfig(top=args.top, customs_name=args.customs)
        bundle_content = generate_bundle(config)
        with open(args.output, "w") as f:
            f.write(bundle_content)
        print(f"Bundle written to {args.output}")


if __name__ == "__main__":
    main()

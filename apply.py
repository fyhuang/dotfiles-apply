#!/usr/bin/env python3

import sys

if sys.version_info[0] < 3:
    raise Exception("Python 3 required")

import os
import os.path
import argparse
import base64
import shutil
from pathlib import Path
from collections import namedtuple


################################
# Data Classes
################################

DotfileEntry = namedtuple(
    "DotfileEntry", ["source_path", "target_path", "relative_path"]
)


Operation = namedtuple(
    "Operation", ["action", "source_path", "dest_path"]
)


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


def collect_include_entries(config: MachineConfig) -> dict[Path, Path]:
    """Collect include files: {relpath -> source_path}. Raises on conflicts."""
    tags = config.tags()
    entries: dict[Path, tuple[Path, str]] = {}
    source_dirs = [config.top / "include"] + [config.top / f"include-{t}" for t in tags]
    for source_dir in source_dirs:
        if not source_dir.is_dir():
            continue
        for f in source_dir.rglob("*"):
            if f.is_file():
                relpath = f.relative_to(source_dir)
                if relpath in entries:
                    _, prev_dir = entries[relpath]
                    raise Exception(
                        f"Conflict: {relpath} provided by both "
                        f"{prev_dir} and {source_dir.name}"
                    )
                entries[relpath] = (f, source_dir.name)
    return {relpath: source for relpath, (source, _) in entries.items()}


def build_include_d(config: MachineConfig, dry_run: bool = False) -> None:
    """Rebuild include.d/ from include/ + include-<tag>/ for active tags."""
    include_d = config.top / "include.d"
    entries = collect_include_entries(config)

    for relpath, source in sorted(entries.items()):
        print(f"  {source} -> include.d/{relpath}")

    if dry_run:
        return

    # Wipe and recreate
    if include_d.exists():
        shutil.rmtree(include_d)

    # Create symlinks
    for relpath, source in entries.items():
        dest = include_d / relpath
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.symlink_to(source.absolute())


################################
# Operation Classes
################################


class LinkOperations:
    def __init__(self, config: MachineConfig):
        self.config = config

    def plan_links(self) -> list[Operation]:
        entries = get_all_dotfile_entries(self.config)
        plan = []
        for entry in entries:
            abs_source_path = entry.source_path.absolute()
            if not os.path.exists(entry.target_path):
                plan.append(Operation("create", abs_source_path, entry.target_path))
            elif entry.target_path.is_symlink():
                if entry.target_path.readlink() != abs_source_path:
                    plan.append(Operation("replace", abs_source_path, entry.target_path))
                else:
                    plan.append(Operation("noop", None, entry.target_path))
            else:
                # exists and is not a symlink
                plan.append(Operation("replace", abs_source_path, entry.target_path))

        return plan

    def execute_link(self, operation: Operation):
        if operation.action == "noop":
            return

        if os.path.exists(operation.dest_path):
            os.remove(operation.dest_path)

        # make parent directories if necessary
        os.makedirs(operation.dest_path.parent, exist_ok=True)

        # get the absolute path of source_path
        os.symlink(operation.source_path, operation.dest_path)


################################
# CLI Interface
################################


def ensure_customs_symlink(config: MachineConfig) -> None:
    """Create/update customs/ symlink to point to all_customs/<name>/."""
    if config.customs_name is None:
        return
    customs_link = config.top / "customs"
    target = Path("all_customs") / config.customs_name
    if customs_link.is_symlink():
        if customs_link.readlink() == target:
            print(f"  customs/ -> {target} (ok)")
            return
        print(f"  customs/ -> {target} (updating)")
        customs_link.unlink()
    elif customs_link.exists():
        raise Exception(f"customs/ exists and is not a symlink: {customs_link}")
    else:
        print(f"  customs/ -> {target} (creating)")
    customs_link.symlink_to(target)


def apply_links(config: MachineConfig, dry_run: bool = False) -> None:
    """Apply all symlinks for the given machine config."""
    link_ops = LinkOperations(config)
    planned = link_ops.plan_links()

    for op in planned:
        if op.action == "noop":
            print(f"  ok: {op.dest_path}")
        elif op.action == "create":
            print(f"  create: {op.source_path} -> {op.dest_path}")
        elif op.action == "replace":
            print(f"  replace: {op.source_path} -> {op.dest_path}")

    if dry_run:
        return

    for op in planned:
        link_ops.execute_link(op)


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


    args = parser.parse_args()

    if args.command is None:
        parser.print_help()

    elif args.command == "apply":
        config = MachineConfig(top=args.top, customs_name=args.customs)
        ensure_customs_symlink(config)
        build_include_d(config, dry_run=args.dry_run)
        apply_links(config, dry_run=args.dry_run)

    elif args.command == "build-includes":
        config = MachineConfig(top=args.top, customs_name=args.customs)
        build_include_d(config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

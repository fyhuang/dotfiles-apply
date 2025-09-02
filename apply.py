#!/usr/bin/env python3

import sys

if sys.version_info[0] < 3:
    raise Exception("Python 3 required")

import os
import os.path
import argparse
import pprint
from pathlib import Path
from collections import namedtuple

from typing import Tuple, List


################################
# Data Classes
################################

DotfileEntry = namedtuple(
    "DotfileEntry", ["source_path", "target_path", "relative_path"]
)


Operation = namedtuple(
    "Operation", ["action", "source_path", "dest_path"]
)


class Paths:
    def __init__(self, top=None, dest=None):
        if top is None:
            #top = Path(os.path.realpath(__file__)).parent
            top = Path.cwd()
        self.top = Path(top)

        if dest is None:
            dest = Path.home()
        self.dest = Path(dest)

    def homelinks(self):
        return self.top / "homelinks"

    def path_overrides(self) -> dict:
        base = read_path_overrides(self.top / "path_overrides")
        custom = read_path_overrides(self.top / "customs" / "path_overrides")
        return base | custom


################################
# Pure Functions
################################


def read_path_overrides(filepath: Path) -> dict:
    if not filepath.exists():
        return {}
    with open(filepath) as f:
        return dict(line.strip().split(":", maxsplit=1) for line in f if ":" in line)


def get_dotfile_entries(paths):
    overrides = paths.path_overrides()

    source_paths = []
    relative_paths = []
    target_paths = []

    def search_recur(top: Path):
        for child in top.iterdir():
            if child.name == "_link_individual":
                continue

            if child.is_dir():
                # we'll link the whole dir, unless _link_individual file is present
                if (child / "_link_individual").exists():
                    search_recur(child)
                    continue

            source_paths.append(child)
            relpath = child.relative_to(paths.homelinks())
            relative_paths.append(relpath)

            # apply path overrides
            if str(relpath) in overrides:
                target_paths.append(paths.dest / overrides[str(relpath)])
            else:
                target_paths.append(paths.dest / relpath)

    search_recur(paths.homelinks())
    return [DotfileEntry(*t) for t in zip(source_paths, target_paths, relative_paths)]


def get_available_customs(paths):
    return [p.name for p in paths.top.glob("all_customs/*")]


################################
# Operation Classes
################################


class LinkOperations:
    def __init__(self, paths):
        self.paths = paths

    def plan_links(self) -> List[Operation]:
        entries = get_dotfile_entries(self.paths)
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
            print("Removing {}".format(operation.dest_path))
            os.remove(operation.dest_path)

        # make parent directories if necessary
        target_dir = operation.dest_path.parent
        print("Creating directory {}".format(target_dir))
        os.makedirs(target_dir, exist_ok=True)

        # get the absolute path of source_path
        print("Linking {} -> {}".format(operation.source_path, operation.dest_path))
        os.symlink(operation.source_path, operation.dest_path)


################################
# CLI Interface
################################


def get_confirm(prompt, default_response="y"):
    confirm = input(prompt).lower()
    if confirm == "":
        confirm = default_response
    return confirm


def print_current_status(target_path):
    if os.path.islink(target_path):
        print("{} currently points to {}".format(target_path, os.readlink(target_path)))
    elif os.path.isfile(target_path):
        print("{} is a regular file".format(target_path))
    else:
        print("{} is of unknown type".format(target_path))


def print_help():
    print(
        "Don't forget to run `git submodule update --init --recursive` for vim plugins"
    )
    print("For Ansible:")
    print("sudo add-apt-repository --update ppa:ansible/ansible")
    print("sudo apt install ansible")


def make_links_cli():
    paths = Paths()
    link_ops = LinkOperations(paths)
    planned_links = link_ops.plan_links()

    # pick files
    toapply = []
    for operation in planned_links:
        if operation.action == "noop":
            continue

        print("Filename of symlink: {}".format(operation.dest_path))
        relative_path = operation.source_path.relative_to(paths.homelinks())

        if operation.action == "create":
            confirm = get_confirm("Link {} (Y/n)? ".format(relative_path), "y")
        elif operation.action == "replace":
            print_current_status(operation.dest_path)
            confirm = get_confirm(
                "Remove and link {} (Y/n)? ".format(relative_path), "y"
            )

        if confirm == "y":
            toapply.append(operation)

    # make links
    for operation in toapply:
        link_ops.execute_link(operation)

    print("Done")
    print_help()


def main():
    parser = argparse.ArgumentParser(description="Dotfile Symlink Manager")
    parser.add_argument("command", choices=["interactive", "printops"], default="interactive", nargs="?")
    args = parser.parse_args()

    if args.command == "interactive":
        selection = ""
        while selection != "x":
            print()
            print("apply.py:")
            print("  l: make symlinks to home directory")
            print("  h: help")

            selection = input("? ")
            if selection == "l":
                make_links_cli()
            elif selection == "h":
                print_help()

    elif args.command == "printops":
        ops = LinkOperations(Paths()).plan_links()
        pprint.pp(ops)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3

import sys
if sys.version_info[0] < 3:
    raise Exception("Python 3 required")


import os
import os.path
import glob
import os.path
from pathlib import Path
from collections import namedtuple


DotfileEntry = namedtuple('DotfileEntry', ['source_path', 'target_path', 'relative_path'])

class Paths:
    def __init__(self, top=None, dest=None):
        if top is None:
            top = Path(os.path.realpath(__file__)).parent
        self.top = Path(top)

        if dest is None:
            dest = Path.home()
        self.dest = Path(dest)

    def homelinks(self):
        return self.top / "homelinks"

    def paths_file(self):
        return self.top / "paths"


################################
# CLI utilities
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


################################
# Customs and linking
################################

def get_dotfile_entries(paths):
    def search_recur(top):
        filenames = []
        entries = os.listdir(top)
        for fn in (os.path.join(top, e) for e in entries):
            if os.path.basename(fn) == "_link_individual":
                continue

            if os.path.isdir(fn):
                # we'll link the whole dir, unless _link_individual file is present
                if os.path.exists(os.path.join(fn, "_link_individual")):
                    filenames += search_recur(fn)
                    continue
            filenames.append(fn)
        return filenames

    source_paths = search_recur(paths.homelinks())
    relative_paths = [path[len(str(paths.homelinks())):].lstrip('/')
            for path in source_paths]
    target_paths = [(paths.dest / path) for path in relative_paths]
    return [DotfileEntry(*t) for t in zip(source_paths, target_paths, relative_paths)]


def pick_customs():
    filenames = [os.path.basename(f) for f in glob.glob("all_customs/*")]
    print(filenames)

    customs_sets = filenames

    # pick machine
    selection = "NONE"
    while selection not in customs_sets:
        print()
        print("Select a machine:")
        for cs in customs_sets:
            print("  {} ({} files)".format(cs, len(os.listdir("all_customs/" + cs))))
        selection = input("> ")

    # show dotfiles, confirm
    if os.path.exists("customs"):
        print("Removing customs")
        os.remove("customs")

    print("Linking {} -> customs".format(cs))
    os.symlink(cs, "customs")
    print("Done")

def get_parent_dirs(root, target_path):
    dirs = []
    while target_path != root and len(target_path) > 0:
        target_path = os.path.dirname(target_path)
        dirs.append(target_path)
    dirs.reverse()
    return dirs

def make_one_link(entry):
    if os.path.exists(entry.target_path):
        print("Removing {}".format(entry.target_path))
        os.remove(entry.target_path)

    # make parent directories if necessary
    parent_dirs = get_parent_dirs(os.environ['HOME'], entry.target_path)
    for pd in parent_dirs:
        if not os.path.isdir(pd):
            print("Creating directory {}".format(pd))
            os.mkdir(pd)

    print("Linking {} -> {}".format(entry.source_path, entry.target_path))
    os.symlink(entry.source_path, entry.target_path)

def make_links():
    entries = get_dotfile_entries()

    # pick files
    toapply = []
    for entry in entries:
        print("Filename of symlink: {}".format(entry.target_path))

        confirm = "n"
        if not os.path.exists(entry.target_path):
            confirm = get_confirm("Link {} (Y/n)? ".format(entry.relative_path), "y")
        elif not os.path.islink(entry.target_path) or os.readlink(entry.target_path) != entry.source_path:
            print_current_status(entry.target_path)
            confirm = get_confirm("Remove and link {} (Y/n)? ".format(entry.relative_path), "y")

        if confirm == "y":
            toapply.append(entry)

    # make links
    for entry in toapply:
        make_one_link(entry)

    print("Done")
    print_help()

def print_help():
    print("Don't forget to run `git submodule update --init --recursive` for vim plugins")

    print("For Ansible:")
    print("sudo add-apt-repository --update ppa:ansible/ansible")
    print("sudo apt install ansible")

def main(argv=sys.argv):
    selection = ""
    while selection != "x":
        print()
        print("apply.py:")
        print("  c: pick customs")
        print("  l: make symlinks to home directory")
        print("  h: help")

        selection = input("? ")
        if selection == "c":
            pick_customs()
        elif selection == "l":
            make_links()
        elif selection == "h":
            print_help()

    return 0

if __name__ == "__main__":
    sys.exit(main())

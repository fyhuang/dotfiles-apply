import pprint
import tempfile
from pathlib import Path

from apply import *


def test_path_overrides():
    with tempfile.TemporaryDirectory() as td:
        paths = Paths(top=Path("testdata/basic"), dest=td)
        po = paths.path_overrides()

        # Overridden in customs
        assert po["vscode/settings.json"] == "Library/Application Support/Code/User/settings.json"



def test_get_dotfile_entries():
    with tempfile.TemporaryDirectory() as td:
        paths = Paths(top=Path("testdata/basic"), dest=td)
        entries = set(get_dotfile_entries(paths))
        pprint.pp(entries)

        # Ordinary homelink
        assert DotfileEntry(
            source_path=paths.homelinks() / ".gitconfig",
            target_path=paths.dest / ".gitconfig",
            relative_path=Path(".gitconfig"),
        ) in entries

        # _link_individual
        assert DotfileEntry(
            source_path=paths.homelinks() / ".ssh" / "config",
            target_path=paths.dest / ".ssh" / "config",
            relative_path=Path(".ssh/config"),
        ) in entries

        # Overridden in custom paths file
        assert DotfileEntry(
            source_path=paths.homelinks() / "vscode/settings.json",
            target_path=paths.dest / "Library/Application Support/Code/User/settings.json",
            relative_path=Path("vscode/settings.json"),
        ) in entries


def test_get_available_customs():
    with tempfile.TemporaryDirectory() as td:
        paths = Paths(top=Path("testdata/basic"), dest=td)
        customs = set(get_available_customs(paths))
        assert customs == {"custom1", "custom2"}


def test_plan_execute():
    with tempfile.TemporaryDirectory() as td:
        paths = Paths(top=Path("testdata/basic"), dest=td)
        link_ops = LinkOperations(paths)

        # Prepare dest
        (paths.dest / ".bashrc").touch()
        os.symlink(src=paths.homelinks().absolute() / ".zshrc", dst=paths.dest / ".zshrc")

        planned_links = set(link_ops.plan_links())
        pprint.pp(planned_links)

        # Ordinary homelink
        assert Operation(
            action="create",
            source_path=paths.homelinks().absolute() / ".gitconfig",
            dest_path=paths.dest / ".gitconfig",
        ) in planned_links

        # Ordinary homelink, but target already exists
        assert Operation(
            action="replace",
            source_path=paths.homelinks().absolute() / ".bashrc",
            dest_path=paths.dest / ".bashrc",
        ) in planned_links

        # Link already exists
        assert Operation(
            action="noop",
            source_path=None,
            dest_path=paths.dest / ".zshrc",
        ) in planned_links

        # Execute planned links
        for operation in planned_links:
            link_ops.execute_link(operation)

        # Check result
        assert (paths.dest / ".gitconfig").is_symlink()
        assert (paths.dest / ".bashrc").is_symlink()
        assert (paths.dest / ".zshrc").is_symlink()

        assert (paths.dest / ".ssh/config").is_symlink() # _link_individual
        assert (paths.dest / "Library/Application Support/Code/User/settings.json").is_symlink() # custom path_overrides

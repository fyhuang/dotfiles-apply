import pprint
import shutil
import tempfile
from pathlib import Path

import pytest

from apply import *


def test_path_overrides():
    with tempfile.TemporaryDirectory() as td:
        config = MachineConfig(top=Path("testdata/basic"), dest=td)
        po = config.path_overrides()

        # Overridden in customs
        assert po["vscode/settings.json"] == "Library/Application Support/Code/User/settings.json"



def test_get_dotfile_entries():
    with tempfile.TemporaryDirectory() as td:
        config = MachineConfig(top=Path("testdata/basic"), dest=td)
        entries = set(get_dotfile_entries_from(config, config.homelinks()))
        pprint.pp(entries)

        # Ordinary homelink
        assert DotfileEntry(
            source_path=config.homelinks() / ".gitconfig",
            target_path=config.dest / ".gitconfig",
            relative_path=Path(".gitconfig"),
        ) in entries

        # _link_individual
        assert DotfileEntry(
            source_path=config.homelinks() / ".ssh" / "config",
            target_path=config.dest / ".ssh" / "config",
            relative_path=Path(".ssh/config"),
        ) in entries

        # Overridden in custom paths file
        assert DotfileEntry(
            source_path=config.homelinks() / "vscode/settings.json",
            target_path=config.dest / "Library/Application Support/Code/User/settings.json",
            relative_path=Path("vscode/settings.json"),
        ) in entries


def test_get_available_customs():
    with tempfile.TemporaryDirectory() as td:
        config = MachineConfig(top=Path("testdata/basic"), dest=td)
        customs = set(get_available_customs(config))
        assert customs == {"custom1", "custom2"}


def test_plan_execute():
    with tempfile.TemporaryDirectory() as td:
        config = MachineConfig(top=Path("testdata/basic"), dest=td)

        # Prepare dest
        (config.dest / ".bashrc").touch()
        os.symlink(src=config.homelinks().absolute() / ".zshrc", dst=config.dest / ".zshrc")

        planned_links = set(plan_links(config))
        pprint.pp(planned_links)

        # Ordinary homelink
        assert Operation(
            action=Action.CREATE,
            source_path=config.homelinks().absolute() / ".gitconfig",
            dest_path=config.dest / ".gitconfig",
        ) in planned_links

        # Ordinary homelink, but target already exists
        assert Operation(
            action=Action.REPLACE,
            source_path=config.homelinks().absolute() / ".bashrc",
            dest_path=config.dest / ".bashrc",
        ) in planned_links

        # Link already exists
        assert Operation(
            action=Action.NOOP,
            source_path=None,
            dest_path=config.dest / ".zshrc",
        ) in planned_links

        # Execute planned links
        for operation in planned_links:
            execute_operation(operation)

        # Check result
        assert (config.dest / ".gitconfig").is_symlink()
        assert (config.dest / ".bashrc").is_symlink()
        assert (config.dest / ".zshrc").is_symlink()

        assert (config.dest / ".ssh/config").is_symlink() # _link_individual
        assert (config.dest / "Library/Application Support/Code/User/settings.json").is_symlink() # custom path_overrides


def test_apply_plan():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        source = td / "src"
        source.mkdir()
        (source / "a.txt").touch()
        (source / "b.txt").touch()

        plan = [
            Operation(Action.CREATE, source / "a.txt", td / "dest" / "a.txt"),
            Operation(Action.CREATE, source / "b.txt", td / "dest" / "b.txt"),
        ]
        apply_plan(plan)

        assert (td / "dest" / "a.txt").is_symlink()
        assert (td / "dest" / "b.txt").is_symlink()

        # Replace one, noop the other
        plan2 = [
            Operation(Action.REPLACE, source / "a.txt", td / "dest" / "a.txt"),
            Operation(Action.NOOP, None, td / "dest" / "b.txt"),
        ]
        apply_plan(plan2)
        assert (td / "dest" / "a.txt").is_symlink()
        assert (td / "dest" / "b.txt").is_symlink()

        # Wipe a directory
        wipe_target = td / "dest" / "subdir"
        wipe_target.mkdir()
        (wipe_target / "junk.txt").touch()
        apply_plan([Operation(Action.WIPE_DIR, None, wipe_target)])
        assert not wipe_target.exists()


################################
# Tag tests (using testdata/tags/)
################################

TAGS_TESTDATA = Path("testdata/tags")


def test_tags_empty():
    config = MachineConfig(top=TAGS_TESTDATA, customs_name="machine-base")
    assert config.tags() == []


def test_tags():
    config = MachineConfig(top=TAGS_TESTDATA, customs_name="machine-tagA")
    assert config.tags() == ["tagA"]


def test_tags_multiple():
    config = MachineConfig(top=TAGS_TESTDATA, customs_name="machine-tagAB")
    assert config.tags() == ["tagA", "tagB"]


def _make_tags_repo(td: Path) -> Path:
    """Copy testdata/tags into a temp dir and return the repo path."""
    repo = td / "repo"
    shutil.copytree(TAGS_TESTDATA, repo, symlinks=True)
    return repo


def test_build_include_d_base_only():
    with tempfile.TemporaryDirectory() as td:
        repo = _make_tags_repo(Path(td))
        config = MachineConfig(top=repo, customs_name="machine-base")
        apply_plan(plan_include_d(config))

        include_d = repo / "include.d"
        assert (include_d / "common.sh").is_symlink()
        assert not (include_d / "fn").exists()


def test_build_include_d_with_tag():
    with tempfile.TemporaryDirectory() as td:
        repo = _make_tags_repo(Path(td))
        config = MachineConfig(top=repo, customs_name="machine-tagA")
        apply_plan(plan_include_d(config))

        include_d = repo / "include.d"
        assert (include_d / "common.sh").is_symlink()
        assert (include_d / "fn" / "tagA.sh").is_symlink()
        assert not (include_d / "fn" / "tagB.sh").exists()


def test_build_include_d_multiple_tags():
    with tempfile.TemporaryDirectory() as td:
        repo = _make_tags_repo(Path(td))
        config = MachineConfig(top=repo, customs_name="machine-tagAB")
        apply_plan(plan_include_d(config))

        include_d = repo / "include.d"
        assert (include_d / "common.sh").is_symlink()
        assert (include_d / "fn" / "tagA.sh").is_symlink()
        assert (include_d / "fn" / "tagB.sh").is_symlink()


def test_build_include_d_collision():
    with tempfile.TemporaryDirectory() as td:
        repo = _make_tags_repo(Path(td))
        config = MachineConfig(top=repo, customs_name="machine-collision")

        with pytest.raises(Exception, match="Conflict.*common.sh"):
            apply_plan(plan_include_d(config))


################################
# Tagged homelinks tests
################################

def test_get_all_dotfile_entries_base_only():
    with tempfile.TemporaryDirectory() as td:
        config = MachineConfig(top=TAGS_TESTDATA, dest=td, customs_name="machine-base")
        entries = get_all_dotfile_entries(config)
        relpaths = {e.relative_path for e in entries}
        assert relpaths == {Path(".profile")}


def test_get_all_dotfile_entries_with_tag():
    with tempfile.TemporaryDirectory() as td:
        config = MachineConfig(top=TAGS_TESTDATA, dest=td, customs_name="machine-tagA")
        entries = get_all_dotfile_entries(config)
        relpaths = {e.relative_path for e in entries}
        assert relpaths == {Path(".profile"), Path(".tagrc")}


################################
# CLI helpers tests
################################

def test_ensure_customs_symlink_create():
    with tempfile.TemporaryDirectory() as td:
        repo = _make_tags_repo(Path(td))
        config = MachineConfig(top=repo, customs_name="machine-tagA")
        apply_plan(plan_customs_symlink(config))

        customs_link = repo / "customs"
        assert customs_link.is_symlink()
        assert customs_link.readlink() == Path("all_customs/machine-tagA")


def test_ensure_customs_symlink_update():
    with tempfile.TemporaryDirectory() as td:
        repo = _make_tags_repo(Path(td))

        # Create initial symlink to a different machine
        customs_link = repo / "customs"
        customs_link.symlink_to(Path("all_customs/machine-base"))
        assert customs_link.readlink() == Path("all_customs/machine-base")

        # Update to machine-tagA
        config = MachineConfig(top=repo, customs_name="machine-tagA")
        apply_plan(plan_customs_symlink(config))

        assert customs_link.readlink() == Path("all_customs/machine-tagA")


################################
# Bundle tests
################################

def test_generate_bundle():
    with tempfile.TemporaryDirectory() as td:
        config = MachineConfig(top=TAGS_TESTDATA, dest=td, customs_name="machine-tagA")
        bundle = generate_bundle(config)

        # Valid shell script
        assert bundle.startswith("#!/bin/sh\n")
        assert "set -e" in bundle

        # -v flag support
        assert 'if [ "$1" = "-v" ]' in bundle
        assert 'echo "$1"' in bundle

        # Header
        assert "# Customs: machine-tagA" in bundle
        assert "# Tags: tagA" in bundle

        # Homelinks: base + tagA
        assert '"$HOME/.profile"' in bundle
        assert '"$HOME/.tagrc"' in bundle

        # Includes: base + tagA
        assert '"$HOME/dotfiles/include.d/common.sh"' in bundle
        assert '"$HOME/dotfiles/include.d/fn/tagA.sh"' in bundle

        # tagB should NOT be present
        assert "tagB" not in bundle

        # Customs files
        assert '"$HOME/dotfiles/customs/machinename"' in bundle
        assert '"$HOME/dotfiles/customs/tags"' in bundle

        # Base64 content decodes correctly
        import base64
        profile_content = Path("testdata/tags/homelinks/.profile").read_bytes()
        profile_b64 = base64.b64encode(profile_content).decode()
        assert profile_b64 in bundle

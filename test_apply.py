import tempfile
from pathlib import Path

from apply import *

def test_get_dotfile_entries():
    with tempfile.TemporaryDirectory() as td:
        paths = Paths(top=Path("testdata/basic"), dest=td)
        print(get_dotfile_entries(paths))
    assert False

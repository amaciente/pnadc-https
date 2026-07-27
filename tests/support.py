from contextlib import contextmanager
from pathlib import Path
import shutil
import uuid


@contextmanager
def workspace():
    """Use an existing writable directory on managed Windows workspaces."""
    root = Path(__file__).parent / "_work"
    path = root / uuid.uuid4().hex
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)

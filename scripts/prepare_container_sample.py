"""Create the public sample database for a read-only container image."""
from pathlib import Path
import sys

from incidentcourt.sample import ensure_sample_db


def prepare(path):
    database = ensure_sample_db(Path(path))
    # The generated fixture is public; the runtime container uses a different UID
    # from the image build. Keep it readable to that UID without granting writes.
    database.chmod(0o444)
    return database


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python -m scripts.prepare_container_sample PATH')
    prepare(sys.argv[1])

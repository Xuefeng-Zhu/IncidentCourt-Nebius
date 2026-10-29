"""Explicit one-time volume bootstrap; does not serve HTTP or call a provider."""
import argparse
import os
from pathlib import Path

from incidentcourt.quota import Quota
from deploy.instacloud.bootstrap_guard import block_outbound, reject_credentials


def initialize_new_volume(data_root):
    data_root = Path(data_root)
    if data_root.is_symlink() or not os.path.ismount(data_root):
        raise ValueError('The expected persistent volume is not mounted.')
    if os.geteuid() != 10001:
        raise ValueError('Initialize the volume as the unprivileged service UID 10001.')
    reject_credentials(os.environ)
    target = data_root/'incidentcourt'
    # Exclusive creation prevents reset, including after an interrupted bootstrap.
    target.mkdir(mode=0o700, exist_ok=False)
    receipts = target/'provider-receipts'
    receipts.mkdir(mode=0o700, exist_ok=False)
    Quota.initialize(target/'quota.sqlite3')
    # Persist directory entries as far as the mounted filesystem supports it.
    for directory in (receipts, target, data_root):
        fd = os.open(directory, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    return target


def main():
    parser = argparse.ArgumentParser(description='One-time, non-serving volume initialization')
    parser.add_argument('--initialize-new-volume', action='store_true')
    args = parser.parse_args()
    if not args.initialize_new_volume:
        parser.error('Explicit --initialize-new-volume is required')
    block_outbound()
    initialize_new_volume('/data')
    print('Initialized a new private ledger and receipt directory.')


if __name__ == '__main__': main()

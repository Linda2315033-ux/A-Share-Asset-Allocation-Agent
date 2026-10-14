"""Restore private A-share research data from a GitHub Release.

Requires GitHub CLI (`gh`) authenticated with access to the private repository.
On GitHub Actions set GH_TOKEN to a fine-grained PAT with Contents: Read on
only the private data repository. This script is intentionally read-only.
"""
import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import tempfile

REPO = 'Linda2315033-ux/a-share-agent-private-data'
TAG = 'data-bootstrap-v1'
HISTORY_NAME = 'stock_history_backup.tar.gz'
AUX_NAME = 'stock_auxiliary_data.tar.gz'
HISTORY_SHA256 = '04584cdf8bb89cbd478305fea2784e8d59a788752744a50b20c1c70bbbb59117'
EXPECTED_PAIRS = 3189
AUX_FILES = {
    'data/stocks/universe.csv',
    'data/stocks/universe_metadata.json',
    'data/stocks/market/sh000300.csv',
}


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def inspect_archive(path, kind):
    """Reject unsafe paths, links, unexpected members, and duplicate file names."""
    seen = set()
    raw, qfq = set(), set()
    with tarfile.open(path, 'r:gz') as archive:
        members = archive.getmembers()
        for member in members:
            name = member.name.removeprefix('./').rstrip('/')
            p = PurePosixPath(name)
            if not name or p.is_absolute() or '..' in p.parts or '\\' in name:
                raise ValueError(f'Unsafe archive path: {member.name}')
            if not (member.isfile() or member.isdir()):
                raise ValueError(f'Unsupported archive member: {member.name}')
            if name in seen:
                raise ValueError(f'Duplicate archive member: {name}')
            seen.add(name)
            if kind == 'history':
                if p.parts[0] != 'mainboard_history_v1':
                    raise ValueError(f'Unexpected history path: {name}')
                if member.isfile():
                    if len(p.parts) != 3 or p.parts[1] not in ('raw', 'qfq') or p.suffix != '.csv':
                        raise ValueError(f'Unexpected history file: {name}')
                    (raw if p.parts[1] == 'raw' else qfq).add(p.name)
            else:
                if member.isfile() and name not in AUX_FILES:
                    raise ValueError(f'Unexpected auxiliary file: {name}')
        if kind == 'history':
            if len(raw) != EXPECTED_PAIRS or raw != qfq:
                raise ValueError(f'History pairs invalid: raw={len(raw)} qfq={len(qfq)}')
            print(f'ARCHIVE_VALIDATED: {EXPECTED_PAIRS} raw/qfq pairs', flush=True)
        elif not AUX_FILES.issubset(seen):
            raise ValueError(f'Missing auxiliary files: {AUX_FILES - seen}')
        else:
            print('AUXILIARY_ARCHIVE_VALIDATED: 3 required files', flush=True)
    return members


def extract(path, destination, kind):
    members = inspect_archive(path, kind)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, 'r:gz') as archive:
        for member in members:
            rel = member.name.removeprefix('./').rstrip('/')
            target = destination.joinpath(*PurePosixPath(rel).parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            # Avoid archive-controlled ownership/modes; no tarfile.extractall.
            with archive.extractfile(member) as source, target.open('wb') as output:
                while True:
                    block = source.read(1024 * 1024)
                    if not block:
                        break
                    output.write(block)


def restore(root):
    if not os.environ.get('GH_TOKEN') and not os.environ.get('GITHUB_TOKEN'):
        print('No GH_TOKEN set; using existing local gh authentication.', flush=True)
    with tempfile.TemporaryDirectory(prefix='github-market-data-') as folder:
        tmp = Path(folder)
        cmd = ['gh', 'release', 'download', TAG, '--repo', REPO,
               '--dir', str(tmp), '--pattern', '*.tar.gz']
        print('Downloading private release assets...', flush=True)
        subprocess.run(cmd, check=True)
        history, auxiliary = tmp / HISTORY_NAME, tmp / AUX_NAME
        if not history.is_file() or not auxiliary.is_file():
            raise FileNotFoundError('Private release is missing one or both backup assets')
        actual = sha256(history)
        if actual != HISTORY_SHA256:
            raise ValueError(f'History SHA-256 mismatch: {actual}')
        print('HISTORY_SHA256_OK', flush=True)
        # Validate both archives before changing the working directory.
        inspect_archive(history, 'history')
        inspect_archive(auxiliary, 'auxiliary')
        target = root / 'data' / 'stocks'
        if (target / 'mainboard_history_v1').exists():
            raise FileExistsError('Refusing to overwrite existing market history directory')
        if any((root / f).exists() for f in AUX_FILES):
            raise FileExistsError('Refusing to overwrite existing auxiliary market data')
        extract(history, target, 'history')
        extract(auxiliary, root, 'auxiliary')
    hist = root / 'data' / 'stocks' / 'mainboard_history_v1'
    raw = list((hist / 'raw').glob('*.csv'))
    qfq = list((hist / 'qfq').glob('*.csv'))
    if len(raw) != EXPECTED_PAIRS or len(qfq) != EXPECTED_PAIRS:
        raise ValueError('Restored CSV counts do not match expected pair count')
    for rel in AUX_FILES:
        if not (root / rel).is_file():
            raise FileNotFoundError(f'Missing restored file: {rel}')
    print('PRIVATE_DATA_RESTORE_OK: 3189 raw/qfq pairs and 3 auxiliary files', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['restore'])
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    restore(args.root.resolve())

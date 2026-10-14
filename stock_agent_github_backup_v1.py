"""Create a NEW, immutable private GitHub Release backup from validated local data.

Run in GitHub Actions with GH_TOKEN scoped to the private data repository
(Contents: Read and write). Never prints credentials. Does not change bootstrap.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone

REPO = 'Linda2315033-ux/a-share-agent-private-data'
HISTORY = Path('data/stocks/mainboard_history_v1')
AUX = [Path('data/stocks/universe.csv'), Path('data/stocks/universe_metadata.json'),
       Path('data/stocks/market/sh000300.csv')]
EXPECTED = 3189


def run(*args):
    return subprocess.run(['gh', *args], check=True, text=True, capture_output=True)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def validate(root):
    hist = root / HISTORY
    raw = {p.name for p in (hist / 'raw').glob('*.csv')}
    qfq = {p.name for p in (hist / 'qfq').glob('*.csv')}
    if len(raw) != EXPECTED or raw != qfq:
        raise ValueError(f'Unexpected history pairs: raw={len(raw)}, qfq={len(qfq)}')
    for f in AUX:
        if not (root / f).is_file():
            raise FileNotFoundError(root / f)
    return len(raw)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--date', required=True, help='Verified expected trade date YYYY-MM-DD')
    parser.add_argument('--confirm', action='store_true')
    args = parser.parse_args()
    if not args.confirm:
        parser.error('Requires --confirm')
    if not os.environ.get('GH_TOKEN'):
        parser.error('GH_TOKEN missing')
    date = datetime.strptime(args.date, '%Y-%m-%d').date().isoformat()
    root = args.root.resolve()
    validate(root)
    # Unique version per execution, never replace an existing release or asset.
    run_id = os.environ.get('GITHUB_RUN_ID', 'local')
    attempt = os.environ.get('GITHUB_RUN_ATTEMPT', '1')
    tag = f'market-data-{date}-run-{run_id}-{attempt}'
    try:
        run('release', 'view', tag, '--repo', REPO)
    except subprocess.CalledProcessError as exc:
        if '404' not in exc.stderr and 'not found' not in exc.stderr.lower():
            raise RuntimeError('Cannot determine whether backup tag exists; refusing upload') from exc
    else:
        raise FileExistsError(f'Release already exists: {tag}')
    with tempfile.TemporaryDirectory(prefix='private-data-backup-') as tmp:
        tmp = Path(tmp)
        history = tmp / 'stock_history_backup.tar.gz'
        auxiliary = tmp / 'stock_auxiliary_data.tar.gz'
        with tarfile.open(history, 'w:gz') as tar:
            tar.add(root / HISTORY, arcname='mainboard_history_v1', recursive=True)
        with tarfile.open(auxiliary, 'w:gz') as tar:
            for rel in AUX:
                tar.add(root / rel, arcname=rel.as_posix())
        manifest = {
            'tag': tag, 'expected_trade_date': date,
            'created_utc': datetime.now(timezone.utc).isoformat(),
            'pairs': EXPECTED,
            'files': {p.name: {'sha256': digest(p), 'bytes': p.stat().st_size}
                      for p in (history, auxiliary)},
            'research_only': True, 'formal_publication_allowed': False,
        }
        mf = tmp / 'backup_manifest.json'
        mf.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        run('release', 'create', tag, str(history), str(auxiliary), str(mf),
            '--repo', REPO, '--target', 'main', '--title', f'Private research snapshot {date}',
            '--notes', 'Private research cache backup; not a public signal.', '--latest=false')
        details = json.loads(run('release', 'view', tag, '--repo', REPO, '--json', 'assets').stdout)
        uploaded = {a['name']: a['size'] for a in details['assets']}
        for file in (history, auxiliary, mf):
            if uploaded.get(file.name) != file.stat().st_size:
                raise RuntimeError(f'Uploaded asset missing or size mismatch: {file.name}')
        print('PRIVATE_VERSIONED_BACKUP_OK:', tag)
        print('BACKUP_MANIFEST_SHA256:', digest(mf))


if __name__ == '__main__':
    main()

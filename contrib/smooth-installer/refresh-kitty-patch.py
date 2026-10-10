#!/usr/bin/env python3
"""Refresh the committed + working-tree Kitty changes against an explicit base."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('repository', nargs='?', default='../kitty')
parser.add_argument('--base', help='Upstream base tag/commit; defaults to the recorded manifest base')
args = parser.parse_args()
root = Path(args.repository).resolve()
assets = Path(__file__).resolve().parent
manifest = json.loads((assets / 'manifest.json').read_text())
base = subprocess.check_output(['git', '-C', str(root), 'rev-parse', (args.base or manifest['kitty_base']) + '^{commit}'], text=True).strip()
# No HEAD endpoint: includes committed custom changes and tracked working changes.
patch = subprocess.check_output(['git', '-C', str(root), 'diff', '--binary', base])
if not patch or b'KITTY_SMOOTH_NVIM' not in patch or b'case 9926:' not in patch:
    raise SystemExit('Expected the smooth Kitty bridge and bounce controls in the diff against the base.')
(assets / 'kitty.patch').write_bytes(patch)
manifest.update(kitty_base=base, kitty_patch_sha256=hashlib.sha256(patch).hexdigest())
(assets / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print('Updated pinned Kitty patch:', base)

#!/usr/bin/env python3
"""Refresh the pinned working-tree Kitty patch; does not commit or publish."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else '../kitty').resolve()
assets = Path(__file__).resolve().parent
base = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
patch = subprocess.check_output(['git', '-C', str(root), 'diff', '--binary', 'HEAD'])
if not patch or b'KITTY_SMOOTH_NVIM' not in patch or b'case 9926:' not in patch:
    raise SystemExit('Expected the smooth Kitty bridge and bounce controls in the working-tree diff.')
(assets / 'kitty.patch').write_bytes(patch)
(assets / 'manifest.json').write_text(json.dumps(dict(
    kitty_url='https://github.com/idelice/kitty.git', kitty_base=base,
    kitty_patch_sha256=hashlib.sha256(patch).hexdigest()), indent=2) + '\n')
print('Updated pinned Kitty patch:', base)

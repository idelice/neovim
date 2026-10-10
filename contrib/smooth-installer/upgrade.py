#!/usr/bin/env python3
"""Upgrade custom changes onto stable upstream tags in isolated repositories."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import uuid

SOURCE = Path(__file__).resolve().parents[2]
NVIM_URL = 'https://github.com/neovim/neovim.git'
KITTY_URL = 'https://github.com/kovidgoyal/kitty.git'
IDENTITY = ['-c', 'user.name=Smooth upgrade', '-c', 'user.email=smooth-upgrade@localhost']


def git(repo, *args, check=True):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True)
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result


def latest_tag(url):
    # Ignore nightly, prerelease, release-candidate and arbitrary named tags.
    output = subprocess.check_output(['git', 'ls-remote', '--tags', '--refs', url], text=True)
    candidates = []
    for line in output.splitlines():
        _, ref = line.split()
        tag = ref.removeprefix('refs/tags/')
        match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', tag)
        if match:
            candidates.append((tuple(map(int, match.groups())), tag))
    if not candidates:
        raise RuntimeError(f'No stable version tags found at {url}')
    return max(candidates)[1]


def apply_patch(repo, patch):
    result = git(repo, 'apply', '--3way', '--index', str(patch), check=False)
    if result.returncode:
        paths = git(repo, 'diff', '--name-only', '--diff-filter=U').stdout.strip()
        raise RuntimeError(f'CONFLICT / patch could not be applied in {repo}\n'
                           f'{paths or result.stderr.strip()}\n'
                           'Stopped. Your original checkout and active installation are unchanged.')


def commit(repo, message):
    git(repo, *IDENTITY, 'commit', '-m', message + '\n\nAI-assisted')


def prepare(source, work, nvim_url=NVIM_URL, kitty_url=KITTY_URL):
    if git(source, 'status', '--porcelain').stdout.strip():
        raise RuntimeError('Commit your Neovim changes first; the upgrade requires a clean checkout.')
    assets = source / 'contrib/smooth-installer'
    manifest = json.loads((assets / 'manifest.json').read_text())
    if 'neovim_base' not in manifest:
        raise RuntimeError('Missing neovim_base in manifest; update the upgrade tools first.')
    patch = assets / 'kitty.patch'
    if hashlib.sha256(patch.read_bytes()).hexdigest() != manifest['kitty_patch_sha256']:
        raise RuntimeError('Kitty patch checksum mismatch.')
    targets = dict(neovim=latest_tag(nvim_url), kitty=latest_tag(kitty_url))
    print(f'Stable targets: Neovim {targets["neovim"]}, Kitty {targets["kitty"]}', flush=True)
    work.mkdir(parents=True)
    nvim, kitty = work / 'neovim', work / 'kitty'
    subprocess.run(['git', 'clone', '--quiet', '--no-hardlinks', str(source), str(nvim)], check=True)
    nvim_patch = work / 'neovim.patch'
    nvim_patch.write_bytes(subprocess.check_output(['git', '-C', str(source), 'diff', '--binary',
                                                  manifest['neovim_base'], 'HEAD']))
    git(nvim, 'fetch', '--no-tags', nvim_url, f'refs/tags/{targets["neovim"]}')
    nvim_base = git(nvim, 'rev-parse', 'FETCH_HEAD^{commit}').stdout.strip()
    git(nvim, 'checkout', '--detach', nvim_base)
    apply_patch(nvim, nvim_patch)
    commit(nvim, f'Apply smooth terminal integration to {targets["neovim"]}')

    kitty.mkdir()
    git(kitty, 'init', '--quiet')
    # Fetch only the recorded base and the selected stable tag, never a moving branch.
    git(kitty, 'fetch', '--no-tags', manifest['kitty_url'], manifest['kitty_base'])
    git(kitty, 'checkout', '--detach', 'FETCH_HEAD')
    apply_patch(kitty, patch)
    commit(kitty, 'Record smooth Kitty changes')
    git(kitty, 'fetch', '--no-tags', kitty_url, f'refs/tags/{targets["kitty"]}')
    kitty_base = git(kitty, 'rev-parse', 'FETCH_HEAD^{commit}').stdout.strip()
    git(kitty, 'checkout', '--detach', kitty_base)
    apply_patch(kitty, patch)
    commit(kitty, f'Apply smooth renderer to {targets["kitty"]}')

    new_assets = nvim / 'contrib/smooth-installer'
    new_patch = subprocess.check_output(['git', '-C', str(kitty), 'diff', '--binary', kitty_base, 'HEAD'])
    (new_assets / 'kitty.patch').write_bytes(new_patch)
    manifest.update(neovim_base=nvim_base, kitty_base=kitty_base, kitty_url=kitty_url,
                    neovim_tag=targets['neovim'], kitty_tag=targets['kitty'],
                    kitty_patch_sha256=hashlib.sha256(new_patch).hexdigest())
    (new_assets / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    git(nvim, 'add', 'contrib/smooth-installer/kitty.patch', 'contrib/smooth-installer/manifest.json')
    commit(nvim, 'Pin stable upgrade snapshot')
    # Local recovery branch; nothing is pushed or merged into the user's checkout.
    git(nvim, 'switch', '-c', 'codex/smooth-stable-upgrade')
    return nvim, targets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true', help='Prepare stable sources without building/installing')
    parser.add_argument('--prefix', type=Path, default=Path.home() / '.local/share/kitty-smooth')
    parser.add_argument('--app-dir', type=Path, default=Path.home() / 'Applications')
    args = parser.parse_args()
    prefix = args.prefix.expanduser().resolve()
    if git(SOURCE, 'status', '--porcelain').stdout.strip():
        raise RuntimeError('Commit your Neovim changes first; the upgrade requires a clean checkout.')
    # After a successful upgrade, reuse its adapted patch on subsequent upgrades.
    state_file = prefix / 'upgrade-state.json'
    source = SOURCE
    input_head = git(SOURCE, 'rev-parse', 'HEAD').stdout.strip()
    if state_file.exists():
        state = json.loads(state_file.read_text())
        if state['input_head'] == input_head and Path(state['source']).is_dir():
            source = Path(state['source'])
    work = prefix.parent / 'kitty-smooth-upgrades' / (datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    prepared, targets = prepare(source, work)
    print(f'Prepared sources: {prepared}', flush=True)
    command = [str(prepared / 'contrib/install-smooth-macos'), '--prefix', str(prefix),
               '--app-dir', str(args.app_dir.expanduser().resolve())]
    if args.prepare_only:
        print('To build/install: ' + shlex.join(command))
        return
    # The installer builds and smoke-tests both forks before switching current.
    subprocess.run(command, check=True)
    state_file.write_text(json.dumps(dict(input_head=input_head, source=str(prepared), targets=targets), indent=2) + '\n')
    print('Upgrade installed. Close old Kitty Smooth windows and reopen the app.\n'
          'Rollback: ./contrib/install-smooth-macos --rollback')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'Upgrade stopped: {exc}', file=sys.stderr)
        sys.exit(1)

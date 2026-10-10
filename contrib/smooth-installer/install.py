#!/usr/bin/env python3
"""One-clone, source-backed installation for Apple Silicon macOS."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import pwd
import shlex
import signal
import shutil
import subprocess
import sys
import uuid

SOURCE = Path(__file__).resolve().parents[2]
ASSETS = Path(__file__).resolve().parent
BEGIN = '# >>> kitty-smooth managed PATH >>>'
END = '# <<< kitty-smooth managed PATH <<<'


def run(args, **kwargs):
    print('+', shlex.join(map(str, args)), flush=True)
    timeout = kwargs.pop('timeout', None)
    process = subprocess.Popen(list(map(str, args)), start_new_session=True, **kwargs)
    try:
        result = process.wait(timeout=timeout)
        if result:
            raise subprocess.CalledProcessError(result, args)
        return subprocess.CompletedProcess(args, result)
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        raise


def script(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!/bin/sh\nset -eu\n' + body)
    path.chmod(0o755)


def remove_block(text):
    if BEGIN not in text:
        if END in text:
            raise RuntimeError('Unmatched managed shell block; refusing to edit it.')
        return text
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise RuntimeError('Ambiguous managed shell blocks; refusing to edit them.')
    start, end = text.index(BEGIN), text.index(END) + len(END)
    if end < start:
        raise RuntimeError('Malformed managed shell block.')
    if text[end:end + 1] == '\n':
        end += 1
    return text[:start] + text[end:]


def shell_block(prefix):
    return (BEGIN + '\nif [[ ${KITTY_SMOOTH_NVIM:-} == 1 ]]; then\n'
            '  unalias nvim 2>/dev/null || true\n'
            '  unfunction nvim 2>/dev/null || true\n'
            f'  export PATH={shlex.quote(str(prefix / "current/bin"))}:"$PATH"\n'
            'fi\n' + END + '\n')


def copy_source(destination):
    # Include tracked working-tree changes, without caches or personal untracked files.
    paths = subprocess.check_output(['git', '-C', str(SOURCE), 'ls-files', '-z']).split(b'\0')
    paths += [b'contrib/smooth-nvim.lua']
    for name in set(paths):
        if not name:
            continue
        relative = Path(os.fsdecode(name))
        source, target = SOURCE / relative, destination / relative
        if not source.exists() and not source.is_symlink():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            target.symlink_to(os.readlink(source))
        elif source.is_file():
            shutil.copy2(source, target)


def write_wrappers(release, compiler):
    q = shlex.quote
    script(release / 'bin/nvim', f'''export VIMRUNTIME={q(str(release / 'neovim/share/nvim/runtime'))}
if [ "${{KITTY_SMOOTH_NVIM-}}" = 1 ]; then
  export NVIM_KITTY_SMOOTH=1
  export NVIM_KITTY_SMOOTH_LUA={q(str(release / 'smooth-nvim.lua'))}
  exec {q(str(release / 'neovim/bin/nvim'))} -c 'lua dofile(vim.env.NVIM_KITTY_SMOOTH_LUA)' "$@"
fi
unset NVIM_KITTY_SMOOTH
exec {q(str(release / 'neovim/bin/nvim'))} "$@"
''')
    script(release / 'bin/kitty', f'''export SLANGC={q(str(compiler))}
exec {q(str(release / 'src/kitty/kitty/launcher/kitty'))} -o cursor_trail=0 -o input_delay=1 -o sync_to_monitor=yes -o 'shell=/bin/zsh -l' "$@"
''')


def write_app(app, prefix, kitty_source):
    marker = app / '.kitty-smooth-prefix'
    if app.exists() and (not marker.exists() or marker.read_text() != str(prefix)):
        raise RuntimeError(f'Refusing to replace an unrelated app: {app}')
    (app / 'Contents/MacOS').mkdir(parents=True, exist_ok=True)
    resources = app / 'Contents/Resources'
    resources.mkdir(exist_ok=True)
    icon = kitty_source / 'kitty/launcher/kitty.app/Contents/Resources/kitty.icns'
    if icon.exists():
        shutil.copy2(icon, resources / 'kitty.icns')
    info = dict(CFBundleIdentifier='local.kitty-smooth', CFBundleName='Kitty Smooth',
                CFBundleDisplayName='Kitty Smooth', CFBundleExecutable='kitty-smooth',
                CFBundlePackageType='APPL', CFBundleVersion='1', CFBundleIconFile='kitty.icns',
                NSHighResolutionCapable=True)
    (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    script(app / 'Contents/MacOS/kitty-smooth',
           f'exec {shlex.quote(str(prefix / "current/bin/kitty"))} "$@"\n')
    marker.write_text(str(prefix))


def verify_manifest():
    manifest = json.loads((ASSETS / 'manifest.json').read_text())
    patch = ASSETS / 'kitty.patch'
    if hashlib.sha256(patch.read_bytes()).hexdigest() != manifest['kitty_patch_sha256']:
        raise RuntimeError('Kitty patch checksum mismatch.')
    if 'NVIM_KITTY_SMOOTH' not in (SOURCE / 'src/nvim/ui_compositor.c').read_text():
        raise RuntimeError('This checkout does not contain the Neovim smooth renderer changes.')
    return manifest


def compiler_path():
    # Kitty's official app supplies the compiler and its matching dylibs.
    for app in (Path('/Applications/kitty.app'), Path.home() / 'Applications/kitty.app'):
        compiler = app / 'Contents/MacOS/slangc'
        if compiler.is_file() and os.access(compiler, os.X_OK):
            return compiler
    # Preserve an existing old/manual Kitty app rather than overwriting it.
    if Path('/Applications/kitty.app').exists():
        raise RuntimeError('Existing Kitty lacks slangc. Update stock Kitty, then rerun the installer.')
    run(['brew', 'install', '--cask', 'kitty'])
    compiler = Path('/Applications/kitty.app/Contents/MacOS/slangc')
    if not compiler.exists():
        raise RuntimeError('The installed stock Kitty does not provide slangc.')
    return compiler


def install(args, manifest):
    prefix = args.prefix
    prefix.mkdir(parents=True, exist_ok=True)
    marker = prefix / '.kitty-smooth-install'
    if any(prefix.iterdir()) and not marker.exists():
        raise RuntimeError(f'Refusing to use a nonempty unmanaged folder: {prefix}')
    marker.write_text('managed source-backed install\n')
    prefix.chmod(0o700)
    lock = prefix / '.install-lock'
    lock.mkdir()  # An existing lock prevents concurrent installers.
    try:
        compiler = compiler_path()
        shell = pwd.getpwuid(os.getuid()).pw_shell
        if Path(shell).name != 'zsh':
            raise RuntimeError('This installer currently supports zsh login shells.')
        zshrc = Path(os.environ.get('ZDOTDIR', str(Path.home()))) / '.zshrc'
        zshrc = zshrc.resolve()
        old_rc = zshrc.read_text() if zshrc.exists() else ''
        clean_rc = remove_block(old_rc)
        current = prefix / 'current'
        if current.exists() and not current.is_symlink():
            raise RuntimeError('current is not a managed symlink.')
        app = args.app_dir / 'Kitty Smooth.app'
        if app.exists() and (not (app / '.kitty-smooth-prefix').exists()
                             or (app / '.kitty-smooth-prefix').read_text() != str(prefix)):
            raise RuntimeError(f'An unrelated app already exists at {app}')
        release = prefix / 'releases' / (dt.datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
        release.mkdir(parents=True)
        src = release / 'src'
        src.mkdir()
        nvim = src / 'neovim'
        copy_source(nvim)
        shutil.copy2(SOURCE / 'contrib/smooth-nvim.lua', release / 'smooth-nvim.lua')
        kitty = src / 'kitty'
        run(['git', 'clone', '--no-checkout', manifest['kitty_url'], kitty])
        run(['git', 'checkout', '--detach', manifest['kitty_base']], cwd=kitty)
        run(['git', 'apply', '--check', ASSETS / 'kitty.patch'], cwd=kitty)
        run(['git', 'apply', ASSETS / 'kitty.patch'], cwd=kitty)
        run(['./dev.sh', 'deps'], cwd=kitty)
        deps = kitty / 'dependencies/darwin-arm64'
        env = dict(os.environ, DEVELOP_ROOT=str(deps), SLANGC=str(compiler),
                   PKG_CONFIG_PATH=str(deps / 'lib/pkgconfig'), GOMAXPROCS='4',
                   CMAKE_BUILD_PARALLEL_LEVEL='4',
                   PATH=str(deps / 'bin') + ':' + os.environ['PATH'])
        python = deps / 'python/Python.framework/Versions/Current/bin/python3'
        # Kitty's build scheduler uses os.cpu_count(); cap it for laptop thermals.
        build_code = "import os,runpy,sys; os.cpu_count=lambda:4; sys.argv=['setup.py','build']; runpy.run_path('setup.py',run_name='__main__')"
        run([python, '-c', build_code], cwd=kitty, env=env)
        if not (kitty / 'kitty/launcher/kitty.app/Contents/MacOS/kitten').is_file():
            raise RuntimeError('Kitty helper build did not finish.')
        run(['make', '-j4', 'CMAKE_BUILD_TYPE=Release',
             f'CMAKE_EXTRA_FLAGS=-DCMAKE_INSTALL_PREFIX={release / "neovim"}'], cwd=nvim)
        run(['cmake', '--install', 'build'], cwd=nvim)
        write_wrappers(release, compiler)
        test_env = dict(os.environ, KITTY_SMOOTH_NVIM='1')
        run([release / 'bin/nvim', '--clean', '--headless',
             '+lua assert(vim.fn.exists(":SmoothBounce") == 2)', '+qa!'], env=test_env, timeout=30)
        run([kitty / 'kitty/launcher/kitty', '--version'], env=env, timeout=30)
        (release / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        # Only wire the app and shell after both builds and checks have succeeded.
        backups = prefix / 'backups'
        backups.mkdir(exist_ok=True)
        backup = backups / (release.name + '.zshrc')
        backup.write_text(old_rc)
        backup.chmod(0o600)
        write_app(app, prefix, kitty)
        zshrc.parent.mkdir(parents=True, exist_ok=True)
        zshrc.write_text(clean_rc.rstrip('\n') + '\n\n' + shell_block(prefix))
        previous = prefix / 'current'
        if previous.is_symlink():
            (prefix / 'previous-target').write_text(os.readlink(previous))
        elif previous.exists():
            raise RuntimeError('current is not a managed symlink.')
        new_link = prefix / 'next'
        if new_link.is_symlink():
            new_link.unlink()
        new_link.symlink_to(release)
        new_link.replace(previous)
        print(f'\nInstalled. Open {app}, then run: nvim .\n'
              f'Stock terminals remain unchanged. Shell backup: {backup}\n'
              'Keep the managed installation folder; the app uses its builds.')
    finally:
        lock.rmdir()


def uninstall(args):
    prefix = args.prefix
    if not (prefix / '.kitty-smooth-install').is_file():
        raise RuntimeError('No managed installation at this prefix.')
    zshrc = (Path(os.environ.get('ZDOTDIR', str(Path.home()))) / '.zshrc').resolve()
    if zshrc.exists():
        text = zshrc.read_text()
        block = shell_block(prefix)
        if block in text:
            zshrc.write_text(text.replace(block, ''))
        elif BEGIN in text:
            raise RuntimeError('Managed shell block has changed; remove it manually before uninstalling.')
    app = args.app_dir / 'Kitty Smooth.app'
    marker = app / '.kitty-smooth-prefix'
    if marker.exists() and marker.read_text() == str(prefix):
        shutil.rmtree(app)
    current = prefix / 'current'
    if current.is_symlink():
        current.unlink()
    print(f'Deactivated. Stock installations are unchanged. Builds/backups retained in {prefix}.')



def rollback(args):
    prefix = args.prefix
    if not (prefix / '.kitty-smooth-install').is_file():
        raise RuntimeError('No managed installation at this prefix.')
    lock = prefix / '.install-lock'
    lock.mkdir()
    try:
        saved = prefix / 'previous-target'
        current = prefix / 'current'
        if not saved.exists() or not current.is_symlink():
            raise RuntimeError('No previous installation to restore.')
        target = Path(saved.read_text()).resolve()
        if target.parent != (prefix / 'releases').resolve() or not (target / 'bin/nvim').is_file():
            raise RuntimeError('Previous installation is missing or invalid.')
        old = current.resolve()
        link = prefix / 'rollback-next'
        if link.is_symlink():
            link.unlink()
        link.symlink_to(target)
        link.replace(current)
        saved.write_text(str(old))
        print('Restored previous build. Close Kitty Smooth windows and reopen the app.')
    finally:
        lock.rmdir()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rollback', action='store_true', help='Restore the previous successful build')
    parser.add_argument('--check', action='store_true', help='Validate checkout and patch without installing')
    parser.add_argument('--uninstall', action='store_true', help='Remove app/shell wiring; keep builds and backups')
    parser.add_argument('--prefix', type=Path, default=Path.home() / '.local/share/kitty-smooth')
    parser.add_argument('--app-dir', type=Path, default=Path.home() / 'Applications')
    args = parser.parse_args()
    args.prefix, args.app_dir = args.prefix.expanduser().resolve(), args.app_dir.expanduser().resolve()
    if args.rollback:
        rollback(args)
        return
    if args.uninstall:
        uninstall(args)
        return
    manifest = verify_manifest()
    if args.check:
        print('PASS: Neovim bridge present; pinned Kitty patch checksum valid.')
        return
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise RuntimeError('Native Apple Silicon macOS is required.')
    if any(c.isspace() for c in str(args.prefix)):
        raise RuntimeError('The build prefix must not contain whitespace (Neovim make requirement).')
    install(args, manifest)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, FileExistsError) as exc:
        print(f'Installation stopped: {exc}', file=sys.stderr)
        sys.exit(1)

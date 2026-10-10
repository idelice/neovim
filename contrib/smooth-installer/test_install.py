"""Installer integration fixtures: no Homebrew/network/user-config mutation."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('smooth_install', Path(__file__).with_name('install.py'))
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def test_shell_block_validation(self):
        self.assertEqual(installer.remove_block('unchanged\n'), 'unchanged\n')
        with self.assertRaises(RuntimeError):
            installer.remove_block(installer.BEGIN)
        with self.assertRaises(RuntimeError):
            installer.remove_block(installer.END + '\n' + installer.BEGIN)

    def test_install_rerun_wrappers_shell_and_uninstall(self):
        with tempfile.TemporaryDirectory(prefix='smooth-install-test-') as folder:
            home = Path(folder)
            args = argparse.Namespace(prefix=home / 'managed', app_dir=home / 'Applications')
            rc = home / '.zshrc'
            rc.write_text('# existing preferences\nexport KEEP_ME=yes\n')
            compiler = home / 'slangc'
            compiler.touch()
            calls = []

            def fake_run(command, **kwargs):
                command = list(map(str, command))
                calls.append(command)
                if command[:2] == ['git', 'clone']:
                    Path(command[-1]).mkdir(parents=True)
                if command[:2] == ['./dev.sh', 'deps']:
                    kitty = kwargs['cwd']
                    helper = kitty / 'kitty/launcher/kitty.app/Contents/MacOS/kitten'
                    helper.parent.mkdir(parents=True)
                    helper.touch()
                    installer.script(kitty / 'kitty/launcher/kitty', 'printf "kitty:%s\\n" "$*"\n')
                if command[0] == 'make':
                    release = kwargs['cwd'].parent.parent
                    runtime = release / 'neovim/share/nvim/runtime'
                    runtime.mkdir(parents=True)
                    installer.script(release / 'neovim/bin/nvim', '''printf '%s\\n' "${NVIM_KITTY_SMOOTH-unset}" "$VIMRUNTIME" "$@"
''')
                return subprocess.CompletedProcess(command, 0)

            with patch.dict(os.environ, HOME=str(home), ZDOTDIR=str(home)), \
                 patch.object(installer, 'compiler_path', return_value=compiler), \
                 patch.object(installer.pwd, 'getpwuid', return_value=argparse.Namespace(pw_shell='/bin/zsh')), \
                 patch.object(installer, 'copy_source', side_effect=lambda path: path.mkdir(parents=True)), \
                 patch.object(installer, 'run', side_effect=fake_run):
                manifest = installer.verify_manifest()
                installer.install(args, manifest)
                first = (args.prefix / 'current').resolve()
                installer.install(args, manifest)
                second = (args.prefix / 'current').resolve()
                self.assertNotEqual(first, second)
                self.assertEqual(rc.read_text().count(installer.BEGIN), 1)
                self.assertIn('export KEEP_ME=yes', rc.read_text())
                self.assertFalse((args.prefix / '.install-lock').exists())
                self.assertTrue(any(c[:3] == ['git', 'apply', '--check'] for c in calls))
                env = dict(os.environ, KITTY_SMOOTH_NVIM='1')
                output = subprocess.check_output([str(second / 'bin/nvim'), 'a file.java'], env=env, text=True)
                self.assertTrue(output.startswith('1\n'))
                self.assertIn('lua dofile(vim.env.NVIM_KITTY_SMOOTH_LUA)', output)
                self.assertIn('a file.java\n', output)
                env.pop('KITTY_SMOOTH_NVIM')
                plain = subprocess.check_output([str(second / 'bin/nvim'), 'x'], env=env, text=True)
                self.assertTrue(plain.startswith('unset\n'))
                self.assertNotIn('dofile', plain)
                env['KITTY_SMOOTH_NVIM'] = '1'
                found = subprocess.check_output(['/bin/zsh', '-fc',
                    f'source {shlex.quote(str(rc))}; whence -p nvim'], env=env, text=True).strip()
                self.assertEqual(found, str(args.prefix / 'current/bin/nvim'))
                app_exe = args.app_dir / 'Kitty Smooth.app/Contents/MacOS/kitty-smooth'
                app_output = subprocess.check_output([str(app_exe), '--version'], env=env, text=True)
                self.assertIn('cursor_trail=0', app_output)
                self.assertIn('--version', app_output)
                installer.uninstall(args)
                self.assertNotIn(installer.BEGIN, rc.read_text())
                self.assertIn('export KEEP_ME=yes', rc.read_text())
                self.assertFalse(app_exe.exists())
                self.assertFalse((args.prefix / 'current').exists())
                self.assertTrue(second.exists())

    def test_failed_build_does_not_activate_or_edit_shell(self):
        with tempfile.TemporaryDirectory(prefix='smooth-install-failure-') as folder:
            home = Path(folder)
            args = argparse.Namespace(prefix=home / 'managed', app_dir=home / 'Applications')
            rc = home / '.zshrc'
            rc.write_text('# keep exactly\n')
            with patch.dict(os.environ, HOME=str(home), ZDOTDIR=str(home)), \
                 patch.object(installer, 'compiler_path', return_value=home / 'slangc'), \
                 patch.object(installer.pwd, 'getpwuid', return_value=argparse.Namespace(pw_shell='/bin/zsh')), \
                 patch.object(installer, 'copy_source', side_effect=lambda path: path.mkdir(parents=True)), \
                 patch.object(installer, 'run', side_effect=subprocess.CalledProcessError(1, ['git'])):
                with self.assertRaises(subprocess.CalledProcessError):
                    installer.install(args, installer.verify_manifest())
            self.assertEqual(rc.read_text(), '# keep exactly\n')
            self.assertFalse((args.prefix / 'current').exists())
            self.assertFalse((args.prefix / '.install-lock').exists())


if __name__ == '__main__':
    unittest.main()

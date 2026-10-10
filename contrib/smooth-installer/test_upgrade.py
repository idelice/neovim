"""Offline Git integration tests for stable-only upgrades and safe conflict stops."""
import importlib.util
import json
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('smooth_upgrade', Path(__file__).with_name('upgrade.py'))
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


def save(repo, name, text):
    p = repo / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    u.git(repo, 'add', name)
    u.commit(repo, 'fixture')


def init(repo):
    repo.mkdir()
    u.git(repo, 'init', '--quiet')
    save(repo, 'feature.txt', 'original\n')
    return u.git(repo, 'rev-parse', 'HEAD').stdout.strip()


class UpgradeTests(unittest.TestCase):
    def scenario(self, root, conflict=None):
        nu, ku, source = root / 'nvim-upstream', root / 'kitty-upstream', root / 'source'
        nb, kb = init(nu), init(ku)
        subprocess.run(['git', 'clone', '--quiet', str(nu), str(source)], check=True)
        save(source, 'feature.txt', 'custom nvim\n')
        scratch = root / 'kitty-custom'
        subprocess.run(['git', 'clone', '--quiet', str(ku), str(scratch)], check=True)
        save(scratch, 'feature.txt', 'custom kitty\n')
        kp = subprocess.check_output(['git', '-C', str(scratch), 'diff', '--binary', kb, 'HEAD'])
        assets = source / 'contrib/smooth-installer'
        assets.mkdir(parents=True)
        (assets / 'kitty.patch').write_bytes(kp)
        (assets / 'manifest.json').write_text(json.dumps(dict(neovim_base=nb, kitty_base=kb,
            kitty_url=str(ku), kitty_patch_sha256=hashlib.sha256(kp).hexdigest())))
        u.git(source, 'add', 'contrib')
        u.commit(source, 'fixture assets')
        for name, repo in [('neovim', nu), ('kitty', ku)]:
            u.git(repo, 'tag', 'v1.0.0')
            if conflict == name:
                save(repo, 'feature.txt', 'conflicting upstream\n')
            else:
                save(repo, 'new-stable.txt', 'stable\n')
            u.git(repo, 'tag', 'v1.1.0')
            save(repo, 'nightly-only.txt', 'must not reach upgrade\n')
            u.git(repo, 'tag', 'v9.0.0-rc1')
            u.git(repo, 'tag', 'nightly')
        return source, nu, ku

    def test_stable_only_and_original_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, nu, ku = self.scenario(root)
            old = u.git(source, 'rev-parse', 'HEAD').stdout
            prepared, targets = u.prepare(source, root / 'work', str(nu), str(ku))
            self.assertEqual(targets, dict(neovim='v1.1.0', kitty='v1.1.0'))
            self.assertEqual((prepared / 'feature.txt').read_text(), 'custom nvim\n')
            self.assertFalse((prepared / 'nightly-only.txt').exists())
            self.assertEqual(u.git(source, 'rev-parse', 'HEAD').stdout, old)
            self.assertFalse(u.git(source, 'status', '--porcelain').stdout)
            manifest = json.loads((prepared / 'contrib/smooth-installer/manifest.json').read_text())
            self.assertEqual(manifest['kitty_url'], str(ku))
            self.assertEqual(manifest['neovim_base'], u.git(nu, 'rev-parse', 'v1.1.0').stdout.strip())
            self.assertFalse(u.git(prepared, 'status', '--porcelain').stdout)

    def test_conflicts_stop_in_isolation(self):
        for project in ('neovim', 'kitty'):
            with self.subTest(project=project), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source, nu, ku = self.scenario(root, project)
                old = u.git(source, 'rev-parse', 'HEAD').stdout
                with self.assertRaisesRegex(RuntimeError, 'CONFLICT'):
                    u.prepare(source, root / 'work', str(nu), str(ku))
                self.assertEqual(u.git(source, 'rev-parse', 'HEAD').stdout, old)
                self.assertFalse(u.git(source, 'status', '--porcelain').stdout)

    def test_dirty_checkout_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, nu, ku = self.scenario(root)
            (source / 'feature.txt').write_text('unsaved\n')
            with self.assertRaisesRegex(RuntimeError, 'clean checkout'):
                u.prepare(source, root / 'work', str(nu), str(ku))
            self.assertFalse((root / 'work').exists())

#!/usr/bin/env python3
"""Run production-worker recovery checks and verify they reject broken fixes.

python3 tests/test_pon_recovery.py --source . -v
The source must include the arm_tx fix. Hardware is stubbed; no router is used.
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PARSER = argparse.ArgumentParser(description=__doc__)
PARSER.add_argument('--source', type=Path, required=True)
ARGS, REST = PARSER.parse_known_args()
SOURCE = ARGS.source.resolve()
EPON = 'airoha-xpon/src/airoha-xpon-epon.c'
MAIN = 'airoha-xpon/src/airoha-xpon-main.c'
EN7572 = 'airoha-pon-frontends/src/airoha-en7572.c'


class RecoveryTests(unittest.TestCase):
    def build(self, source):
        env = {**os.environ, 'LC_ALL': 'C'}
        return subprocess.run(['sh', str(ROOT / 'tests/pon-recovery/build.sh'), str(source)],
                              capture_output=True, text=True, timeout=30, env=env)

    def run_mutant(self, path, pattern, replacement, missing_function=False):
        with tempfile.TemporaryDirectory(prefix='pon-recovery-mutant-') as tmp:
            fixture = Path(tmp)
            for name in (EPON, MAIN, EN7572):
                target = fixture / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(SOURCE / name, target)
            target = fixture / path
            text, count = re.subn(pattern, replacement, target.read_text(), flags=re.M | re.S)
            self.assertEqual(count, 1, 'negative control must change exactly one production location')
            target.write_text(text)
            result = self.build(fixture)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            # Rejecting a compile error would not prove the behavioral assertions work.
            if missing_function:
                self.assertIn('Cannot extract', result.stderr)
            else:
                self.assertIn('FAIL:', result.stderr, result.stdout + result.stderr)
                self.assertNotIn('error:', result.stderr)

    def test_production_worker_recovers(self):
        result = self.build(SOURCE)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(sum(line.startswith('PASS ') for line in result.stdout.splitlines()), 29)
        self.assertIn('All production-worker recovery assertions passed', result.stdout)

    def test_rejects_broken_helper(self):
        self.run_mutant(EPON,
                        r'static int airoha_xpon_epon_arm_tx\(struct airoha_xpon \*xpon\)\n\{.*?^\}',
                        'static int airoha_xpon_epon_arm_tx(struct airoha_xpon *xpon)\n'
                        '{\n (void)xpon; return -EAGAIN;\n}')

    def test_rejects_disconnected_production_call(self):
        self.run_mutant(EPON, r'ret = airoha_xpon_epon_arm_tx\(xpon\);',
                        'ret = airoha_pon_frontend_set_tx_enable(xpon->frontend, true);')

    def test_rejects_redundant_prepare(self):
        # A helper that always re-prepares still recovers, but violates the healthy case.
        self.run_mutant(EPON,
                        r'(static int airoha_xpon_epon_arm_tx\([^\n]*\)\n\{.*?int ret;\n)',
                        r'\1\n mode = airoha_xpon_mode_info(xpon->active_mode);\n'
                        r' ret = airoha_pon_frontend_prepare(xpon->frontend, mode->frontend_mode);\n'
                        r' if (ret) return ret;\n')

    def test_rejects_ignored_recovery_error(self):
        self.run_mutant(MAIN, r'airoha_xpon_epon_recover_tx\(xpon\)\)',
                        '(airoha_xpon_epon_recover_tx(xpon), 0))')

    def test_missing_helper_is_an_error(self):
        self.run_mutant(EPON,
                        r'static int airoha_xpon_epon_arm_tx\(struct airoha_xpon \*xpon\)\n\{.*?^\}',
                        '', missing_function=True)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0], *REST])

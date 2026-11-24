#!/usr/bin/env python3
"""Check the XGS-PON PLOAM helpers and verify the checks reject broken ones.

python3 tests/test_xgspon_ploam.py --source . -v
The production helpers are compiled on the host; no router is used.
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

PARSER = argparse.ArgumentParser(description=__doc__)
PARSER.add_argument('--source', type=Path, required=True)
ARGS, REST = PARSER.parse_known_args()
SOURCE = ARGS.source.resolve()
PLOAM = 'airoha-xpon/src/airoha-xpon-ploam.c'
PRIVATE = 'airoha-xpon/src/airoha-xpon-private.h'
HELPERS = ('airoha_xpon_profile_repeat', 'airoha_xpon_is_broadcast',
           'airoha_xpon_eqd_register_value')
IDS = ('AIROHA_XGPON_BROADCAST_ID', 'AIROHA_XGPON_ALL_ONU_ID')

PRELUDE = r'''
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
#define BIT(n) (1u << (n))
#define GENMASK(h, l) (((2u << (h)) - 1) & ~((1u << (l)) - 1))
#define U32_MAX UINT32_MAX

enum { AIROHA_XPON_MODE_XGPON = 1, AIROHA_XPON_MODE_XGSPON = 2 };
struct airoha_xpon { int active_mode; };
'''

CHECKS = r'''
static int failures;
#define CHECK(expr) do { \
	if (expr) \
		printf("PASS %s\n", #expr); \
	else { \
		fprintf(stderr, "FAIL: %s\n", #expr); \
		failures++; \
	} \
} while (0)

int main(void)
{
	struct airoha_xpon xg = { AIROHA_XPON_MODE_XGPON };
	struct airoha_xpon xgs = { AIROHA_XPON_MODE_XGSPON };
	u32 eqd = 0;

	/* G.9807.1 Table C.11.4: control bit 2 selects the 9.95328 Gb/s rate. */
	CHECK(airoha_xpon_profile_repeat(true, 0x54, 0x28) == 0x28);
	CHECK(airoha_xpon_profile_repeat(true, 0x57, 0xff) == 0xff);
	CHECK(airoha_xpon_profile_repeat(true, 0x50, 0x28) == -EINVAL);
	CHECK(airoha_xpon_profile_repeat(false, 0x54, 0x28) == -EINVAL);
	CHECK(airoha_xpon_profile_repeat(false, 0x50, 0xe5) == 0x05);

	CHECK(airoha_xpon_is_broadcast(&xgs, AIROHA_XGPON_ALL_ONU_ID));
	CHECK(airoha_xpon_is_broadcast(&xgs, AIROHA_XGPON_BROADCAST_ID));
	CHECK(airoha_xpon_is_broadcast(&xg, AIROHA_XGPON_BROADCAST_ID));
	CHECK(!airoha_xpon_is_broadcast(&xg, AIROHA_XGPON_ALL_ONU_ID));
	CHECK(!airoha_xpon_is_broadcast(&xgs, 2));

	CHECK(airoha_xpon_eqd_register_value(true, 12345, &eqd) == 0 && eqd == 49380);
	CHECK(airoha_xpon_eqd_register_value(false, 12345, &eqd) == 0 && eqd == 12345);
	CHECK(airoha_xpon_eqd_register_value(true, U32_MAX / 4, &eqd) == 0 &&
	      eqd == (U32_MAX / 4) * 4);
	CHECK(airoha_xpon_eqd_register_value(true, U32_MAX / 4 + 1, &eqd) == -ERANGE);
	CHECK(airoha_xpon_eqd_register_value(false, U32_MAX, &eqd) == 0 && eqd == U32_MAX);

	if (failures)
		return 1;
	puts("All XGS-PON PLOAM helper assertions passed");
	return 0;
}
'''


def extract(source):
    ploam = (source / PLOAM).read_text()
    private = (source / PRIVATE).read_text()
    parts = [PRELUDE]
    for name in IDS:
        match = re.search(rf'^#define {name}\s+\S+$', private, re.M)
        if not match:
            raise LookupError(f'Cannot extract {name}')
        parts.append(match.group(0) + '\n')
    for name in HELPERS:
        match = re.search(rf'^static \w+ {name}\(.*?^\}}\n', ploam, re.M | re.S)
        if not match:
            raise LookupError(f'Cannot extract {name}')
        parts.append(match.group(0))
    parts.append(CHECKS)
    return ''.join(parts)


def build_and_run(source):
    try:
        program = extract(source)
    except LookupError as error:
        return subprocess.CompletedProcess([], 2, '', str(error) + '\n')
    with tempfile.TemporaryDirectory(prefix='xgspon-ploam-') as tmp:
        c_file = Path(tmp) / 'check.c'
        binary = Path(tmp) / 'check'
        c_file.write_text(program)
        env = {**os.environ, 'LC_ALL': 'C'}
        compiled = subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-Wall', '-Werror',
                                   '-o', str(binary), str(c_file)],
                                  capture_output=True, text=True, timeout=60, env=env)
        if compiled.returncode:
            return compiled
        return subprocess.run([str(binary)], capture_output=True, text=True, timeout=30, env=env)


class XgsponPloamTests(unittest.TestCase):
    def run_mutant(self, pattern, replacement, missing_function=False):
        with tempfile.TemporaryDirectory(prefix='xgspon-ploam-mutant-') as tmp:
            fixture = Path(tmp)
            for name in (PLOAM, PRIVATE):
                target = fixture / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(SOURCE / name, target)
            target = fixture / PLOAM
            text, count = re.subn(pattern, replacement, target.read_text(), flags=re.M | re.S)
            self.assertEqual(count, 1, 'negative control must change exactly one production location')
            target.write_text(text)
            result = build_and_run(fixture)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            # Rejecting a compile error would not prove the behavioral assertions work.
            if missing_function:
                self.assertIn('Cannot extract', result.stderr)
            else:
                self.assertIn('FAIL:', result.stderr, result.stdout + result.stderr)
                self.assertNotIn('error:', result.stderr)

    def test_helpers(self):
        result = build_and_run(SOURCE)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(sum(line.startswith('PASS ') for line in result.stdout.splitlines()), 15)
        self.assertIn('All XGS-PON PLOAM helper assertions passed', result.stdout)

    def test_rejects_ignored_rate_bit(self):
        self.run_mutant(r'if \(!!\(control & BIT\(2\)\) != xgspon\)', 'if (0)')

    def test_rejects_full_repeat_octet_on_xgpon(self):
        self.run_mutant(r'repeat & GENMASK\(4, 0\)', 'repeat')

    def test_rejects_missing_all_onu_id(self):
        self.run_mutant(r'dest == AIROHA_XGPON_BROADCAST_ID \|\|.*?dest == AIROHA_XGPON_ALL_ONU_ID\);',
                        'dest == AIROHA_XGPON_BROADCAST_ID;')

    def test_rejects_unscaled_eqd(self):
        self.run_mutant(r'xgspon \? delay \* 4 : delay', 'delay')

    def test_rejects_missing_overflow_guard(self):
        self.run_mutant(r'if \(xgspon && delay > U32_MAX / 4\)', 'if (0)')

    def test_rejects_missing_helper(self):
        self.run_mutant(r'^static int airoha_xpon_eqd_register_value\(',
                        'static int airoha_xpon_eqd_value(', missing_function=True)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0], *REST])

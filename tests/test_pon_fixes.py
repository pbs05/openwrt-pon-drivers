"""Source-level regressions; not a kernel build or hardware simulation.

Run with Python 3 and the pure-Python pycparser package:
    python3 -m unittest discover -s tests -v

Selected actual C branches are interpreted with explicit mocked side effects.
Kernel locking, MMIO, firmware execution and C type checking require deployment.
"""

import ast
import errno
from functools import lru_cache
import operator
from pathlib import Path
import re
import unittest

from pycparser import c_ast as C, c_parser


ROOT = Path(__file__).resolve().parents[1]
XPON = ROOT / "airoha-xpon/src"
EN = ROOT / "airoha-pon-frontends/src/airoha-en7572.c"
PARSER = c_parser.CParser()
TYPES = ("typedef int bool; typedef unsigned char u8; typedef unsigned short u16;"
         "typedef unsigned int u32; typedef int irqreturn_t;")


def uncomment(text):
    return re.sub(
        r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|/\*.*?\*/|//[^\n]*',
        lambda m: " " if m[0].startswith(("//", "/*")) else m[0],
        text, flags=re.S,
    )


SOURCES = {
    p.name: uncomment(p.read_text(encoding="utf-8"))
    for p in XPON.glob("*.[ch]")
}
SOURCES[EN.name] = uncomment(EN.read_text(encoding="utf-8"))
DEFINES = {}
for source in SOURCES.values():
    DEFINES.update(re.findall(r"^#define\s+(\w+)[ \t]+([^\n]+)", source, re.M))


@lru_cache(maxsize=None)
def function(name):
    for source in SOURCES.values():
        match = re.search(r"[\w\s*]+\b" + name + r"\s*\([^;{}]*\)\s*\{", source)
        if not match:
            continue
        depth = 1
        for token in re.finditer(r'"(?:\\.|[^"\\])*"|[{}]', source[match.end():]):
            depth += (token[0] == "{") - (token[0] == "}")
            if not depth:
                return source[match.start():match.end() + token.end()].strip()
    raise AssertionError(f"Missing C function: {name}")


@lru_cache(maxsize=None)
def tree(name):
    return PARSER.parse(TYPES + "\n" + function(name)).ext[-1]


CONSTANTS = {"true": True, "false": False, "fallthrough": 0}
CONSTANTS.update({name: getattr(errno, name) for name in ("EAGAIN", "EINVAL")})


class Returned(Exception):
    pass


class Jumped(Exception):
    pass


class Branches:
    """A deliberately bounded AST evaluator, failing on unsupported C nodes."""

    binary = {
        "==": operator.eq, "!=": operator.ne, "<": operator.lt, ">": operator.gt,
        "<=": operator.le, ">=": operator.ge, "+": operator.add, "-": operator.sub,
        "&": operator.and_, "|": operator.or_,
    }

    def __init__(self, calls):
        self.calls = calls

    def constant(self, name):
        if name in CONSTANTS:
            return CONSTANTS[name]
        expr = PARSER.parse(TYPES + "\nint f(void) { return " + DEFINES[name] + "; }")
        return self.eval(expr.ext[-1].body.block_items[0].expr)

    def ref(self, node):
        if isinstance(node, C.ID):
            return self.locals, node.name
        if isinstance(node, C.StructRef):
            return self.eval(node.name), node.field.name
        raise AssertionError(f"Unsupported C lvalue: {node}")

    def eval(self, node):
        if node is None:
            return None
        if isinstance(node, C.Constant):
            if node.type in ("string", "char"):
                return ast.literal_eval(node.value)
            return int(re.sub(r"[uUlL]+$", "", node.value), 0)
        if isinstance(node, C.ID):
            return self.locals[node.name] if node.name in self.locals else self.constant(node.name)
        if isinstance(node, C.StructRef):
            return self.eval(node.name)[node.field.name]
        if isinstance(node, C.Cast):
            return self.eval(node.expr)
        if isinstance(node, C.TernaryOp):
            return self.eval(node.iftrue if self.eval(node.cond) else node.iffalse)
        if isinstance(node, C.UnaryOp):
            if node.op == "&":
                return self.ref(node.expr)
            if node.op == "sizeof":
                return 4 if isinstance(node.expr, C.Typename) else len(self.eval(node.expr))
            if node.op == "!":
                return not self.eval(node.expr)
            if node.op == "-":
                return -self.eval(node.expr)
            if node.op == "~":
                return ~self.eval(node.expr)
            if node.op == "p++":
                obj, key = self.ref(node.expr)
                old = obj[key]
                obj[key] += 1
                return old
        if isinstance(node, C.BinaryOp):
            left = self.eval(node.left)
            if node.op == "&&":
                return left and self.eval(node.right)
            if node.op == "||":
                return left or self.eval(node.right)
            right = self.eval(node.right)
            return self.binary[node.op](left, right)
        if isinstance(node, C.FuncCall):
            name = node.name.name
            args = node.args.exprs if node.args else []
            if name == "readl_poll_timeout_atomic":
                return self.calls[name](self.ref(args[1]))
            return self.calls[name](*(self.eval(a) for a in args))
        raise AssertionError(f"Unsupported C expression: {node}")

    def execute(self, node):
        if node is None:
            return
        if isinstance(node, C.Compound):
            items = node.block_items or []
            labels = {n.name: i for i, n in enumerate(items) if isinstance(n, C.Label)}
            i = 0
            while i < len(items):
                try:
                    self.execute(items[i])
                    i += 1
                except Jumped as jump:
                    if jump.args[0] not in labels:
                        raise
                    i = labels[jump.args[0]]
        elif isinstance(node, C.Decl):
            self.locals[node.name] = self.eval(node.init)
        elif isinstance(node, C.Assignment):
            obj, key = self.ref(node.lvalue)
            value = self.eval(node.rvalue)
            obj[key] = value if node.op == "=" else self.binary[node.op[:-1]](obj[key], value)
        elif isinstance(node, C.If):
            self.execute(node.iftrue if self.eval(node.cond) else node.iffalse)
        elif isinstance(node, C.Return):
            raise Returned(self.eval(node.expr))
        elif isinstance(node, C.Goto):
            raise Jumped(node.name)
        elif isinstance(node, C.Label):
            self.execute(node.stmt)
        else:
            self.eval(node)

    def run(self, name, **variables):
        self.locals = variables
        try:
            self.execute(tree(name).body)
        except Returned as result:
            return result.args[0]


class PonFixTests(unittest.TestCase):
    def test_changed_function_syntax(self):
        for name in (
            "airoha_xpon_try_arm_upstream", "airoha_xpon_drain_ploamd",
            "airoha_xpon_xgpon_drain_ploamd_locked", "airoha_xpon_xgpon_irq",
            "airoha_xpon_xgpon_phy_irq", "airoha_xpon_activate_data_key",
            "en7572_prepare", "en7572_set_tx_enable",
            "airoha_xpon_xgpon_reset_and_enable_digital_rx",
            "airoha_xpon_xgpon_start_control",
            "airoha_xpon_send_registration",
        ):
            with self.subTest(function=name):
                tree(name)

    def test_md32_cold_warm_empty_and_failure(self):
        for empty in (False, True):
            events = []
            en = {"lock": 0, "prepared": False, "tx_gate_enabled": False,
                  "tx_disable": 1, "md32_needs_reload": False, "bob_a0_valid": not empty,
                  "bob_a2_valid": not empty, "program": {"dev": 0}, "bob": 0,
                  "runtime": 0}
            reload_error = [0]
            vm = Branches({
                "airoha_pon_frontend_priv": lambda frontend: en,
                "en7572_bob_base": lambda mode: vm.constant("EN7572_BOB_A0_BASE"),
                "mutex_lock": lambda *a: events.append("lock"),
                "mutex_unlock": lambda *a: events.append("unlock"),
                "gpiod_set_value_cansleep": lambda gpio, value: events.append(("gpio", value)),
                "en7572_update_bits": lambda *a: events.append("register") or 0,
                "en7572_initialize_md32": lambda *a: events.append("reload") or reload_error[0],
                "en7572_mode_name": lambda *a: "XG-PON",
                "en7572_bob_u8": lambda *a: 0,
                "en7572_bob_u16": lambda *a: 0,
                "en7572_write": lambda *a: 0,
                "dev_info": lambda *a: None,
                "dev_err": lambda *a: events.append("error"),
                "GENMASK": lambda high, low: ((1 << (high - low + 1)) - 1) << low,
                "BIT": lambda bit: 1 << bit,
                "FIELD_PREP": lambda mask, value: value * (mask & -mask),
            })
            for attempt in range(4):
                events.clear()
                reload_error[0] = -5 if attempt == 2 else 0
                ret = vm.run("en7572_prepare", frontend=0, mode=2)
                self.assertEqual(ret, reload_error[0])
                self.assertEqual(en["prepared"], not reload_error[0])
                self.assertTrue(en["md32_needs_reload"])
                self.assertEqual(events[:3], ["lock", ("gpio", 1), "register"])
                self.assertEqual(events[-1], "unlock")
                self.assertEqual(events.count("reload"), int(attempt > 0))
                self.assertFalse(en["tx_gate_enabled"])

    def test_lifecycle_source_contracts(self):
        irq = function("airoha_xpon_xgpon_irq")
        self.assertIn("mutex_trylock(&xpon->state_lock)", irq)
        self.assertNotIn("mutex_lock(&xpon->state_lock)", irq)
        drain = function("airoha_xpon_drain_ploamd")
        self.assertLess(drain.index("lockdep_assert_held(&xpon->state_lock)"),
                        drain.index("mutex_lock(&xpon->ploam_lock)"))
        worker = function("airoha_xpon_link_work")
        self.assertEqual(worker.count("airoha_xpon_xgpon_drain_ploamd_locked(xpon)"), 2)
        self.assertEqual(worker.count('airoha_xpon_xgpon_restart_mac(xpon, "OLT Deactivate")'), 2)
        enable = function("en7572_set_tx_enable")
        self.assertLess(enable.index("mutex_lock"), enable.index("!en->prepared"))
        self.assertNotIn("queue_delayed_work(", function("airoha_xpon_xgpon_phy_irq"))
        self.assertIn("mod_delayed_work(", function("airoha_xpon_xgpon_phy_irq"))
        registration = function("airoha_xpon_send_registration")
        self.assertIn("AIROHA_XGPON_CUR_KIDX", registration)
        self.assertIn("diagnostic->control_key_index = message[3]", registration)
        self.assertIn("AIROHA_XGPON_TX_PLOAMU_CNT", registration)
        ranging = function("airoha_xpon_accept_ranging_time")
        self.assertIn("diagnostic.ploamu_tx_before", ranging)
        self.assertIn("diagnostic.ploamu_tx_after", ranging)
        self.assertIn("AIROHA_XGPON_DBG_BWM_CHK_STS", ranging)
        self.assertIn("AIROHA_XGPON_TX_ERR_STS", ranging)
        self.assertIn("AIROHA_XGPON_US_PROF_VLD", ranging)
        self.assertLess(
            ranging.index("airoha_xpon_set_onu_state(xpon, AIROHA_XGPON_O5)"),
            ranging.index("ret = readl_poll_timeout("),
        )
        self.assertLess(
            ranging.index("ret = readl_poll_timeout("),
            ranging.index("ack_result = airoha_xpon_send_ack("),
        )
        self.assertLess(
            ranging.index("ack_result = airoha_xpon_send_ack("),
            ranging.index("airoha_xpon_update_omci_link(xpon)"),
        )
        handler = function("airoha_xpon_handle_ploamd")
        self.assertIn(".ploamu_tx_at_deactivate", handler)
        self.assertIn(".bwm_check_at_deactivate", handler)
        self.assertIn(".tx_error_at_deactivate", handler)
        self.assertIn(".irq_at_deactivate", handler)
        alloc = function("airoha_xpon_accept_alloc_id")
        self.assertNotIn(
            "alloc_id == xpon->onu_id)",
            alloc[:alloc.index("return -EINVAL;")],
        )
        self.assertIn("if (alloc_id == xpon->onu_id)\n\t\tret = 0;", alloc)
        self.assertLess(
            alloc.index("if (alloc_id == xpon->onu_id)"),
            alloc.index("ack_result = airoha_xpon_send_ack("),
        )
        self.assertIn("diagnostic.alloc_id = alloc_id;", alloc)
        self.assertIn("diagnostic.onu_id = xpon->onu_id;", alloc)
        self.assertIn("diagnostic.operation_result = ret;", alloc)
        self.assertIn("diagnostic.ack_result = ack_result;", alloc)
        self.assertIn("AIROHA_XGPON_PLOAMU_FIFO_STS", alloc)
        self.assertIn("AIROHA_XGPON_TX_ACK_PLOAMU_CNT", alloc)

    def test_tx_enable_requires_prepared_and_reports_gate_errors(self):
        for prepared in (False, True):
            for enable in (False, True):
                for gate_error in (0, -5):
                    events = []
                    en = {"lock": 0, "prepared": prepared,
                          "tx_gate_enabled": False, "tx_disable": 1}
                    vm = Branches({
                        "airoha_pon_frontend_priv": lambda frontend: en,
                        "mutex_lock": lambda *a: events.append("lock"),
                        "mutex_unlock": lambda *a: events.append("unlock"),
                        "en7572_update_bits": lambda *a: events.append("register") or gate_error,
                        "gpiod_set_value_cansleep": lambda gpio, value: events.append(("gpio", value)),
                        "GENMASK": lambda high, low: ((1 << (high - low + 1)) - 1) << low,
                        "FIELD_PREP": lambda mask, value: value * (mask & -mask),
                    })
                    ret = vm.run("en7572_set_tx_enable", frontend=0, enable=enable)
                    self.assertEqual(events[0], "lock")
                    self.assertEqual(events[-1], "unlock")
                    if enable and not prepared:
                        self.assertEqual((ret, events), (-errno.EAGAIN, ["lock", "unlock"]))
                    else:
                        self.assertEqual(ret, gate_error)
                    self.assertEqual(en["tx_gate_enabled"], enable and prepared and not gate_error)
                    if enable and prepared and not gate_error:
                        self.assertLess(events.index("register"), events.index(("gpio", 0)))
                    elif not enable:
                        self.assertLess(events.index(("gpio", 1)), events.index("register"))

    def test_irq_lock_contention_branch(self):
        branch = next(node for node in tree("airoha_xpon_xgpon_irq").body.block_items
                      if isinstance(node, C.If) and isinstance(node.cond, C.BinaryOp)
                      and isinstance(node.cond.right, C.ID)
                      and node.cond.right.name == "AIROHA_XGPON_INT_PLOAMD_RECV")
        for available in (False, True):
            events = []
            vm = Branches({
                "BIT": lambda bit: 1 << bit,
                "mutex_trylock": lambda *a: available,
                "mutex_unlock": lambda *a: events.append("unlock"),
                "airoha_xpon_xgpon_drain_ploamd_locked": lambda *a: events.append("drain"),
                "mod_delayed_work": lambda wq, work, delay: events.append(("defer", delay)),
            })
            vm.locals = {"xpon": {"state_lock": 0, "link_work": 0},
                         "events": 1, "system_wq": 0}
            vm.execute(branch)
            self.assertEqual(events, ["drain", "unlock"] if available else [("defer", 0)])

    def test_drain_lifecycle_and_fifo_budget(self):
        for stopping in (False, True):
            for valid in (False, True):
                for initialized in (False, True):
                    for epon in (False, True):
                        for full in (False, True):
                            events = []
                            vm = Branches({
                                "lockdep_assert_held": lambda *a: None,
                                "airoha_xpon_mode_is_epon": lambda mode: epon,
                                "airoha_xpon_drain_ploamd": lambda *a: events.append("drain") or (
                                    vm.constant("AIROHA_XGPON_PLOAMD_MAX_DRAIN") if full else 0),
                                "dev_warn_ratelimited": lambda *a: events.append("warn"),
                                "mod_delayed_work": lambda wq, work, delay: events.append(("defer", delay)),
                            })
                            xpon = {"state_lock": 0, "stopping": stopping, "active_mode_valid": valid,
                                    "mac_initialized": initialized, "active_mode": 0, "dev": 0, "link_work": 0}
                            vm.run("airoha_xpon_xgpon_drain_ploamd_locked", xpon=xpon, system_wq=0)
                            expected = []
                            if not stopping and valid and initialized and not epon:
                                expected = ["drain", "warn", ("defer", 0)] if full else ["drain"]
                            self.assertEqual(events, expected)

    def test_aes_advisory_timeout(self):
        for index in (0, 1, 2, 3):
            for timeout in (False, True):
                events = []
                xpon = {"dev": 0, "xgpon_base": 0, "crypto": {"key_switch_timeout_count": 0}}

                def poll(ref):
                    ref[0][ref[1]] = 0 if timeout else vm.constant("AIROHA_XGPON_INT_AES_KEY_SWITCH_DONE")
                    return -110 if timeout else 0

                vm = Branches({
                    "BIT": lambda bit: 1 << bit,
                    "airoha_xgpon_read": lambda *a: 0,
                    "airoha_xgpon_write": lambda x, reg, value: events.append(("write", reg, value)),
                    "readl_poll_timeout_atomic": poll,
                    "dev_warn_ratelimited": lambda *a: events.append("warn"),
                })
                ret = vm.run("airoha_xpon_activate_data_key", xpon=xpon, index=index)
                self.assertEqual(ret, 0 if index in (1, 2) else -errno.EINVAL)
                valid_timeout = timeout and index in (1, 2)
                self.assertEqual(xpon["crypto"]["key_switch_timeout_count"], int(valid_timeout))
                self.assertEqual("warn" in events, valid_timeout)
                if index in (1, 2):
                    w1c = vm.constant("AIROHA_XGPON_INT_STATUS")
                    self.assertEqual(sum(e[0] == "write" and e[1] == w1c for e in events),
                                     1 if timeout else 2)
                else:
                    self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()

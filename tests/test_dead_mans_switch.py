#!/usr/bin/env python3
"""Tests for the dead-man's-switch (activity-countdown escrow) template.

Drives the template through ``ContractEngine`` against a real ``WorldState``,
mirroring how ``blockchain._execute_transaction`` credits ``value`` before a
call and reverts state on failure.  Heights are passed explicitly so the
countdown semantics can be exercised deterministically.

Run directly (``python3 tests/test_dead_mans_switch.py``) or under pytest.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from backend.contract import ContractEngine
from backend.sandbox import validate_source
from backend.state import WorldState
from backend.templates import get_template, template_catalog

OWNER = "0x" + "11" * 20
HEIR = "0x" + "22" * 20
THIRD = "0x" + "33" * 20
CONTRACT = "0xc" + "ab" * 20

PERIOD = 10
DEPLOY_HEIGHT = 1


class Chain:
    """Minimal harness: engine + world state + explicit block heights."""

    def __init__(self):
        self.engine = ContractEngine({})
        self.ws = WorldState()
        self.ws.set_balance(OWNER, 1000.0)
        self.ws.set_balance(HEIR, 0.0)
        self.ws.set_balance(THIRD, 500.0)
        src = get_template("dead_mans_switch")["source"]
        ok, msg = validate_source(src)
        assert ok, msg
        res = self.engine.deploy(src, OWNER, CONTRACT, self.ws,
                                 constructor=[HEIR, PERIOD],
                                 height=DEPLOY_HEIGHT)
        assert res["ok"], res["error"]

    def call(self, fn, args=None, sender=OWNER, value=0.0, height=2):
        """State-changing call; reverts on failure exactly like the chain."""
        before = self.ws.copy()
        self.ws.add_balance(sender, -value)
        self.ws.add_balance(CONTRACT, value)
        res = self.engine.invoke(CONTRACT, fn, args or [], sender, value,
                                 self.ws, height)
        if not res["ok"]:
            self.ws = before
        return res

    def read(self, fn, args=None, height=2):
        res = self.engine.simulate(CONTRACT, fn, args or [], THIRD,
                                   self.ws, height)
        assert res["ok"], res["error"]
        return res["return"]

    def balance(self, addr):
        return self.ws.balance(addr)


class DeadMansSwitchTest(unittest.TestCase):
    def test_template_registered(self):
        entry = next(t for t in template_catalog()
                     if t["name"] == "dead_mans_switch")
        self.assertEqual([c["name"] for c in entry["constructor"]],
                         ["heir", "period"])
        fns = [f["name"] for f in entry["functions"]]
        for expected in ("deposit", "check_in", "claim",
                         "time_remaining", "can_claim", "status"):
            self.assertIn(expected, fns)

    def test_initial_status(self):
        chain = Chain()
        s = chain.read("status", height=DEPLOY_HEIGHT)
        self.assertEqual(s["owner"], OWNER)
        self.assertEqual(s["heir"], HEIR)
        self.assertEqual(s["period"], PERIOD)
        self.assertEqual(s["last_active"], DEPLOY_HEIGHT)
        self.assertEqual(s["deadline"], DEPLOY_HEIGHT + PERIOD)
        self.assertEqual(s["remaining"], PERIOD)
        self.assertFalse(s["claimed"])
        self.assertFalse(s["claimable"])

    def test_deposit_and_countdown(self):
        chain = Chain()
        res = chain.call("deposit", sender=OWNER, value=100.0, height=3)
        self.assertTrue(res["ok"], res["error"])
        self.assertEqual(chain.balance(CONTRACT), 100.0)
        self.assertEqual(chain.balance(OWNER), 900.0)
        # 持有人本人存入 => 倒计时重置到高度 3。
        self.assertEqual(chain.read("time_remaining", height=3), PERIOD)
        self.assertEqual(chain.read("time_remaining", height=3 + PERIOD), 0)
        # 第三方代存 => 不重置倒计时。
        res = chain.call("deposit", sender=THIRD, value=50.0, height=5)
        self.assertTrue(res["ok"], res["error"])
        self.assertEqual(chain.balance(CONTRACT), 150.0)
        s = chain.read("status", height=5)
        self.assertEqual(s["last_active"], 3)
        self.assertEqual(s["remaining"], 3 + PERIOD - 5)

    def test_deposit_requires_value(self):
        chain = Chain()
        res = chain.call("deposit", sender=OWNER, value=0.0, height=2)
        self.assertFalse(res["ok"])

    def test_check_in_only_owner(self):
        chain = Chain()
        chain.call("deposit", sender=OWNER, value=100.0, height=2)
        for stranger in (HEIR, THIRD):
            res = chain.call("check_in", sender=stranger, height=4)
            self.assertFalse(res["ok"])
            self.assertIn("持有人", res["error"])
        res = chain.call("check_in", sender=OWNER, height=4)
        self.assertTrue(res["ok"], res["error"])
        s = chain.read("status", height=4)
        self.assertEqual(s["last_active"], 4)
        self.assertEqual(s["deadline"], 4 + PERIOD)

    def test_claim_before_deadline_fails(self):
        chain = Chain()
        chain.call("deposit", sender=OWNER, value=100.0, height=2)
        res = chain.call("claim", sender=HEIR, height=2 + PERIOD - 1)
        self.assertFalse(res["ok"])
        self.assertIn("期限未到", res["error"])
        self.assertEqual(chain.balance(HEIR), 0.0)

    def test_claim_only_heir_after_deadline(self):
        chain = Chain()
        chain.call("deposit", sender=OWNER, value=100.0, height=2)
        deadline = 2 + PERIOD
        for stranger in (OWNER, THIRD):
            res = chain.call("claim", sender=stranger, height=deadline)
            self.assertFalse(res["ok"])
            self.assertIn("继承人", res["error"])
        res = chain.call("claim", sender=HEIR, height=deadline)
        self.assertTrue(res["ok"], res["error"])
        self.assertEqual(chain.balance(HEIR), 100.0)
        self.assertEqual(chain.balance(CONTRACT), 0.0)
        s = chain.read("status", height=deadline)
        self.assertTrue(s["claimed"])
        self.assertFalse(s["claimable"])

    def test_claim_is_final(self):
        chain = Chain()
        chain.call("deposit", sender=OWNER, value=100.0, height=2)
        chain.call("claim", sender=HEIR, height=2 + PERIOD)
        # 领取后：再次领取、签到、存入全部拒绝。
        self.assertFalse(chain.call("claim", sender=HEIR,
                                    height=2 + PERIOD + 1)["ok"])
        self.assertFalse(chain.call("check_in", sender=OWNER,
                                    height=2 + PERIOD + 1)["ok"])
        self.assertFalse(chain.call("deposit", sender=OWNER, value=10.0,
                                    height=2 + PERIOD + 1)["ok"])

    def test_owner_comeback_before_claim(self):
        """到期后只要没被领走，持有人重新活跃即可继续保住资金。"""
        chain = Chain()
        chain.call("deposit", sender=OWNER, value=100.0, height=2)
        expired = 2 + PERIOD + 3  # 已过期 3 个区块
        self.assertTrue(chain.read("can_claim", height=expired))
        res = chain.call("check_in", sender=OWNER, height=expired)
        self.assertTrue(res["ok"], res["error"])
        # 倒计时重置，继承人暂时无法领取。
        self.assertFalse(chain.read("can_claim", height=expired))
        res = chain.call("claim", sender=HEIR, height=expired)
        self.assertFalse(res["ok"])
        # 新期限再次到期后，继承人仍可领取。
        new_deadline = expired + PERIOD
        res = chain.call("claim", sender=HEIR, height=new_deadline)
        self.assertTrue(res["ok"], res["error"])
        self.assertEqual(chain.balance(HEIR), 100.0)

    def test_owner_deposit_rearms_after_expiry(self):
        """过期未领取时，持有人本人再次存入同样重置倒计时。"""
        chain = Chain()
        chain.call("deposit", sender=OWNER, value=100.0, height=2)
        expired = 2 + PERIOD + 1
        res = chain.call("deposit", sender=OWNER, value=25.0, height=expired)
        self.assertTrue(res["ok"], res["error"])
        s = chain.read("status", height=expired)
        self.assertEqual(s["last_active"], expired)
        self.assertFalse(s["claimable"])
        res = chain.call("claim", sender=HEIR, height=expired + PERIOD)
        self.assertTrue(res["ok"], res["error"])
        self.assertEqual(chain.balance(HEIR), 125.0)

    def test_claim_empty_balance_fails(self):
        chain = Chain()
        res = chain.call("claim", sender=HEIR, height=DEPLOY_HEIGHT + PERIOD)
        self.assertFalse(res["ok"])
        self.assertIn("没有可领取", res["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

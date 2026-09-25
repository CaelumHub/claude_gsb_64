"""Chain-level test for the deadman_escrow template.

Drives a real Node (txpool, mining, block execution, event files) with the
dead-man's-switch template.  The `cryptography` and `requests` packages are
unavailable in this sandbox, so they are stubbed: the toy signature scheme is
symmetric (pub == priv) and only stands in for ECDSA — all product code paths
(wallets, tx signing/validation, pool, execution, events) run for real.
"""
import hashlib
import os
import sys
import tempfile
import types

# --------------------------------------------------------------------------- #
# Test-only stubs, installed only when the real packages are unavailable
# --------------------------------------------------------------------------- #
try:
    import cryptography  # noqa: F401
    _HAVE_CRYPTO = True
except ImportError:
    _HAVE_CRYPTO = False

if not _HAVE_CRYPTO:
    class _Priv:
        def __init__(self, secret):
            self._s = secret

        def private_numbers(self):
            return types.SimpleNamespace(
                private_value=int.from_bytes(self._s, "big"))

        def public_key(self):
            return _Pub(self._s)

        def sign(self, data, _alg):
            return hashlib.sha256(self._s + data).digest()

    class _Pub:
        def __init__(self, raw):
            self._r = raw

        def public_bytes(self, _enc, _fmt):
            return self._r

        def verify(self, sig, data, _alg):
            if sig != hashlib.sha256(self._r + data).digest():
                raise ValueError("invalid signature")

    _ec = types.SimpleNamespace(
        SECP256K1=lambda: object(),
        ECDSA=lambda _h: object(),
        generate_private_key=lambda _curve: _Priv(os.urandom(32)),
        derive_private_key=lambda value, _curve: _Priv(value.to_bytes(32, "big")),
        EllipticCurvePublicKey=types.SimpleNamespace(
            from_encoded_point=lambda _curve, raw: _Pub(raw)),
    )
    _hashes = types.SimpleNamespace(SHA256=type("SHA256", (), {}))
    _ser = types.SimpleNamespace(
        Encoding=types.SimpleNamespace(X962=object()),
        PublicFormat=types.SimpleNamespace(UncompressedPoint=object()))

    for name in ("cryptography", "cryptography.hazmat",
                 "cryptography.hazmat.primitives",
                 "cryptography.hazmat.primitives.asymmetric"):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["cryptography.hazmat.primitives"].hashes = _hashes
    sys.modules["cryptography.hazmat.primitives"].serialization = _ser
    sys.modules["cryptography.hazmat.primitives.asymmetric"].ec = _ec

try:
    import requests  # noqa: F401
except ImportError:
    sys.modules.setdefault("requests", types.ModuleType("requests"))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.config import build_config          # noqa: E402
from backend.node import Node                    # noqa: E402
from backend.templates import get_template       # noqa: E402

failures = []

def check(name, cond, extra=""):
    tag = "PASS" if cond else "FAIL"
    if not cond:
        failures.append(name)
    print(f"[{tag}] {name} {extra}")

def mine(n=1):
    for _ in range(n):
        status, msg, h = node.mine_block(owner)
        assert status == "extended", f"mining failed: {msg}"

def call(sender, fn, args=None, value=0):
    tx, err = node.create_call(sender, caddr, fn, args or [], fee=0, value=value)
    assert err is None, err
    ok, reason = node.submit_transaction(tx)
    assert ok, reason
    mine()
    return node.blockchain.last_receipts[-1]  # coinbase receipt is first? see below

def status():
    r = node.blockchain.engine.simulate(
        caddr, "status", [], owner, node.blockchain.state,
        node.blockchain.height)
    assert r["ok"], r["error"]
    return r["return"]

# --------------------------------------------------------------------------- #
# Node boot + wallets
# --------------------------------------------------------------------------- #
args = types.SimpleNamespace(id="t1", port=19000, host="127.0.0.1", peers=None,
                             data_dir=tempfile.mkdtemp(prefix="lc-test-"),
                             mine=False, seed=False)
cfg = build_config(args)
cfg["INITIAL_DIFFICULTY_BITS"] = 8          # keep the test fast
node = Node(cfg)
node.start()

owner, _ = node.wallets.create("owner")
heir, _ = node.wallets.create("heir")
def bal(a):
    # state is replaced on every added block — always read the current one
    return node.blockchain.state.balance(a)

mine(2)
check("owner funded by coinbase", bal(owner) == 100.0, f"bal={bal(owner)}")

# --------------------------------------------------------------------------- #
# Deploy the deadman_escrow template (period = 5 blocks)
# --------------------------------------------------------------------------- #
src = get_template("deadman_escrow")["source"]
tx, err = node.create_deploy(owner, src, 0, constructor=[heir, 5])
assert err is None, err
ok, reason = node.submit_transaction(tx)
assert ok, reason
mine()
caddr = "0xc" + hashlib.sha256(tx.txid.encode()).hexdigest()[:40]
deploy_receipt = [r for r in node.blockchain.last_receipts
                  if r.get("contract") == caddr]
check("deploy confirmed on chain", len(deploy_receipt) == 1
      and deploy_receipt[0]["ok"])
st = status()
check("init: owner/heir/period", st["owner"] == owner and st["heir"] == heir
      and st["period"] == 5 and st["claimed"] is False)
check("init: countdown armed", st["deadline"] == st["last_active"] + 5
      and st["remaining"] > 0)

# --------------------------------------------------------------------------- #
# Deposit 50 LC (also resets the countdown)
# --------------------------------------------------------------------------- #
r = call(owner, "deposit", value=50)
check("deposit mined ok", r["ok"], r.get("error") or "")
st = status()
check("contract holds deposit", st["balance"] == 50.0 and st["amount"] == 50.0)
check("deposit reset countdown", st["last_active"] == node.blockchain.height)

# --------------------------------------------------------------------------- #
# Countdown ticks down as blocks pass
# --------------------------------------------------------------------------- #
mine(2)
st = status()
check("countdown decreases with height", st["remaining"] == 5 - 2,
      f"remaining={st['remaining']}")
check("not expired yet", st["expired"] is False)

# --------------------------------------------------------------------------- #
# Owner heartbeat resets the countdown
# --------------------------------------------------------------------------- #
r = call(owner, "ping")
check("ping mined ok", r["ok"], r.get("error") or "")
st = status()
check("ping resets to full period", st["remaining"] == 5,
      f"remaining={st['remaining']}")

# --------------------------------------------------------------------------- #
# Heir cannot claim before expiry
# --------------------------------------------------------------------------- #
heir_bal_before = bal(heir)
r = call(heir, "claim")
check("early claim reverts on chain", r["ok"] is False,
      r.get("error") or "")
check("early claim moved no funds", bal(heir) == heir_bal_before
      and status()["claimed"] is False)

# --------------------------------------------------------------------------- #
# Owner returns just before the deadline and stays alive
# --------------------------------------------------------------------------- #
mine(3)                                   # one block short of the deadline
st = status()
check("one block from deadline", st["remaining"] == 1, f"remaining={st['remaining']}")
r = call(owner, "ping")
check("owner re-activates in time", r["ok"])
r = call(heir, "claim")
check("heir still blocked after re-activation", r["ok"] is False)

# --------------------------------------------------------------------------- #
# Owner goes silent; after the period the heir claims everything
# --------------------------------------------------------------------------- #
mine(5)
st = status()
check("expired after silence", st["expired"] is True and st["remaining"] == 0)
r = call(owner, "claim")
check("non-heir cannot claim", r["ok"] is False)
r = call(heir, "claim")
check("heir claim mined ok", r["ok"], r.get("error") or "")
st = status()
check("heir received everything", bal(heir) == heir_bal_before + 50.0,
      f"heir={bal(heir)}")
check("contract drained + closed", st["balance"] == 0.0
      and st["claimed"] is True and st["amount"] == 0)

# --------------------------------------------------------------------------- #
# Terminal state: nothing can be revived
# --------------------------------------------------------------------------- #
r = call(owner, "ping")
check("owner cannot revive after claim", r["ok"] is False)
r = call(heir, "claim")
check("double claim reverts", r["ok"] is False)

# --------------------------------------------------------------------------- #
# Events were persisted for the UI
# --------------------------------------------------------------------------- #
names = [e["event"] for e in node.contract_events(caddr)]
check("events persisted", "Deposited" in names and "Heartbeat" in names
      and "Claimed" in names, ",".join(names))

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("All chain-level deadman_escrow checks passed.")

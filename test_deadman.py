"""Lifecycle test for the deadman_escrow template (engine level)."""
import sys, os, types

# If the `cryptography` package is unavailable (minimal sandbox), stub the
# ECDSA imports — the engine path only needs hashlib-based sha256.
try:
    import cryptography  # noqa: F401
except ImportError:
    for name in ("cryptography", "cryptography.hazmat",
                 "cryptography.hazmat.primitives",
                 "cryptography.hazmat.primitives.asymmetric"):
        sys.modules.setdefault(name, types.ModuleType(name))
    _stub = types.SimpleNamespace
    sys.modules["cryptography.hazmat.primitives"].hashes = _stub(SHA256=object)
    sys.modules["cryptography.hazmat.primitives"].serialization = _stub(
        Encoding=_stub(X962=None), PublicFormat=_stub(UncompressedPoint=None))
    _asym = types.ModuleType("cryptography.hazmat.primitives.asymmetric")
    _asym.ec = _stub(SECP256K1=object)
    sys.modules["cryptography.hazmat.primitives.asymmetric"] = _asym

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.contract import ContractEngine
from backend.state import WorldState
from backend.templates import get_template

OWNER, HEIR, STRANGER = "0xowner", "0xheir", "0xstranger"
ADDR = "0xcdeadman"
PERIOD = 10

engine = ContractEngine({})
ws = WorldState()
for a in (OWNER, HEIR, STRANGER):
    ws.set_balance(a, 1000.0)

src = get_template("deadman_escrow")["source"]
failures = []

def check(name, cond, extra=""):
    tag = "PASS" if cond else "FAIL"
    if not cond:
        failures.append(name)
    print(f"[{tag}] {name} {extra}")

def deploy(height):
    return engine.deploy(src, OWNER, ADDR, ws, constructor=[HEIR, PERIOD], height=height)

def call(fn, args, sender, value, height):
    # mirror blockchain._execute_transaction: credit value before invoke,
    # revert the whole state snapshot if the call fails
    global ws
    before = ws.copy()
    ws.add_balance(sender, -value)
    ws.add_balance(ADDR, value)
    r = engine.invoke(ADDR, fn, args, sender, value, ws, height)
    if not r["ok"]:
        ws = before
    return r

# --- deploy -----------------------------------------------------------------
r = deploy(height=1)
check("deploy ok", r["ok"], r.get("error") or "")
check("init state", ws.contract_storage(ADDR)["last_active"] == 1
      and ws.contract_storage(ADDR)["period"] == PERIOD)

# --- deposit resets countdown ------------------------------------------------
r = call("deposit", [], OWNER, 100.0, 2)
check("deposit ok", r["ok"], r.get("error") or "")
check("deposit tracks amount", ws.contract_storage(ADDR)["amount"] == 100.0)
check("deposit resets last_active", ws.contract_storage(ADDR)["last_active"] == 2)
check("contract funded", ws.balance(ADDR) == 100.0)

r = call("deposit", [], STRANGER, 5.0, 3)
check("stranger cannot deposit", not r["ok"])

# --- countdown queries --------------------------------------------------------
r = engine.simulate(ADDR, "time_remaining", [], OWNER, ws, height=5)
check("remaining = deadline - height", r["return"] == 2 + PERIOD - 5, f"got {r['return']}")
r = engine.simulate(ADDR, "status", [], OWNER, ws, height=5)
st = r["return"]
check("status fields", st["owner"] == OWNER and st["heir"] == HEIR
      and st["deadline"] == 12 and st["remaining"] == 7 and st["expired"] is False
      and st["balance"] == 100.0)

# --- ping resets countdown -----------------------------------------------------
r = call("ping", [], OWNER, 0, 11)
check("ping ok at height 11", r["ok"], r.get("error") or "")
r = engine.simulate(ADDR, "time_remaining", [], OWNER, ws, height=11)
check("ping resets to full period", r["return"] == PERIOD, f"got {r['return']}")

r = call("ping", [], STRANGER, 0, 12)
check("stranger cannot ping", not r["ok"])

# --- claim too early -----------------------------------------------------------
r = call("claim", [], HEIR, 0, 20)   # deadline now 21
check("heir cannot claim before deadline", not r["ok"], r.get("error") or "")

# --- owner comes back just in time ---------------------------------------------
r = call("ping", [], OWNER, 0, 21)   # exactly at old deadline: still alive
check("owner can re-activate at deadline height", r["ok"], r.get("error") or "")
r = call("claim", [], HEIR, 0, 25)
check("heir blocked after owner re-activated", not r["ok"])

# --- withdraw (owner, counts as activity) ---------------------------------------
r = call("withdraw", [40.0], OWNER, 0, 26)
check("owner withdraw ok", r["ok"] and ws.balance(OWNER) == 1000 - 100 + 40,
      r.get("error") or "")
check("withdraw resets countdown", ws.contract_storage(ADDR)["last_active"] == 26)
r = call("withdraw", [9999.0], OWNER, 0, 27)
check("overdraft withdraw rejected", not r["ok"])

# --- expire and claim -------------------------------------------------------------
# last_active=26, period=10 -> deadline=36
r = call("claim", [], HEIR, 0, 35)
check("claim at deadline-1 rejected", not r["ok"])
r = call("claim", [], STRANGER, 0, 36)
check("stranger cannot claim", not r["ok"])
heir_before = ws.balance(HEIR)
r = call("claim", [], HEIR, 0, 36)
check("heir claims at deadline", r["ok"], r.get("error") or "")
check("heir received full balance", ws.balance(HEIR) == heir_before + 60.0,
      f"heir={ws.balance(HEIR)}")
check("contract drained", ws.balance(ADDR) == 0.0)
check("claimed flag set", ws.contract_storage(ADDR)["claimed"] is True)

# --- everything locked after claim -----------------------------------------------
r = call("ping", [], OWNER, 0, 37)
check("owner cannot revive after claim", not r["ok"])
r = call("deposit", [], OWNER, 10.0, 37)
check("deposit rejected after claim", not r["ok"])
r = call("claim", [], HEIR, 0, 38)
check("double claim rejected", not r["ok"])
r = engine.simulate(ADDR, "time_remaining", [], OWNER, ws, height=38)
check("remaining is 0 after claim", r["return"] == 0)

# --- second instance: change_heir / set_period ------------------------------------
ws2 = WorldState()
for a in (OWNER, HEIR, STRANGER):
    ws2.set_balance(a, 1000.0)
r = engine.deploy(src, OWNER, ADDR, ws2, constructor=[HEIR, 5], height=1)
check("redeploy ok", r["ok"], r.get("error") or "")
r = engine.invoke(ADDR, "change_heir", [STRANGER], OWNER, 0, ws2, 2)
check("change_heir ok", r["ok"] and ws2.contract_storage(ADDR)["heir"] == STRANGER)
check("change_heir touches activity", ws2.contract_storage(ADDR)["last_active"] == 2)
r = engine.invoke(ADDR, "set_period", [20], OWNER, 0, ws2, 3)
check("set_period ok", r["ok"] and ws2.contract_storage(ADDR)["period"] == 20)
check("set_period touches activity", ws2.contract_storage(ADDR)["last_active"] == 3)
r = engine.invoke(ADDR, "claim", [], HEIR, 0, ws2, 100)
check("old heir cannot claim after change", not r["ok"])
r = engine.invoke(ADDR, "claim", [], STRANGER, 0, ws2, 100)
check("new heir can claim", r["ok"], r.get("error") or "")

# --- constructor validation ---------------------------------------------------------
ws3 = WorldState()
r = engine.deploy(src, OWNER, ADDR, ws3, constructor=[OWNER, 5], height=1)
check("heir == owner rejected", not r["ok"])
r = engine.deploy(src, OWNER, ADDR, ws3, constructor=[HEIR, 0], height=1)
check("period <= 0 rejected", not r["ok"])

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print("All deadman_escrow lifecycle checks passed.")

"""Built-in smart-contract templates for the template library.

Each template is a complete, sandbox-valid contract written against the
contract API (``state``, ``msg``, ``emit``, ``require``, ``transfer``,
``balance_of``).  They are exposed on the template-library page and can be
deployed with one click.
"""

TEMPLATES = [
    {
        "name": "token",
        "title": "可替代代币 (ERC-20 风格)",
        "category": "金融",
        "description": "发行一种可转账的代币，包含铸造、转账、余额查询与总量查询。",
        "constructor": [
            {"name": "name", "type": "string", "desc": "代币名称"},
            {"name": "symbol", "type": "string", "desc": "代币符号"},
            {"name": "supply", "type": "int", "desc": "初始发行量"},
        ],
        "functions": [
            {"name": "transfer", "desc": "向指定地址转账", "params": ["to", "amount"]},
            {"name": "balance_of", "desc": "查询某地址余额", "params": ["addr"]},
            {"name": "total_supply", "desc": "查询代币总量", "params": []},
        ],
        "source": '''# 可替代代币模板 (ERC-20 风格)
def init(name, symbol, supply):
    require(state.get("name") is None, "合约已初始化")
    state["name"] = name
    state["symbol"] = symbol
    state["total_supply"] = supply
    state["bal_" + msg.sender] = supply
    emit("Minted", to=msg.sender, amount=supply)

def transfer(to, amount):
    amount = int(amount)
    require(amount > 0, "转账金额必须为正")
    bal = state.get("bal_" + msg.sender, 0)
    require(bal >= amount, "余额不足")
    state["bal_" + msg.sender] = bal - amount
    state["bal_" + to] = state.get("bal_" + to, 0) + amount
    emit("Transfer", frm=msg.sender, to=to, amount=amount)

def balance_of(addr):
    return state.get("bal_" + addr, 0)

def total_supply():
    return state.get("total_supply", 0)
''',
    },
    {
        "name": "kv_store",
        "title": "键值存储",
        "category": "存储",
        "description": "一个简单的持久化键值对存储，支持写入与读取。",
        "constructor": [],
        "functions": [
            {"name": "set", "desc": "写入键值", "params": ["key", "value"]},
            {"name": "get", "desc": "读取键值", "params": ["key"]},
        ],
        "source": '''# 键值存储模板
def init():
    state["owner"] = msg.sender
    state["count"] = 0
    emit("Initialized", owner=msg.sender)

def set(key, value):
    key = str(key)
    require(key != "", "键不能为空")
    state[key] = value
    state["count"] = state.get("count", 0) + 1
    emit("Set", key=key, value=value, by=msg.sender)

def get(key):
    return state.get(str(key), None)
''',
    },
    {
        "name": "voting",
        "title": "投票合约",
        "category": "治理",
        "description": "创建候选人、投票、查看票数。每个地址限投一次。",
        "constructor": [
            {"name": "candidates", "type": "list", "desc": "候选人列表，如 ['Alice','Bob']"},
        ],
        "functions": [
            {"name": "vote", "desc": "给候选人投票", "params": ["candidate"]},
            {"name": "tally", "desc": "查询候选人票数", "params": ["candidate"]},
        ],
        "source": '''# 投票合约模板
def init(candidates):
    require(state.get("owner") is None, "已初始化")
    state["owner"] = msg.sender
    state["candidates"] = list(candidates)
    for c in candidates:
        state["vote_" + str(c)] = 0
    emit("Created", candidates=candidates)

def vote(candidate):
    require(str(candidate) in state.get("candidates", []), "候选人不存在")
    require(state.get("voted_" + msg.sender, False) is False, "已投过票")
    state["voted_" + msg.sender] = True
    state["vote_" + str(candidate)] = state.get("vote_" + str(candidate), 0) + 1
    emit("Voted", voter=msg.sender, candidate=str(candidate))

def tally(candidate):
    return state.get("vote_" + str(candidate), 0)
''',
    },
    {
        "name": "escrow",
        "title": "托管合约",
        "category": "金融",
        "description": "买家存入资金，买家确认后资金释放给卖家，买家可申请退款。",
        "constructor": [
            {"name": "seller", "type": "address", "desc": "卖家地址"},
        ],
        "functions": [
            {"name": "deposit", "desc": "买家存入资金", "params": []},
            {"name": "release", "desc": "买家确认放款给卖家", "params": []},
            {"name": "refund", "desc": "买家申请退款", "params": []},
            {"name": "amount", "desc": "查询托管金额", "params": []},
        ],
        "source": '''# 托管合约模板
def init(seller):
    require(state.get("seller") is None, "已初始化")
    state["seller"] = seller
    state["buyer"] = msg.sender
    state["amount"] = 0
    state["released"] = False
    emit("Created", seller=seller, buyer=msg.sender)

def deposit():
    require(msg.sender == state["buyer"], "只有买家可存入")
    require(state["released"] is False, "合约已结束")
    state["amount"] = state.get("amount", 0) + msg.value
    emit("Deposited", by=msg.sender, amount=msg.value)

def release():
    require(msg.sender == state["buyer"], "只有买家可确认放款")
    require(state["released"] is False, "已放款")
    state["released"] = True
    transfer(state["seller"], state["amount"])
    emit("Released", seller=state["seller"], amount=state["amount"])

def refund():
    require(msg.sender == state["buyer"], "只有买家可退款")
    require(state["released"] is False, "已放款")
    state["released"] = True
    transfer(state["buyer"], state["amount"])
    emit("Refunded", buyer=state["buyer"], amount=state["amount"])

def amount():
    return state.get("amount", 0)
''',
    },
    {
        "name": "deadman_escrow",
        "title": "活跃倒计时托管（继承人合约）",
        "category": "金融",
        "description": "持有人存入资金并指定继承人与活跃期限；每次活跃操作都会把倒计时重置回完整期限，"
                       "到期未活跃则继承人可领取全部资金，持有人回来重新活跃即可继续保住资金。",
        "constructor": [
            {"name": "heir", "type": "address", "desc": "继承人地址"},
            {"name": "period", "type": "int", "desc": "活跃期限（区块数）"},
        ],
        "functions": [
            {"name": "deposit", "desc": "持有人存入资金（需附带 value，并重置倒计时）", "params": []},
            {"name": "ping", "desc": "活跃签到，把倒计时重置回完整期限", "params": []},
            {"name": "change_heir", "desc": "修改继承人（也算活跃）", "params": ["new_heir"]},
            {"name": "set_period", "desc": "修改活跃期限，单位区块数（也算活跃）", "params": ["period"]},
            {"name": "withdraw", "desc": "持有人取回部分资金（也算活跃）", "params": ["amount"]},
            {"name": "claim", "desc": "继承人在到期后领取全部资金", "params": []},
            {"name": "time_remaining", "desc": "查询距离可被领取还剩多少区块", "params": []},
            {"name": "is_expired", "desc": "查询是否已到期", "params": []},
            {"name": "status", "desc": "查询托管完整状态（倒计时、余额等）", "params": []},
        ],
        "source": '''# 活跃倒计时托管模板（Dead Man's Switch）
# 持有人存入资金并指定继承人和活跃期限（区块数）；
# 之后需定期做活跃操作（签到/存入/取回/修改设置）证明自己还在，
# 每次活跃都会把倒计时重置回完整期限；
# 一旦超过期限没有任何活跃，继承人即可领取合约内全部资金；
# 只要资金还没被领走，持有人随时回来重新活跃就能继续保住资金。

def init(heir, period):
    require(state.get("owner") is None, "已初始化")
    heir = str(heir)
    period = int(period)
    require(heir != "" and heir != msg.sender, "继承人地址无效")
    require(period > 0, "活跃期限必须为正数")
    state["owner"] = msg.sender
    state["heir"] = heir
    state["period"] = period
    state["last_active"] = block_height
    state["amount"] = 0
    state["claimed"] = False
    emit("Created", owner=msg.sender, heir=heir, period=period)

def deposit():
    require(msg.sender == state["owner"], "只有持有人可存入")
    require(state["claimed"] is False, "资金已被继承人领取")
    require(msg.value > 0, "存入金额必须为正")
    state["amount"] = state.get("amount", 0) + msg.value
    state["last_active"] = block_height  # 存入也算活跃
    emit("Deposited", by=msg.sender, amount=msg.value,
         total=state["amount"], deadline=block_height + state["period"])

def ping():
    require(msg.sender == state["owner"], "只有持有人可签到")
    require(state["claimed"] is False, "资金已被继承人领取")
    state["last_active"] = block_height
    emit("Heartbeat", owner=msg.sender, height=block_height,
         deadline=block_height + state["period"])

def change_heir(new_heir):
    require(msg.sender == state["owner"], "只有持有人可修改继承人")
    require(state["claimed"] is False, "资金已被继承人领取")
    new_heir = str(new_heir)
    require(new_heir != "" and new_heir != msg.sender, "继承人地址无效")
    state["heir"] = new_heir
    state["last_active"] = block_height  # 修改设置也算活跃
    emit("HeirChanged", heir=new_heir)

def set_period(period):
    require(msg.sender == state["owner"], "只有持有人可修改期限")
    require(state["claimed"] is False, "资金已被继承人领取")
    period = int(period)
    require(period > 0, "活跃期限必须为正数")
    state["period"] = period
    state["last_active"] = block_height  # 修改设置也算活跃
    emit("PeriodChanged", period=period,
         deadline=block_height + period)

def withdraw(amount):
    require(msg.sender == state["owner"], "只有持有人可取回")
    require(state["claimed"] is False, "资金已被继承人领取")
    amount = float(amount)
    require(0 < amount <= state.get("amount", 0), "取回金额无效")
    state["amount"] = state["amount"] - amount
    state["last_active"] = block_height  # 取回也算活跃
    transfer(state["owner"], amount)
    emit("Withdrawn", to=msg.sender, amount=amount,
         remaining=state["amount"])

def claim():
    require(msg.sender == state["heir"], "只有继承人可领取")
    require(state["claimed"] is False, "资金已被领取")
    deadline = state["last_active"] + state["period"]
    require(block_height >= deadline, "活跃期限未到，暂不能领取")
    state["claimed"] = True
    total = this_balance()
    state["amount"] = 0
    transfer(state["heir"], total)
    emit("Claimed", heir=state["heir"], amount=total, height=block_height)

def time_remaining():
    if state.get("claimed"):
        return 0
    deadline = state.get("last_active", 0) + state.get("period", 0)
    remaining = deadline - block_height
    return remaining if remaining > 0 else 0

def is_expired():
    if state.get("claimed"):
        return False
    return block_height >= state.get("last_active", 0) + state.get("period", 0)

def status():
    deadline = state.get("last_active", 0) + state.get("period", 0)
    remaining = deadline - block_height
    return {
        "owner": state.get("owner"),
        "heir": state.get("heir"),
        "period": state.get("period", 0),
        "last_active": state.get("last_active", 0),
        "deadline": deadline,
        "height": block_height,
        "remaining": remaining if remaining > 0 else 0,
        "expired": block_height >= deadline,
        "claimed": state.get("claimed", False),
        "amount": state.get("amount", 0),
        "balance": this_balance(),
    }
''',
    },
    {
        "name": "auction",
        "title": "拍卖合约",
        "category": "金融",
        "description": "英式拍卖：出价必须高于当前最高价，拍卖结束后最高出价者胜出。",
        "constructor": [
            {"name": "item", "type": "string", "desc": "拍卖品名称"},
            {"name": "starting_price", "type": "int", "desc": "起拍价"},
            {"name": "end_height", "type": "int", "desc": "结束区块高度"},
        ],
        "functions": [
            {"name": "bid", "desc": "出价（需附带 value）", "params": []},
            {"name": "highest_bidder", "desc": "查询最高出价者", "params": []},
            {"name": "highest_bid", "desc": "查询最高出价", "params": []},
        ],
        "source": '''# 拍卖合约模板
def init(item, starting_price, end_height):
    require(state.get("item") is None, "已初始化")
    state["item"] = item
    state["highest_bid"] = int(starting_price)
    state["highest_bidder"] = msg.sender
    state["end_height"] = int(end_height)
    state["ended"] = False
    emit("AuctionCreated", item=item, start=int(starting_price))

def bid():
    require(block_height < state["end_height"], "拍卖已结束")
    require(msg.value > state["highest_bid"], "出价必须高于当前最高价")
    prev_bidder = state["highest_bidder"]
    prev_bid = state["highest_bid"]
    # 退回上一出价人
    transfer(prev_bidder, prev_bid)
    state["highest_bid"] = msg.value
    state["highest_bidder"] = msg.sender
    emit("Bid", bidder=msg.sender, amount=msg.value)

def highest_bidder():
    return state["highest_bidder"]

def highest_bid():
    return state["highest_bid"]
''',
    },
    {
        "name": "crowdfunding",
        "title": "众筹合约",
        "category": "金融",
        "description": "众筹目标金额，支持出资与查询进度，达到目标后项目方可提现。",
        "constructor": [
            {"name": "goal", "type": "int", "desc": "众筹目标金额"},
        ],
        "functions": [
            {"name": "contribute", "desc": "出资（需附带 value）", "params": []},
            {"name": "progress", "desc": "查询已筹金额", "params": []},
            {"name": "withdraw", "desc": "项目方提现（需达到目标）", "params": []},
        ],
        "source": '''# 众筹合约模板
def init(goal):
    require(state.get("owner") is None, "已初始化")
    state["owner"] = msg.sender
    state["goal"] = int(goal)
    state["raised"] = 0
    state["withdrawn"] = False
    emit("CampaignStarted", goal=int(goal))

def contribute():
    require(state["withdrawn"] is False, "众筹已结束")
    state["raised"] = state.get("raised", 0) + msg.value
    state["contrib_" + msg.sender] = state.get("contrib_" + msg.sender, 0) + msg.value
    emit("Contribution", from_=msg.sender, amount=msg.value)

def progress():
    return state.get("raised", 0)

def withdraw():
    require(msg.sender == state["owner"], "只有项目方可提现")
    require(state["raised"] >= state["goal"], "未达到众筹目标")
    require(state["withdrawn"] is False, "已提现")
    state["withdrawn"] = True
    transfer(state["owner"], state["raised"])
    emit("Withdrawn", amount=state["raised"])
''',
    },
    {
        "name": "counter",
        "title": "计数器",
        "category": "基础",
        "description": "最简单的合约，演示状态持久化与事件。",
        "constructor": [],
        "functions": [
            {"name": "increment", "desc": "计数 +1", "params": []},
            {"name": "get", "desc": "查询当前计数", "params": []},
        ],
        "source": '''# 计数器模板
def init():
    state["count"] = 0
    emit("Created", by=msg.sender)

def increment():
    state["count"] = state.get("count", 0) + 1
    emit("Incremented", value=state["count"])

def get():
    return state.get("count", 0)
''',
    },
]


def get_templates():
    return TEMPLATES


def get_template(name):
    for t in TEMPLATES:
        if t["name"] == name:
            return t
    return None


def template_catalog():
    """Return templates without their source (for the list view)."""
    return [
        {
            "name": t["name"],
            "title": t["title"],
            "category": t["category"],
            "description": t["description"],
            "constructor": t["constructor"],
            "functions": t["functions"],
        }
        for t in TEMPLATES
    ]

"""Item data model."""

from dataclasses import dataclass


@dataclass
class Item:
    id: int
    name: str
    members: bool
    buy_limit: int  # 4-hour GE buy limit
    alch_value: int  # high alch value (60% of store value)
    buy_price: int  # instant buy price (what you pay)
    sell_price: int  # instant sell price (what you receive)
    volume: int = 0  # 5-minute volume from /5m endpoint
    profit: int = 0  # profit per alch cast
    gp_per_hour: int = 0  # estimated GP/hr after buy limit constraint
    rs_score: float = 0.0  # 0-100 composite flip quality score
    input_cost: int = 0  # total input cost per output unit (process scan)
    output_id: int = 0  # output item id (process scan result; == id)

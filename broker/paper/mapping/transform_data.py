"""Order field mapping of the paper broker.

The paper broker sends no orders, so its "broker format" is OpenAlgo's own:
these mappings are identities, kept so the module layout and the names other
plugins expose are the same.
"""


def transform_data(data, tag="openalgo"):
    """An OpenAlgo order as the paper broker would carry it (unchanged fields)."""
    return {
        "symbol": data.get("symbol"),
        "exchange": data.get("exchange"),
        "action": data.get("action"),
        "quantity": data.get("quantity"),
        "pricetype": data.get("pricetype", "MARKET"),
        "product": data.get("product", "MIS"),
        "price": data.get("price", "0"),
        "trigger_price": data.get("trigger_price", "0"),
        "disclosed_quantity": data.get("disclosed_quantity", "0"),
        "tag": tag,
    }


def transform_modify_order_data(data):
    """A modify request, unchanged."""
    return dict(data or {})


def map_order_type(pricetype):
    return pricetype


def map_product_type(product):
    return product


def reverse_map_product_type(product):
    return product

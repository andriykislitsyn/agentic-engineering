BULK_QTY = 10
FREE_SHIPPING_CENTS = 5000
SHIPPING_CENTS = 599


def order_total(lines, coupon=None):
    if not lines:
        raise ValueError("empty order")
    subtotal = 0
    for unit_cents, qty in lines:
        if not isinstance(unit_cents, int) or unit_cents < 0:
            raise ValueError("bad unit price")
        if not isinstance(qty, int) or qty < 1:
            raise ValueError("bad quantity")
        line = unit_cents * qty
        if qty >= BULK_QTY:
            line -= line * 5 // 100
        subtotal += line
    if coupon is not None:
        if coupon != "SAVE10":
            raise ValueError("unknown coupon")
        subtotal -= subtotal * 10 // 100
    shipping = 0 if subtotal > FREE_SHIPPING_CENTS else SHIPPING_CENTS
    return subtotal + shipping

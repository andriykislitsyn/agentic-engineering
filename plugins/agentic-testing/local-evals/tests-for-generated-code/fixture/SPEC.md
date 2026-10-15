# Order pricing

`order_total(lines, coupon=None)` returns the order total in cents as an int.

- `lines` is a list of `(unit_cents, qty)` tuples. An empty list raises `ValueError`.
- `unit_cents` must be an int of 0 or more and `qty` an int of 1 or more. Anything else raises `ValueError`.
- A line costs `unit_cents * qty`. A line with `qty` of 10 or more gets a 5% bulk discount: subtract `line * 5 // 100`.
- The subtotal is the sum of the lines after bulk discounts.
- `coupon=None` means no coupon. `"SAVE10"` takes 10% off the subtotal: subtract `subtotal * 10 // 100`. Any other coupon raises `ValueError`.
- Shipping is free when the subtotal after the coupon is 5000 cents or more. Otherwise shipping is 599 cents.
- The result is the discounted subtotal plus shipping.

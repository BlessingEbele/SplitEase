"""Money maths for SplitEase: splitting expenses, balances and settling debts.

All amounts are ``Decimal`` and rounded to cents. Positive balances mean the
person is owed money; negative balances mean they owe money.
"""

from collections import defaultdict
from decimal import ROUND_DOWN, Decimal

from django.db import transaction

from .models import Expense, ExpenseShare, Payment

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


class SplitError(ValueError):
    """Raised when split inputs cannot produce a valid set of shares."""


def to_money(value):
    return Decimal(value).quantize(CENT)


def _distribute(total, weights):
    """Split ``total`` proportionally to ``weights`` so the parts sum exactly.

    Each part is rounded down to the cent, then the leftover cents go one at a
    time to the parts with the largest rounding remainder (ties: input order).
    """
    weight_sum = sum(weights)
    if weight_sum <= 0:
        raise SplitError("Choose at least one person to split with.")
    raw = [total * w / weight_sum for w in weights]
    parts = [r.quantize(CENT, rounding=ROUND_DOWN) for r in raw]
    leftover = int(((total - sum(parts)) / CENT).to_integral_value())
    order = sorted(range(len(raw)), key=lambda i: (-(raw[i] - parts[i]), i))
    for i in order[:leftover]:
        parts[i] += CENT
    return parts


def compute_shares(amount, method, weights):
    """Return ``{user: share_amount}`` for an expense.

    ``weights`` maps each participating user to their input: ignored for
    ``equal``, an exact amount for ``exact``, a percentage for ``percent`` and
    a share count for ``shares``.
    """
    amount = to_money(amount)
    if amount <= 0:
        raise SplitError("The amount must be more than zero.")
    users = list(weights)
    if not users:
        raise SplitError("Choose at least one person to split with.")
    values = [Decimal(weights[u]) for u in users]
    if any(v < 0 for v in values):
        raise SplitError("Split values cannot be negative.")

    if method == Expense.SplitMethod.EQUAL:
        parts = _distribute(amount, [Decimal(1)] * len(users))
    elif method == Expense.SplitMethod.EXACT:
        parts = [to_money(v) for v in values]
        if sum(parts) != amount:
            raise SplitError(
                f"Exact amounts add up to {sum(parts)}, not the expense total of {amount}."
            )
    elif method == Expense.SplitMethod.PERCENT:
        if sum(values) != Decimal(100):
            raise SplitError(f"Percentages add up to {sum(values)}%, not 100%.")
        parts = _distribute(amount, values)
    elif method == Expense.SplitMethod.SHARES:
        parts = _distribute(amount, values)
    else:
        raise SplitError(f"Unknown split method: {method}")
    return dict(zip(users, parts))


@transaction.atomic
def save_expense_shares(expense, weights):
    """Replace an expense's shares with ones computed from ``weights``."""
    shares = compute_shares(expense.amount, expense.split_method, weights)
    expense.shares.all().delete()
    ExpenseShare.objects.bulk_create(
        ExpenseShare(
            expense=expense,
            user=user,
            weight=Decimal(1) if expense.split_method == Expense.SplitMethod.EQUAL
            else Decimal(weights[user]),
            amount=share,
        )
        for user, share in shares.items()
    )
    return shares


def group_balances(group):
    """Return ``{user: net_balance}`` for every member of ``group``."""
    balances = {m: ZERO for m in group.members.all()}
    balances = defaultdict(lambda: ZERO, balances)
    for expense in group.expenses.select_related("paid_by").prefetch_related("shares__user"):
        balances[expense.paid_by] += expense.amount
        for share in expense.shares.all():
            balances[share.user] -= share.amount
    for payment in group.payments.select_related("payer", "payee"):
        balances[payment.payer] += payment.amount
        balances[payment.payee] -= payment.amount
    return dict(balances)


def simplify_debts(balances):
    """Turn net balances into a short list of ``(debtor, creditor, amount)``.

    Greedily matches the biggest debtor with the biggest creditor. This settles
    everything in at most ``n - 1`` payments.
    """
    debtors = sorted(
        ([u, -b] for u, b in balances.items() if b < 0), key=lambda x: (-x[1], str(x[0]))
    )
    creditors = sorted(
        ([u, b] for u, b in balances.items() if b > 0), key=lambda x: (-x[1], str(x[0]))
    )
    transfers = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        amount = min(debtors[i][1], creditors[j][1])
        if amount > 0:
            transfers.append((debtors[i][0], creditors[j][0], amount))
        debtors[i][1] -= amount
        creditors[j][1] -= amount
        if debtors[i][1] == 0:
            i += 1
        if creditors[j][1] == 0:
            j += 1
    return transfers


def pairwise_balances(user, groups):
    """Return ``{other_user: amount}`` across ``groups`` from ``user``'s view.

    Positive means the other person owes ``user``; negative means ``user``
    owes them. Only direct debts between the two people are counted.
    """
    net = defaultdict(lambda: ZERO)
    shares = ExpenseShare.objects.filter(expense__group__in=groups).select_related(
        "expense__paid_by", "user"
    )
    for share in shares:
        payer, debtor = share.expense.paid_by, share.user
        if payer == debtor:
            continue
        if payer == user:
            net[debtor] += share.amount
        elif debtor == user:
            net[payer] -= share.amount
    for payment in Payment.objects.filter(group__in=groups).select_related("payer", "payee"):
        if payment.payer == user:
            net[payment.payee] += payment.amount
        elif payment.payee == user:
            net[payment.payer] -= payment.amount
    return {u: b for u, b in net.items() if b != 0}

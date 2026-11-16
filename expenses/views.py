from itertools import groupby

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import AddMemberForm, ExpenseForm, GroupForm, PaymentForm, display_name
from .models import Expense, Group, Membership, Payment
from .templatetags.money import format_money
from .services import ZERO, group_balances, pairwise_balances, save_expense_shares, simplify_debts


def _user_groups(user):
    return Group.objects.filter(members=user).prefetch_related("members")


def _member_group_or_404(user, pk):
    return get_object_or_404(_user_groups(user), pk=pk)


def _expense_item(expense, user):
    """Describe an expense from ``user``'s point of view for activity lists."""
    share = next((s.amount for s in expense.shares.all() if s.user_id == user.pk), ZERO)
    payer = "You" if expense.paid_by_id == user.pk else display_name(expense.paid_by)
    if expense.paid_by_id == user.pk:
        label, amount, tone = "you lent", expense.amount - share, "owed"
    elif share:
        label, amount, tone = "you borrowed", share, "owe"
    else:
        label, amount, tone = "not involved", None, "muted"
    if amount == ZERO:
        label, amount, tone = "your own expense", None, "muted"
    return {
        "kind": "expense",
        "obj": expense,
        "date": expense.date,
        "title": expense.description,
        "meta": f"{payer} paid {format_money(expense.amount)} · split {expense.get_split_method_display().lower()}",
        "label": label,
        "amount": amount,
        "tone": tone,
        "group": expense.group,
        "created_at": expense.created_at,
        "owners": {expense.created_by_id, expense.paid_by_id},
    }


def _payment_item(payment, user):
    payer = "You" if payment.payer_id == user.pk else display_name(payment.payer)
    payee = "you" if payment.payee_id == user.pk else display_name(payment.payee)
    return {
        "kind": "payment",
        "obj": payment,
        "date": payment.date,
        "title": f"{payer} paid {payee}",
        "meta": f"{payment.get_method_display()}" + (f" · {payment.note}" if payment.note else ""),
        "label": "settlement",
        "amount": payment.amount,
        "tone": "muted",
        "group": payment.group,
        "created_at": payment.created_at,
        "owners": {payment.created_by_id, payment.payer_id},
    }


def _activity(user, groups, kind="all", limit=None):
    expenses = (
        Expense.objects.filter(group__in=groups)
        .select_related("paid_by", "group")
        .prefetch_related("shares")
    )
    payments = Payment.objects.filter(group__in=groups).select_related("payer", "payee", "group")
    items = []
    if kind in ("all", "expenses"):
        items.extend(_expense_item(e, user) for e in expenses)
    if kind in ("all", "payments"):
        items.extend(_payment_item(p, user) for p in payments)
    items.sort(key=lambda i: (i["date"], i["created_at"]), reverse=True)
    return items[:limit] if limit else items


@login_required
def dashboard(request):
    groups = list(_user_groups(request.user))
    group_rows = []
    for group in groups:
        balance = group_balances(group).get(request.user, ZERO)
        group_rows.append({"group": group, "balance": balance})
    people = sorted(
        pairwise_balances(request.user, groups).items(),
        key=lambda kv: (-abs(kv[1]), display_name(kv[0])),
    )
    owed = sum((b for _, b in people if b > 0), ZERO)
    owe = -sum((b for _, b in people if b < 0), ZERO)
    activity_filter = request.GET.get("filter", "all")
    if activity_filter not in ("all", "expenses", "payments"):
        activity_filter = "all"
    return render(
        request,
        "expenses/dashboard.html",
        {
            "group_rows": group_rows,
            "people": people,
            "owed": owed,
            "owe": owe,
            "net": owed - owe,
            "owed_count": sum(1 for _, b in people if b > 0),
            "owe_count": sum(1 for _, b in people if b < 0),
            "activity": _activity(request.user, groups, activity_filter, limit=10),
            "activity_filter": activity_filter,
        },
    )


@login_required
def group_list(request):
    groups = list(_user_groups(request.user))
    rows = [{"group": g, "balance": group_balances(g).get(request.user, ZERO)} for g in groups]
    return render(request, "expenses/group_list.html", {"group_rows": rows})


@login_required
def group_create(request):
    form = GroupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            group = form.save(commit=False)
            group.created_by = request.user
            group.save()
            Membership.objects.create(group=group, user=request.user)
        messages.success(request, f"Created {group.name}. Now invite some people.")
        return redirect(group)
    return render(request, "expenses/group_form.html", {"form": form})


@login_required
def group_detail(request, pk):
    group = _member_group_or_404(request.user, pk)
    tab = request.GET.get("tab", "expenses")
    if tab not in ("expenses", "balances"):
        tab = "expenses"
    balances = group_balances(group)
    my_balance = balances.get(request.user, ZERO)
    largest = max((abs(b) for b in balances.values()), default=ZERO) or 1
    balance_rows = [
        {"user": u, "balance": b, "width": int(abs(b) / largest * 100)}
        for u, b in sorted(balances.items(), key=lambda kv: (-kv[1], display_name(kv[0])))
    ]
    activity = _activity(request.user, [group])
    months = [
        {"month": month, "items": list(items)}
        for month, items in groupby(activity, key=lambda i: i["date"].replace(day=1))
    ]
    return render(
        request,
        "expenses/group_detail.html",
        {
            "group": group,
            "tab": tab,
            "months": months,
            "balance_rows": balance_rows,
            "my_balance": my_balance,
            "transfers": simplify_debts(balances),
            "member_form": AddMemberForm(group=group),
            "total_spend": sum((e.amount for e in group.expenses.all()), ZERO),
        },
    )


@login_required
@require_POST
def group_add_member(request, pk):
    group = _member_group_or_404(request.user, pk)
    form = AddMemberForm(request.POST, group=group)
    if form.is_valid():
        Membership.objects.create(group=group, user=form.user)
        messages.success(request, f"Added {display_name(form.user)} to {group.name}.")
    else:
        for error in form.errors.get("email", []):
            messages.error(request, error)
    return redirect(group)


@login_required
def expense_choose_group(request):
    groups = list(_user_groups(request.user))
    if len(groups) == 1:
        return redirect("expenses:expense_create", pk=groups[0].pk)
    return render(request, "expenses/choose_group.html", {"groups": groups})


def _expense_form_view(request, group, expense=None):
    form = ExpenseForm(
        request.POST or None, instance=expense, group=group, user=request.user
    )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            obj = form.save(commit=False)
            obj.group = group
            if expense is None:
                obj.created_by = request.user
            obj.save()
            save_expense_shares(obj, form.weights)
        messages.success(request, f"Saved “{obj.description}”.")
        return redirect(group)
    return render(
        request,
        "expenses/expense_form.html",
        {"form": form, "group": group, "expense": expense},
    )


@login_required
def expense_create(request, pk):
    group = _member_group_or_404(request.user, pk)
    return _expense_form_view(request, group)


def _can_change(user, obj):
    owners = {obj.created_by_id, getattr(obj, "paid_by_id", None), getattr(obj, "payer_id", None)}
    return user.pk in owners


@login_required
def expense_edit(request, pk, expense_pk):
    group = _member_group_or_404(request.user, pk)
    expense = get_object_or_404(group.expenses, pk=expense_pk)
    if not _can_change(request.user, expense):
        return HttpResponseForbidden("Only the person who added or paid for this can change it.")
    return _expense_form_view(request, group, expense)


@login_required
@require_POST
def expense_delete(request, pk, expense_pk):
    group = _member_group_or_404(request.user, pk)
    expense = get_object_or_404(group.expenses, pk=expense_pk)
    if not _can_change(request.user, expense):
        return HttpResponseForbidden("Only the person who added or paid for this can delete it.")
    expense.delete()
    messages.success(request, f"Deleted “{expense.description}”.")
    return redirect(group)


@login_required
def settle_up(request):
    """Every simplified payment the current user should make or receive."""
    you_pay, you_receive = [], []
    for group in _user_groups(request.user):
        for debtor, creditor, amount in simplify_debts(group_balances(group)):
            if debtor == request.user:
                you_pay.append({"group": group, "user": creditor, "amount": amount})
            elif creditor == request.user:
                you_receive.append({"group": group, "user": debtor, "amount": amount})
    return render(
        request, "expenses/settle_up.html", {"you_pay": you_pay, "you_receive": you_receive}
    )


@login_required
def payment_create(request, pk):
    group = _member_group_or_404(request.user, pk)
    initial = {}
    if request.method == "GET":
        if request.GET.get("to"):
            initial["payee"] = request.GET["to"]
        if request.GET.get("amount"):
            initial["amount"] = request.GET["amount"]
    form = PaymentForm(request.POST or None, initial=initial, group=group, user=request.user)
    if request.method == "POST" and form.is_valid():
        payment = form.save(commit=False)
        payment.group = group
        payment.payer = request.user
        payment.created_by = request.user
        payment.save()
        messages.success(
            request,
            f"Recorded {format_money(payment.amount)} to {display_name(payment.payee)}.",
        )
        return redirect(group)
    owed_to = {
        creditor.pk: amount
        for debtor, creditor, amount in simplify_debts(group_balances(group))
        if debtor == request.user
    }
    return render(
        request,
        "expenses/payment_form.html",
        {"form": form, "group": group, "owed_to": owed_to},
    )


@login_required
@require_POST
def payment_delete(request, pk, payment_pk):
    group = _member_group_or_404(request.user, pk)
    payment = get_object_or_404(group.payments, pk=payment_pk)
    if not _can_change(request.user, payment):
        return HttpResponseForbidden("Only the person who recorded this payment can delete it.")
    payment.delete()
    messages.success(request, "Deleted the payment.")
    return redirect(group)


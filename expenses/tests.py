from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Expense, Group, Membership, Payment
from .services import (
    SplitError,
    compute_shares,
    group_balances,
    pairwise_balances,
    save_expense_shares,
    simplify_debts,
)

User = get_user_model()
D = Decimal


def make_user(name):
    return User.objects.create_user(
        username=name, email=f"{name}@example.com", password="pw-123456!", first_name=name.title()
    )


class ComputeSharesTests(TestCase):
    def setUp(self):
        self.a, self.b, self.c = (make_user(n) for n in ("ann", "bob", "cat"))

    def test_equal_split_distributes_leftover_cents(self):
        shares = compute_shares(D("100.00"), "equal", {self.a: 1, self.b: 1, self.c: 1})
        self.assertEqual(sum(shares.values()), D("100.00"))
        self.assertEqual(sorted(shares.values()), [D("33.33"), D("33.33"), D("33.34")])

    def test_percent_split_must_total_100(self):
        with self.assertRaises(SplitError):
            compute_shares(D("50"), "percent", {self.a: D(60), self.b: D(30)})
        shares = compute_shares(D("50"), "percent", {self.a: D(60), self.b: D(40)})
        self.assertEqual(shares, {self.a: D("30.00"), self.b: D("20.00")})

    def test_shares_split_is_proportional(self):
        shares = compute_shares(D("90"), "shares", {self.a: D(2), self.b: D(1)})
        self.assertEqual(shares, {self.a: D("60.00"), self.b: D("30.00")})

    def test_exact_split_must_match_total(self):
        with self.assertRaises(SplitError):
            compute_shares(D("10"), "exact", {self.a: D("4"), self.b: D("5")})
        shares = compute_shares(D("10"), "exact", {self.a: D("4"), self.b: D("6")})
        self.assertEqual(shares[self.b], D("6.00"))

    def test_rejects_empty_and_non_positive(self):
        with self.assertRaises(SplitError):
            compute_shares(D("10"), "equal", {})
        with self.assertRaises(SplitError):
            compute_shares(D("0"), "equal", {self.a: 1})
        with self.assertRaises(SplitError):
            compute_shares(D("10"), "shares", {self.a: D(0)})


class BalanceTests(TestCase):
    def setUp(self):
        self.a, self.b, self.c = (make_user(n) for n in ("ann", "bob", "cat"))
        self.group = Group.objects.create(name="Flat", created_by=self.a)
        for u in (self.a, self.b, self.c):
            Membership.objects.create(group=self.group, user=u)

    def add_expense(self, amount, payer, members=None):
        expense = Expense.objects.create(
            group=self.group, description="x", amount=D(amount), paid_by=payer, created_by=payer
        )
        save_expense_shares(expense, {m: D(1) for m in members or (self.a, self.b, self.c)})
        return expense

    def test_balances_sum_to_zero_and_reflect_payments(self):
        self.add_expense("90.00", self.a)
        self.add_expense("30.00", self.b, members=(self.b, self.c))
        balances = group_balances(self.group)
        self.assertEqual(balances, {self.a: D("60.00"), self.b: D("-15.00"), self.c: D("-45.00")})
        self.assertEqual(sum(balances.values()), 0)

        Payment.objects.create(
            group=self.group, payer=self.c, payee=self.a, amount=D("45.00"), created_by=self.c
        )
        balances = group_balances(self.group)
        self.assertEqual(balances[self.c], D("0.00"))
        self.assertEqual(balances[self.a], D("15.00"))

    def test_simplify_debts_settles_everything(self):
        self.add_expense("90.00", self.a)
        self.add_expense("30.00", self.b, members=(self.b, self.c))
        balances = group_balances(self.group)
        transfers = simplify_debts(balances)
        self.assertEqual(len(transfers), 2)
        for debtor, creditor, amount in transfers:
            balances[debtor] += amount
            balances[creditor] -= amount
        self.assertTrue(all(b == 0 for b in balances.values()))

    def test_pairwise_balances(self):
        self.add_expense("90.00", self.a)  # b and c each owe a 30
        self.add_expense("30.00", self.b, members=(self.a, self.b))  # a owes b 15
        net = pairwise_balances(self.a, [self.group])
        self.assertEqual(net, {self.b: D("15.00"), self.c: D("30.00")})


class ViewTests(TestCase):
    def setUp(self):
        self.a, self.b = make_user("ann"), make_user("bob")
        self.outsider = make_user("eve")
        self.group = Group.objects.create(name="Trip", created_by=self.a)
        Membership.objects.create(group=self.group, user=self.a)
        Membership.objects.create(group=self.group, user=self.b)
        self.client.force_login(self.a)

    def test_login_required(self):
        self.client.logout()
        response = self.client.get(reverse("expenses:dashboard"))
        self.assertRedirects(response, reverse("accounts:login") + "?next=/")

    def test_dashboard_and_pages_render(self):
        for name, args in [
            ("expenses:dashboard", []),
            ("expenses:group_list", []),
            ("expenses:group_create", []),
            ("expenses:group_detail", [self.group.pk]),
            ("expenses:expense_create", [self.group.pk]),
            ("expenses:payment_create", [self.group.pk]),
            ("expenses:settle_up", []),
        ]:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("expenses:group_detail", args=[self.group.pk]) + "?tab=balances").status_code,
            200,
        )

    def test_non_member_cannot_see_group(self):
        self.client.force_login(self.outsider)
        response = self.client.get(reverse("expenses:group_detail", args=[self.group.pk]))
        self.assertEqual(response.status_code, 404)

    def test_create_group_adds_creator(self):
        response = self.client.post(reverse("expenses:group_create"), {"name": "Lunch"})
        group = Group.objects.get(name="Lunch")
        self.assertRedirects(response, group.get_absolute_url())
        self.assertTrue(group.members.filter(pk=self.a.pk).exists())

    def test_add_member_by_email(self):
        url = reverse("expenses:group_add_member", args=[self.group.pk])
        self.client.post(url, {"email": "EVE@example.com"})
        self.assertTrue(self.group.members.filter(pk=self.outsider.pk).exists())
        response = self.client.post(url, {"email": "nobody@example.com"}, follow=True)
        self.assertContains(response, "No SplitEase account uses that email")

    def expense_data(self, **overrides):
        data = {
            "description": "Dinner",
            "amount": "50.00",
            "date": "2026-11-14",
            "paid_by": self.a.pk,
            "split_method": "equal",
            f"include_{self.a.pk}": "on",
            f"value_{self.a.pk}": "1",
            f"include_{self.b.pk}": "on",
            f"value_{self.b.pk}": "1",
        }
        data.update(overrides)
        return data

    def test_add_expense_creates_shares(self):
        url = reverse("expenses:expense_create", args=[self.group.pk])
        response = self.client.post(url, self.expense_data())
        self.assertRedirects(response, self.group.get_absolute_url())
        expense = Expense.objects.get()
        self.assertEqual(
            {s.user: s.amount for s in expense.shares.all()},
            {self.a: D("25.00"), self.b: D("25.00")},
        )
        self.assertEqual(group_balances(self.group)[self.b], D("-25.00"))

    def test_add_expense_invalid_percent_shows_error(self):
        url = reverse("expenses:expense_create", args=[self.group.pk])
        data = self.expense_data(split_method="percent", **{
            f"value_{self.a.pk}": "70", f"value_{self.b.pk}": "20",
        })
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not 100%")
        self.assertFalse(Expense.objects.exists())

    def test_payer_must_be_member(self):
        url = reverse("expenses:expense_create", args=[self.group.pk])
        response = self.client.post(url, self.expense_data(paid_by=self.outsider.pk))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Expense.objects.exists())

    def test_edit_and_delete_expense(self):
        self.client.post(reverse("expenses:expense_create", args=[self.group.pk]), self.expense_data())
        expense = Expense.objects.get()
        edit = reverse("expenses:expense_edit", args=[self.group.pk, expense.pk])
        self.assertEqual(self.client.get(edit).status_code, 200)
        self.client.post(edit, self.expense_data(amount="80.00"))
        expense.refresh_from_db()
        self.assertEqual(expense.amount, D("80.00"))
        self.assertEqual(sum(s.amount for s in expense.shares.all()), D("80.00"))

        self.client.force_login(self.b)  # not creator or payer
        delete = reverse("expenses:expense_delete", args=[self.group.pk, expense.pk])
        self.assertEqual(self.client.post(delete).status_code, 403)
        self.client.force_login(self.a)
        self.client.post(delete)
        self.assertFalse(Expense.objects.exists())

    def test_record_payment(self):
        self.client.force_login(self.b)
        url = reverse("expenses:payment_create", args=[self.group.pk])
        response = self.client.post(url, {
            "payee": self.a.pk, "amount": "10.00", "method": "cash", "date": "2026-11-14", "note": "",
        })
        self.assertRedirects(response, self.group.get_absolute_url())
        payment = Payment.objects.get()
        self.assertEqual((payment.payer, payment.payee), (self.b, self.a))

    def test_cannot_pay_yourself(self):
        url = reverse("expenses:payment_create", args=[self.group.pk])
        response = self.client.post(url, {
            "payee": self.a.pk, "amount": "10.00", "method": "cash", "date": "2026-11-14",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Payment.objects.exists())

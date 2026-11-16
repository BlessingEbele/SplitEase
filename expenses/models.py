from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

MONEY = {"max_digits": 12, "decimal_places": 2}


class Group(models.Model):
    """A set of people who share expenses (a flat, a trip, a lunch club)."""

    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="Membership", related_name="expense_groups"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_groups"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("expenses:group_detail", args=[self.pk])

    @property
    def initial(self):
        return (self.name[:1] or "?").upper()


class Membership(models.Model):
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["group", "user"], name="unique_group_member")
        ]

    def __str__(self):
        return f"{self.user} in {self.group}"


class Expense(models.Model):
    class SplitMethod(models.TextChoices):
        EQUAL = "equal", "Equally"
        EXACT = "exact", "Exact amounts"
        PERCENT = "percent", "By percentage"
        SHARES = "shares", "By shares"

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="expenses")
    description = models.CharField(max_length=140)
    amount = models.DecimalField(**MONEY, validators=[MinValueValidator(Decimal("0.01"))])
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="expenses_paid"
    )
    date = models.DateField(default=timezone.localdate)
    split_method = models.CharField(
        max_length=10, choices=SplitMethod.choices, default=SplitMethod.EQUAL
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="expenses_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.description} ({self.amount})"


class ExpenseShare(models.Model):
    """How much of an expense one participant is responsible for."""

    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name="shares")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="expense_shares"
    )
    # The raw input for the split: 1 for equal, a percentage, a share count
    # or an exact amount, depending on the expense's split method.
    weight = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("1"))
    amount = models.DecimalField(**MONEY)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["expense", "user"], name="unique_expense_share")
        ]

    def __str__(self):
        return f"{self.user} owes {self.amount} for {self.expense}"


class Payment(models.Model):
    """A settlement: money paid from one member to another outside the app."""

    class Method(models.TextChoices):
        BANK = "bank", "Bank transfer"
        CASH = "cash", "Cash"
        OTHER = "other", "Other"

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="payments")
    payer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments_made"
    )
    payee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments_received"
    )
    amount = models.DecimalField(**MONEY, validators=[MinValueValidator(Decimal("0.01"))])
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.BANK)
    note = models.CharField(max_length=140, blank=True)
    date = models.DateField(default=timezone.localdate)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments_recorded"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(payer=models.F("payee")), name="payment_not_to_self"
            )
        ]

    def __str__(self):
        return f"{self.payer} paid {self.payee} {self.amount}"

"""Create demo users, groups, expenses and payments for local development."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from expenses.models import Expense, Group, Membership, Payment
from expenses.services import save_expense_shares

PASSWORD = "splitease-demo"


class Command(BaseCommand):
    help = f"Load demo data. Every demo user's password is '{PASSWORD}'."

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        people = {}
        for first, last, username in [
            ("Ada", "Obi", "ada"), ("Tomi", "K.", "tomi"),
            ("Maya", "B.", "maya"), ("Jonas", "R.", "jonas"),
        ]:
            user, created = User.objects.get_or_create(
                email=f"{username}@example.com",
                defaults={"username": username, "first_name": first, "last_name": last},
            )
            if created:
                user.set_password(PASSWORD)
                user.save()
            people[username] = user

        if Group.objects.filter(name="Flat 4B", created_by=people["ada"]).exists():
            self.stdout.write("Demo data already loaded.")
            return

        today = timezone.localdate()
        flat = Group.objects.create(name="Flat 4B", description="Rent, bills, groceries", created_by=people["ada"])
        trip = Group.objects.create(name="Lisbon trip", created_by=people["jonas"])
        for user in people.values():
            Membership.objects.create(group=flat, user=user)
        for name in ("ada", "jonas", "maya"):
            Membership.objects.create(group=trip, user=people[name])

        def add(group, description, amount, payer, days_ago, method="equal", weights=None, members=None):
            expense = Expense.objects.create(
                group=group, description=description, amount=Decimal(amount),
                paid_by=people[payer], created_by=people[payer], split_method=method,
                date=today - timedelta(days=days_ago),
            )
            members = members or list(group.members.all())
            save_expense_shares(expense, weights or {m: Decimal(1) for m in members})

        add(flat, "Groceries — weekly shop", "96.00", "ada", 1)
        add(flat, "Electricity bill", "120.00", "ada", 7)
        add(flat, "Internet", "48.00", "tomi", 12)
        add(flat, "Water bill", "28.00", "ada", 18, method="percent", weights={
            people["ada"]: Decimal(50), people["tomi"]: Decimal(25), people["maya"]: Decimal(25),
        })
        add(trip, "Dinner at Taberna", "246.00", "jonas", 3)
        add(trip, "Airport taxi", "54.00", "ada", 5, method="shares", weights={
            people["ada"]: Decimal(1), people["jonas"]: Decimal(1), people["maya"]: Decimal(2),
        })
        Payment.objects.create(
            group=flat, payer=people["maya"], payee=people["ada"], amount=Decimal("20.00"),
            method=Payment.Method.CASH, created_by=people["maya"], date=today - timedelta(days=2),
        )
        self.stdout.write(self.style.SUCCESS(
            f"Loaded demo data. Sign in as ada@example.com with password '{PASSWORD}'."
        ))

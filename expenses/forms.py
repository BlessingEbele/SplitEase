from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Expense, Group, Payment
from .services import SplitError, compute_shares

User = get_user_model()


def display_name(user):
    full = user.get_full_name().strip()
    return full or user.username or user.email


class MemberChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return display_name(obj)


class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ["name", "description"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Flat 4B"}),
            "description": forms.TextInput(attrs={"placeholder": "Optional"}),
        }


class AddMemberForm(forms.Form):
    email = forms.EmailField(label="Email address")

    def __init__(self, *args, group, **kwargs):
        self.group = group
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data["email"]
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            raise forms.ValidationError(
                "No SplitEase account uses that email yet. Ask them to sign up first."
            )
        if self.group.members.filter(pk=user.pk).exists():
            raise forms.ValidationError(f"{display_name(user)} is already in this group.")
        self.user = user
        return email


class ExpenseForm(forms.ModelForm):
    """Expense details plus one include/value pair per group member."""

    class Meta:
        model = Expense
        fields = ["description", "amount", "date", "paid_by", "split_method"]
        widgets = {
            "description": forms.TextInput(attrs={"placeholder": "e.g. Groceries"}),
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01", "inputmode": "decimal", "class": "big"}),
            "date": forms.DateInput(attrs={"type": "date"}),
            "split_method": forms.RadioSelect,
        }

    def __init__(self, *args, group, user, **kwargs):
        self.group = group
        super().__init__(*args, **kwargs)
        self.members = list(group.members.order_by("first_name", "username"))
        self.fields["paid_by"] = MemberChoiceField(
            queryset=group.members.all(), label="Paid by", empty_label=None
        )
        if not self.instance.pk:
            self.fields["paid_by"].initial = user.pk
            self.fields["date"].initial = timezone.localdate()

        existing = {}
        if self.instance.pk:
            existing = {s.user_id: s.weight for s in self.instance.shares.all()}
        self.member_rows = []
        for member in self.members:
            inc_name, val_name = f"include_{member.pk}", f"value_{member.pk}"
            self.fields[inc_name] = forms.BooleanField(
                required=False,
                initial=(member.pk in existing) if existing else True,
                label=display_name(member),
            )
            self.fields[val_name] = forms.DecimalField(
                required=False,
                min_value=Decimal("0"),
                decimal_places=2,
                initial=existing.get(member.pk, Decimal("1")),
                widget=forms.NumberInput(attrs={"step": "0.01", "min": "0", "class": "split-value"}),
            )
            self.member_rows.append(
                {"user": member, "include": self[inc_name], "value": self[val_name]}
            )

    def clean(self):
        cleaned = super().clean()
        amount, method = cleaned.get("amount"), cleaned.get("split_method")
        if amount is None or not method:
            return cleaned
        weights = {}
        for member in self.members:
            if cleaned.get(f"include_{member.pk}"):
                value = cleaned.get(f"value_{member.pk}")
                if value is None:
                    value = Decimal("0") if method != Expense.SplitMethod.EQUAL else Decimal("1")
                weights[member] = value
        try:
            compute_shares(amount, method, weights)
        except SplitError as exc:
            raise forms.ValidationError(str(exc))
        self.weights = weights
        return cleaned


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["payee", "amount", "method", "date", "note"]
        widgets = {
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01", "inputmode": "decimal", "class": "big"}),
            "method": forms.RadioSelect,
            "date": forms.DateInput(attrs={"type": "date"}),
            "note": forms.TextInput(attrs={"placeholder": "Optional"}),
        }
        labels = {"payee": "Who are you paying?", "method": "Paid with"}

    def __init__(self, *args, group, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["payee"] = MemberChoiceField(
            queryset=group.members.exclude(pk=user.pk), label="Who are you paying?"
        )
        self.fields["date"].initial = timezone.localdate()

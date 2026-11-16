from django.contrib import admin

from .models import Expense, ExpenseShare, Group, Membership, Payment


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ["user"]


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ["name", "created_by", "created_at"]
    search_fields = ["name"]
    inlines = [MembershipInline]


class ExpenseShareInline(admin.TabularInline):
    model = ExpenseShare
    extra = 0


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ["description", "group", "amount", "paid_by", "split_method", "date"]
    list_filter = ["split_method", "group"]
    search_fields = ["description"]
    date_hierarchy = "date"
    inlines = [ExpenseShareInline]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["payer", "payee", "amount", "method", "group", "date"]
    list_filter = ["method", "group"]

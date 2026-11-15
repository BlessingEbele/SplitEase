from django.urls import path

from . import views

app_name = "expenses"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("groups/", views.group_list, name="group_list"),
    path("groups/new/", views.group_create, name="group_create"),
    path("groups/<int:pk>/", views.group_detail, name="group_detail"),
    path("groups/<int:pk>/members/", views.group_add_member, name="group_add_member"),
    path("groups/<int:pk>/expenses/new/", views.expense_create, name="expense_create"),
    path("groups/<int:pk>/expenses/<int:expense_pk>/edit/", views.expense_edit, name="expense_edit"),
    path("groups/<int:pk>/expenses/<int:expense_pk>/delete/", views.expense_delete, name="expense_delete"),
    path("groups/<int:pk>/payments/new/", views.payment_create, name="payment_create"),
    path("groups/<int:pk>/payments/<int:payment_pk>/delete/", views.payment_delete, name="payment_delete"),
    path("expenses/new/", views.expense_choose_group, name="expense_choose_group"),
    path("settle/", views.settle_up, name="settle_up"),
]

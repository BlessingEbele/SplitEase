from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect, render

from .forms import EmailAuthenticationForm, SignUpForm


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True
    extra_context = {"mode": "login"}


def signup(request):
    if request.user.is_authenticated:
        return redirect("expenses:dashboard")
    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return redirect("expenses:dashboard")
    return render(request, "accounts/signup.html", {"form": form, "mode": "signup"})

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class AuthTests(TestCase):
    def test_signup_logs_in_and_redirects(self):
        response = self.client.post(reverse("accounts:signup"), {
            "first_name": "Ann",
            "email": "Ann@Example.com",
            "username": "ann",
            "password1": "a-strong-pass-123",
            "password2": "a-strong-pass-123",
        })
        self.assertRedirects(response, reverse("expenses:dashboard"))
        user = User.objects.get()
        self.assertEqual(user.email, "ann@example.com")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_signup_rejects_duplicate_email(self):
        User.objects.create_user(username="x", email="ann@example.com", password="pw")
        response = self.client.post(reverse("accounts:signup"), {
            "first_name": "Ann", "email": "ANN@example.com", "username": "ann2",
            "password1": "a-strong-pass-123", "password2": "a-strong-pass-123",
        })
        self.assertContains(response, "already exists")

    def test_login_with_email(self):
        User.objects.create_user(username="ann", email="ann@example.com", password="a-strong-pass-123")
        response = self.client.post(reverse("accounts:login"), {
            "username": "ann@example.com", "password": "a-strong-pass-123",
        })
        self.assertRedirects(response, reverse("expenses:dashboard"))

    def test_login_page_renders(self):
        self.assertContains(self.client.get(reverse("accounts:login")), "Welcome back")
        self.assertContains(self.client.get(reverse("accounts:signup")), "Create your account")

    def test_logout(self):
        user = User.objects.create_user(username="ann", email="ann@example.com", password="pw")
        self.client.force_login(user)
        response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(response, reverse("accounts:login"))

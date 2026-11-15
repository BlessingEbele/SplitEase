# SplitEase

Split shared expenses with flatmates, friends and colleagues. SplitEase keeps a
running balance for every group and suggests the fewest payments to settle up.

## Features

- Email-based sign up and sign in (custom `accounts.User`)
- Groups with members added by email
- Expenses split **equally**, by **exact amounts**, by **percentage** or by **shares**,
  with a live per-person preview while you type
- Cent-exact rounding: shares always add up to the expense total
- Per-group balances and **simplified debts** (at most _n − 1_ payments)
- Dashboard with net balance, who owes whom across groups and recent activity
- Settle-up page and payment recording (bank transfer, cash, other)
- Django admin for every model

## Getting started

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo         # optional demo data
python manage.py runserver
```

Open http://127.0.0.1:8000. With demo data, sign in as `ada@example.com` /
`splitease-demo`.

Run the tests with `python manage.py test`.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | insecure dev key | Set in production |
| `DJANGO_DEBUG` | `1` | `0` to disable debug |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated hosts |
| `SPLITEASE_CURRENCY` | `$` | Currency symbol shown in the UI |

## Project layout

- `accounts/` – custom user model, sign up / login views
- `expenses/` – groups, expenses, shares and payments
  - `services.py` – splitting, balances and debt simplification
  - `management/commands/seed_demo.py` – demo data
- `templates/`, `static/css/splitease.css` – UI

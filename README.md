# TableOrder — Phase 1 (Core Loop MVP)

QR table ordering for a hotel/restaurant. Phase 1 is the working core loop:
admin login → tables + printable QR → menu → customer scans & orders → admin
assigns a free waiter → waiter serves and marks "I'm available". Queue is FIFO,
one waiter per table, one table per waiter.

## Setup (once)

```
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` and set at least:
- `SECRET_KEY` (a long random string)
- `ADMIN_EMAIL` and `ADMIN_PASSWORD` (your first admin, created on first run)

Local dev uses a SQLite file `tableorder.db`. Online, set `DATABASE_URL` to a
PostgreSQL connection string and `COOKIE_SECURE=1`.

## Run

```
uvicorn app.main:app --reload
```

- Admin board: http://127.0.0.1:8000/static/admin.html
- Waiter page: http://127.0.0.1:8000/static/waiter.html
- Customer page (from a QR): http://127.0.0.1:8000/customer.html?token=<token>
- API docs: http://127.0.0.1:8000/docs

In dev, email OTP codes print in the terminal running uvicorn (no email needed).

## Test

```
python -m pytest -q
```

## Manual acceptance walkthrough (Phase 1)

1. Log in to the admin board. Add a table; open its "print all" page and scan a
   QR with your phone (or open the `/customer.html?token=...` link).
2. Add a menu item (e.g. "Ugali + Beef", 350).
3. On the customer page: sign in with email OTP, add the item, place the order.
4. The admin board shows the table in the queue (oldest first) with a beep.
5. Create a waiter (admin → waiters), then assign the table to that waiter.
6. Log in to the waiter page: you see the table and the guest's items. Mark an
   item served, then "Finish table / I'm available".
7. Checks that must hold:
   - Two tables A (earlier) then B: A is listed above B; assigning B first asks
     for a reason and writes to the audit log.
   - A busy waiter cannot be given a second table until "I'm available".
   - A second order from the same table goes to the same waiter.
   - Deleting a table (or regenerating its QR) makes the old link stop working.

## Project layout

```
app/            main.py, db.py, schema.py, auth.py, queue.py, emailer.py, qr.py
app/routers/    admin, tables, menu, customer, orders, waiter
static/         admin.html, waiter.html, customer.html, uploads/
tests/          smoke, schema, admin_auth, tables, menu, customer_auth,
                orders, queue, waiter, admin_board
```

## Notes / Phase 2 (not in Phase 1)

Stock ("plates left"), the "table must be open" rule, the hotel Wi-Fi/IP check,
rate limits beyond OTP, and the audit log beyond reassignment are Phase 2. The
game, points and rewards are Phase 3.
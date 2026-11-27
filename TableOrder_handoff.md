# HAND-OFF: "TableOrder" — QR table ordering system for a hotel/restaurant (Kenya)

> Paste this whole file to the AI that will build it. Read all of it before writing any code.

---

## 0. INSTRUCTIONS TO THE AI (how to work with me)

**Who I am:** a beginner developer in Kenya. No capital, no bank/credit card (I use M-Pesa). Windows laptop, VS Code, I have used Python/FastAPI, HTML/JS and Git/GitHub before (a previous project, "GoalHub", runs on FastAPI + PostgreSQL on Render + Neon with Google sign-in). I send photos of my screen, so ask for clear, upright photos.

**How to work with me:**
1. Build in the **phases in section 12**, one phase at a time. Do not start the next phase until I say the current one works.
2. Give **small numbered steps, ONE ask at a time**. Give me **whole files** to paste over (File > Open File in VS Code, Ctrl+A, Ctrl+C, paste), not fragments.
3. Tell me exactly which files to create or replace, and the commands to run to test. Tell me the **last line of a red error** is what you need.
4. Write simple, readable code with comments. Prefer few dependencies. Add automated tests for the rules in section 7 (queue, stock, waiter assignment, game limits). Run/think through them before giving me code.
5. **Never ask me to paste secrets** (database URL, admin keys, email passwords, API keys) into chat. They go only into a local `.env` file or the hosting dashboard's environment variables. Never repeat a secret you see in a photo.
6. Where something is a business/legal decision (data protection, game prizes), tell me plainly and let me decide. Do not pretend a feature is solved if it is only partly solvable (see section 5, the Wi-Fi rule, and section 8, the game).
7. Server is the source of truth: **prices, stock, queue order, game outcomes and permissions are always decided on the server**, never trusted from the phone.

---

## 1. THE IDEA IN ONE PARAGRAPH

Today waiters walk from table to table asking what people want. Instead, every table has a printed QR code. A customer scans it and lands on the hotel's page: the **menu**, what is **being prepared right now**, how many **plates are left** of each dish, and an **Order** button. Several people at one table can each order from their own phone. Every order goes into a **fair first-come queue**; the admin (or an auto-assign setting) gives the table to a **free waiter**. One waiter serves one table at a time and presses "I'm available" when finished. While customers wait they can play a **hard skill game** (admin switches it on/off, sets how many winners per day, how many tries per table, and the prize: points or a free item). Customers have verified accounts with **loyalty points**. Waiters can also take orders for guests on their phone. The admin manages tables (add/delete, printable stylish QR codes), the menu, stock, waiters, the game and reports.

---

## 2. ROLES

| Role | Logs in with | Can do |
|---|---|---|
| **Customer** | Google sign-in or email + one-time code | Scan table QR, view menu/stock, order, track order, play game, see points |
| **Waiter / Waitress** | Username/email + password (+ optional 4-6 digit PIN on shared phone), created by admin | See assigned table, take orders per guest, mark served, mark "available" |
| **Admin / Manager** | Email + password (+ optional 2FA later) | Everything: tables, QR, menu, stock, waiters, assignment, game, prizes, reports |
| **Kitchen** *(optional, Phase 3)* | Staff login | Sees the order tickets, marks "preparing / ready", updates plates left |

Keep roles in one `users` table with a `role` column. Customers and staff must not be able to reach each other's pages or APIs (check the role on **every** server route).

---

## 3. TABLES AND QR CODES (admin feature)

- Admin can **add** a table (name/number, optional seats, optional area like "Garden"). Creating a table generates an **unguessable token** (at least 128 random bits, e.g. `secrets.token_urlsafe(16)`). The QR contains `https://<site>/t/<token>`, **not** the table number (so people cannot guess other tables).
- Admin can **delete/disable** a table (soft-delete: keep history, token stops working) and **regenerate** a table's QR (if a code was copied/abused; old token dies).
- **Printable output:** a page/PDF with a table "tent card": big styled QR, "Table 7", "Scan to order", the hotel name/logo and the Wi-Fi name. Option "print all tables" (A4 grid) and "print one".
- **Not boring QR codes:** use a styled-QR library (e.g. the JS library `qr-code-styling`, which supports rounded/dot modules, gradients, corner styles and a centre logo), in the hotel's colours. Rules so it still scans: use error-correction level **H** when a logo is in the centre, keep dark modules on a light background with strong contrast, keep a quiet border, and **test-scan every style with 2-3 phones** before printing. A tiny table number printed under it helps staff.
- Table has a live status: `free` / `occupied` / `waiting_for_waiter` / `being_served` / `needs_bill` (see section 6).

---

## 4. CUSTOMER EXPERIENCE (phone, installable web page, English + Swahili)

1. Scan QR -> `/t/<token>`. If the table is valid, show the hotel's page for that table. If not logged in -> sign-in (section 9).
2. **Menu page:** categories, photo, price in **KES**, description, dietary tags, and a status badge per item:
   - `Available` (+ **"12 plates left"** when low, e.g. under 10 — admin decides the threshold)
   - `Being prepared now` (kitchen/admin flag)
   - `Sold out` (0 left, cannot add to cart)
3. Cart -> **Place order**. Customer can add a note ("no onions"). They see **order status**: `In queue (position 3)` -> `Waiter assigned: Mary` -> `Being served` -> `Done`, with an estimated wait.
4. **Shared table:** several phones can order at the same table at the same time. All orders attach to the same **table session** (section 6) and the same waiter. Show the customer their own items and (optionally) a running table total.
5. **Points** page: balance, history, how to earn/redeem.
6. **Game** button while an order is waiting (only if admin has opened the game).
7. Works on slow mobile data, big touch targets, loads fast, installable (PWA).

---

## 5. THE "MUST BE ON THE HOTEL WI-FI" RULE (be honest about limits)

**A website cannot read which Wi-Fi name a phone is on.** So we cannot literally check "logged into the hotel Wi-Fi". Use **layers**; none is perfect, together they stop casual abuse:

1. **Public-IP check (main layer).** Everyone on the hotel Wi-Fi reaches the internet through the hotel router's one public IP. The server records that IP (admin presses "Set hotel network" while connected to the hotel Wi-Fi) and **only accepts orders from that IP** (behind a host like Render, read the real client IP from the proxy's `X-Forwarded-For` header, the **last** entry added by the trusted proxy). Customers on mobile data have a different IP and are blocked from ordering (they may still browse the menu). Caveats: the ISP may change the IP (give the admin a one-tap "update" button and an optional list of allowed IPs/ranges); some ISPs share addresses (CGNAT) which can weaken this; IPv6 needs handling (compare the /64 prefix).
2. **Run the server inside the hotel (best, if the hotel agrees).** A small always-on PC or Raspberry Pi on the hotel LAN serves the site at a local address. Then the site is only reachable on the hotel Wi-Fi at all, and it keeps working when the internet is down. Trade-off: you must maintain that machine and back it up.
3. **Table must be "open".** An order is only accepted if the table is marked `occupied` (a waiter/host or admin opens it when guests sit, or the first scan creates an "awaiting host" request). This blocks "photographed the code and ordering from home" very strongly. Make this configurable.
4. **Verified accounts + rate limits** (e.g. max orders per account per hour, one open order batch per table) so a prankster cannot flood the admin.
5. **Optional browser location check** (geofence radius around the hotel). It can be faked and some people will refuse the permission, so treat it only as a hint, never as the only protection.

Explain to the hotel owner what is and isn't guaranteed.

---

## 6. QUEUE, WAITER ASSIGNMENT AND TABLE SESSIONS (the core logic)

**Table session:** when a table is opened (or its first valid order arrives) a `table_session` starts. It closes when the waiter marks the table finished (after serving/bill). All orders from any phone at that table belong to the current session.

**Fair queue:** orders/table-sessions that are waiting for a waiter are sorted **strictly by the time the first order was placed (FIFO)**. The admin screen shows the oldest first, with waiting time. If the admin assigns out of order, require a short reason and write it to an **audit log** (so staff cannot quietly favour friends). Customers see their queue position.

**Assignment:**
- Admin gets a **notification** (sound + highlighted card + browser notification if allowed) when a new table is waiting. Card shows table, items, time waiting, and a dropdown of **free waiters**.
- **One waiter per table. One table at a time per waiter.** A waiter is `free` until assigned, then `busy` until they press **"Finished / I'm available"**. Only then can they receive another table.
- Later orders from the **same table** automatically go to the **same waiter** (no re-assignment) and appear as new items on their screen.
- Optional setting **"Auto-assign"**: the next table in the queue goes to the free waiter who has been idle longest (reduces admin work and removes favouritism). Admin can still override with a reason.
- Waiter statuses: `free`, `busy`, `on_break`, `off_duty`. Only `free` waiters can be assigned. If a busy waiter's phone is off/idle too long, alert the admin so they can reassign.
- Admin can **reassign** a table to another waiter (logged).

**Waiter phone dashboard:**
- Shows their assigned table and the orders **grouped per guest** (Guest 1, Guest 2... or seat numbers/names) because families/groups order together.
- Waiter can **add orders on behalf of a guest** (guests without phones, or elderly customers): pick guest -> add items -> submit. This respects stock and prices exactly like a customer order.
- Buttons: `Mark item served`, `Table needs bill`, `Finish table / I'm available`.

**Order and item statuses:** `placed` -> `accepted` -> `preparing` -> `ready` -> `served` (or `cancelled`). Allow cancellation by the customer only before `preparing`; after that only waiter/admin, and stock is returned when cancelled.

---

## 7. MENU AND STOCK ("plates remaining")

- Per menu item: name, category, price (KES, integer cents or whole shillings), photo, description, `active`, `is_preparing` flag, `portions_left` (nullable = unlimited, e.g. drinks), `low_stock_threshold`, `daily_portions` (what the kitchen prepared today).
- **Admin/kitchen sets today's portions** each morning ("Ugali + beef: 30 plates"). Each accepted order **reserves** portions **atomically** (a database transaction / `UPDATE ... WHERE portions_left >= qty`), so two people cannot take the last plate at the same moment. If the update affects 0 rows -> "Sorry, only N left / sold out".
- Cancelled or declined orders **return** portions. Show "x plates left" only when low or if the admin wants it always.
- Admin can mark an item "being prepared now" (shows a pulsing badge) and can instantly hide/sold-out an item.
- Daily reset option + a log of stock changes (who changed what, when).

---

## 8. THE WAITING GAME + PRIZES

**Settings the admin controls (a "Game" page):**
- **Game on/off** (unlock/close), optional schedule (e.g. 12:00-22:00).
- **Winners per day** (e.g. first 5). When the quota is reached the game says today's prizes are gone (optionally still playable for fun, no prize).
- **Prize type per day:** points (how many) **or** a free item (pick from menu or free text like "free fries/juice") — the admin chooses.
- **Max tries per table per day** (a shared pool for the table) and also an optional **max tries per account per day**.
- **Difficulty** (1-5) tuned so that winning is **hard but possible** (target e.g. 1-5% of plays; make this a number the admin can see: plays vs wins today, and adjust).

**Who can play:** *anyone logged in at the table can play* (several phones, all fine). Fairness and anti-farming come from the **per-table try pool**, the per-account cap and the daily winner cap — not from restricting who plays.

**Anti-cheating (important):** a game that runs only in the browser can be cheated by anyone using developer tools. So:
- Choose a **skill game that can be checked on the server**, for example: a timing game (stop a moving bar inside a very narrow zone 3 times in a row), a memory sequence that grows each round, or a catch/avoid game. The server creates a **game session** with a random seed and rules, the phone records the player's inputs (a "move log" with timestamps), and the **server re-plays the log** to decide win/lose. Never accept "I won" from the client.
- Reject impossible timings/too-perfect inputs, rate-limit starts (e.g. 1 start per 20 s), and tie each session to the account + table.
- Winning with the daily quota left -> create a **reward**: points are added to the points ledger; a free item creates a **one-time reward code** shown on the winner's phone and valid only that day. The waiter/admin presses "Redeem" so it cannot be reused.

**Legal check (business decision for the owner, not for the AI):** prize games/competitions can fall under Kenya's rules on gaming, lotteries and promotional competitions (regulated by the Betting Control and Licensing Board). Keep the game **free to play, skill-based, with no payment needed to enter**, and ask a lawyer or the board before launch. I (the owner) will decide; the AI should just keep the design "free skill game with limited free prizes".

---

## 9. ACCOUNTS, VERIFICATION AND POINTS

- **Customers must have an account.** Offer: **Google sign-in** (email already verified by Google; the easiest and free) and **email + one-time code (OTP)** for people without Google. OTP rules: 6 digits, expires in 10 minutes, max 5 tries, max 3 codes per hour, stored hashed. Phone-number OTP by SMS (e.g. Africa's Talking) costs money per SMS — leave it as an optional later upgrade.
- Sending email: use a transactional email service with a free tier (examples: Brevo, Resend; check their current limits) or SMTP. Keep keys in environment variables only.
- Sessions: random token in an `HttpOnly`, `SameSite=Lax`, `Secure` cookie; store only the **hash** of the token in the database.
- **Points ledger** (never a single editable number): table `points_ledger(id, user_id, delta, reason, order_id/game_id, created_at)`; balance = sum. Earn: e.g. 1 point per KES 100 spent (admin sets the rate) on **paid/served** orders, plus game rewards. Redeem: admin defines rewards ("100 points = free soda"); redemption creates a one-time code the waiter confirms.
- Staff accounts are created **only by the admin** (no public staff sign-up). Passwords hashed with argon2/bcrypt. Lock after repeated failures.

---

## 10. ADMIN DASHBOARD (feature list)

1. **Live board:** new-order notifications (sound), queue sorted oldest-first, assign/reassign waiter, table map with colours (free / occupied / waiting / being served).
2. **Tables:** add, edit, delete/disable, regenerate QR, print one/all, open/close table manually.
3. **Menu & stock:** categories, items, photos, prices, today's portions, "being prepared" flag, sold-out toggle, stock log.
4. **Waiters:** add/disable/reset password, see status (free/busy/break), see today's tables served and average service time.
5. **Game:** on/off, schedule, winners per day, prize type and prize, tries per table/account, difficulty, today's plays/wins, winners list, reward codes redeemed.
6. **Points & rewards:** earn rate, reward catalogue, customer lookup, manual adjustment (logged).
7. **Customers:** list, search, block abusive accounts.
8. **Orders & reports:** today/week sales, best sellers, average wait time (placed -> waiter assigned -> served), waiter performance, stock used, export CSV.
9. **Settings:** hotel name/logo/colours, hotel network (public IP) setting, currency (KES), tax/service charge %, low-stock threshold, auto-assign on/off, require-table-open on/off.
10. **Audit log:** every admin override, reassignment, stock edit, deletion.

---

## 11. THINGS YOU DIDN'T MENTION (added by me — keep or drop)

- **Bill & payment:** per table running bill, split by guest, mark paid (cash / M-Pesa). Later: **M-Pesa Daraja STK push** so the customer pays from the phone. Print or show a receipt.
- **Call waiter / request bill** buttons (without ordering).
- **Order notifications to the customer** (screen update, optional sound/vibration, optional web push).
- **Kitchen display** screen with tickets (Phase 3).
- **Allergy/notes and spice level**, **estimated preparation time** per item.
- **Complaint/feedback** after the meal (1-5 stars) feeding the admin report.
- **Opening hours / "kitchen closed"** switch.
- **Offline/poor-network behaviour:** show a clear message, never double-submit an order (use an idempotency key), retry safely.
- **Time zone** is Africa/Nairobi; store timestamps in UTC.
- **Multi-hotel later:** keep a `hotel_id` on tables, menu items and users from day one so the same system can be sold to other hotels. (Cheap to add now, painful later.)
- **Data protection:** you will store names, emails and order history. Kenya's Data Protection Act applies (registration with the Office of the Data Protection Commissioner may be required for businesses; ask the hotel/lawyer). Provide a privacy policy page, collect the minimum, let customers delete their account.

---

## 12. SUGGESTED TECHNOLOGY (my recommendation; challenge it if you have a better beginner-friendly option)

- **Backend:** Python **FastAPI** + **PostgreSQL** (SQLite is fine on a laptop during development). Same pattern I used before: a database layer that works with SQLite locally and PostgreSQL when `DATABASE_URL` is set.
- **Frontend:** plain HTML/CSS/JavaScript, mobile-first, installable PWA, separate pages/apps for **customer**, **waiter** and **admin**. No heavy framework required.
- **Real-time updates:** start with **polling every 3-5 seconds** (simple, reliable). Upgrade to **Server-Sent Events** later for instant admin notifications. Add a sound + `Notification` API for the admin page.
- **QR:** `qr-code-styling` (browser) for pretty codes + a print stylesheet, or Python `segno` on the server.
- **Images:** resize/compress uploaded menu photos on upload; store on the host's disk or an object store, not as giant database blobs (free database space is small).
- **Hosting while developing:** free tiers are fine (Render web service + Neon PostgreSQL worked for my last project). **Warning:** free web services go to sleep when idle and take ~1 minute to wake, which is **not acceptable in a busy restaurant**. For real use choose: (a) a small always-on VPS (a few dollars a month — check current prices), or (b) a mini-PC/Raspberry Pi inside the hotel (best for the Wi-Fi rule and for internet outages), with automatic daily backups.
- **Security basics (must-have):** parameterised SQL only, role checks on every route, CSRF/origin checks on POST, rate limiting (login, OTP, orders, game starts), request size limits, HTTPS only, secrets in env vars, input validation with Pydantic, no HTML injection (render text with `textContent`), unguessable QR tokens, audit log.

### Main tables (starting point)

`hotels, users(role), tables(token, status, active), table_sessions, categories, menu_items(portions_left...), orders, order_items(guest_label), waiters(status), assignments, stock_log, game_settings, game_sessions(seed, move_log, result), rewards(code, used_at), points_ledger, otp_codes, sessions, audit_log, settings`

---

## 13. BUILD PHASES (do one at a time; each ends with a working demo)

**Phase 1 — The core loop (MVP, must work first)**
Admin login; add/delete tables + printable QR; menu CRUD; customer scan -> sign in (Google or email OTP) -> see menu -> place order; admin sees order with notification, assigns a free waiter; waiter login and phone page; waiter marks served and "I'm available"; queue is FIFO; one waiter per table, one table per waiter. Tests for the queue/assignment rules.

**Phase 2 — Stock, groups, rules**
Plates left + atomic reservation, "being prepared" flag, multiple phones per table, waiter-takes-orders-per-guest, "table open" rule, hotel public-IP check, audit log, rate limits.

**Phase 3 — Game, points, rewards**
Server-verified skill game, admin game settings (on/off, winners/day, tries/table, prize, difficulty), points ledger, reward codes and redemption, customer points page.

**Phase 4 — Money and polish**
Bills + split + M-Pesa (Daraja) payment, reports/CSV, kitchen display, feedback stars, Swahili translation, styled QR themes, backups, production hosting, hotel staff training notes.

---

## 14. ACCEPTANCE CHECKS (examples the AI must make pass)

- Two phones order the last plate at the same instant -> exactly one succeeds.
- Two tables ordered in order A then B -> the admin screen lists A above B; assigning B first requires a reason and is logged.
- A waiter with an open table can't be assigned a second table; after "I'm available" they can.
- A second order from the same table goes to the same waiter automatically.
- An order from a phone on mobile data (not the hotel IP) is refused with a friendly message; browsing the menu still works.
- A table that is not open refuses orders (when the setting is on).
- Deleting a table kills its QR link; regenerating makes the old printed code stop working.
- Game: forged "I won" requests are rejected; the 6th win of a "5 winners" day gets no prize; a table cannot exceed its try limit even with many phones/accounts.
- A reward code works once only and expires the same day.
- Customers can't open staff/admin pages or APIs; waiters can't open admin pages.

---

## 15. OPEN QUESTIONS FOR ME (the owner) — ask me one at a time when relevant

1. Is the hotel willing to host a small computer on its network, or must it be fully online?
2. Cash only at first, or M-Pesa from the start?
3. Name and colours/logo of the hotel (for the QR cards and the app)?
4. How many tables, waiters and menu items to expect on day one?
5. Language(s) for customers: English only first, Swahili too?
6. What should the game be (timing / memory / catch)? The AI can propose 2-3 and let me pick.

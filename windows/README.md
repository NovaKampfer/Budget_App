# EasyBudget Desktop (Windows, offline)

The original desktop version of EasyBudget, built with **Python**, **Kivy** and **KivyMD**.
It tracks transactions, shows daily ending balances on a monthly calendar, and supports
**recurring income/expenses** — all stored locally, no cloud and no ads.

> Looking for the phone app? See [`../android`](../android).

---

## ✨ Features

- 📅 **Calendar view**: daily ending balances in a monthly grid (Mon–Sun).
- ➕ **Add transactions**: positive for income, negative for expenses.
- ⟳ **Recurring transactions**: every _N_ days, weeks or months, generated 12 months ahead.
- 🖊 **Edit/Delete**: one-off transactions, a single recurring occurrence, or a whole series.
- ✅ **Offline-first**: data lives in a local SQLite database at
  `C:\Users\<you>\.easybudget_desktop\easybudget.db`.

---

## 📂 Project structure

```
windows/
├── db/
│   └── database.py     # SQLite data layer
├── main.py             # App entry point (UI + logic)
├── requirements.txt    # Python dependencies
└── run.bat             # One-click launcher for Windows
```

---

## 🚀 Getting started

1. Install **Python 3.10+** from [python.org](https://www.python.org/downloads/).
2. Clone the repo:
   ```bash
   git clone https://github.com/NovaKampfer/Budget_App.git
   cd Budget_App/windows
   ```
3. Double-click **`run.bat`**. The first run creates a virtual environment and installs
   the dependencies; later runs start the app straight away.

Or manually:

```bash
cd windows
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

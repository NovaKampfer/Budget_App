# EasyBudget Desktop (Offline)

EasyBudget is a simple **offline personal budget tracker** built with **Python**, **Kivy**, and **KivyMD**.  
It helps you track transactions, visualize balances on a monthly calendar, and set up **recurring income/expenses** without relying on the cloud.

---

## ✨ Features

- 📅 **Calendar view**: See daily ending balances in a monthly grid, aligned Mon–Sun.
- ➕ **Add transactions**: Positive for income, negative for expenses.
- ⟳ **Recurring transactions**:
  - Supports every _N_ days, weeks, or months.
  - Generated automatically up to 12 months ahead.
  - Marked with a **⟲** symbol in the transaction list.
- 🖊 **Edit/Delete**:
  - Update or delete one-off transactions.
  - Delete only a single recurring occurrence, or the entire series.
- ✅ **Offline-first**:
  - Stores data in a local SQLite database at  
    `C:\Users\<you>\.easybudget_desktop\easybudget.db`.
- 🎨 **Material Design** look and feel.

---

## 📂 Project Structure

Budget_app/
├── db/
│ └── database.py # SQLite database layer
├── main.py # Application entry point (UI + logic)
├── requirements.txt # Python dependencies
├── run.bat # One-click launcher for Windows
└── README.md # This file






---

## 🚀 Getting Started

### 1. Install Python
Make sure you have **Python 3.10+** installed.  
Download from [python.org](https://www.python.org/downloads/).

### 2. Clone or download this repo
```bash
git clone https://github.com/NovaKampfer/Budget_App.git
cd Budget_App

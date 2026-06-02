# Payroll to QBO Journal Entry Transformer

A secure, local-only Windows desktop application to convert raw payroll "Complete Summary" exports into QuickBooks Online compatible Journal Entry CSVs.

## Features
- **Local Processing:** No data ever leaves your machine.
- **PII Stripping:** Automatically removes SSN, Names, and Employee IDs upon loading.
- **Validation:** Ensures the Journal Entry balances (Debits = Credits) before saving.
- **Mapping:** Automatically maps Divisions to QBO Classes and Wages to specific GL Codes.

## Prerequisites
- Python 3.10 or higher
- Windows 10/11

## Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-repo/payroll-to-qbo.git
   cd payroll-to-qbo

## Project Structure
payroll_to_qbo/
├── app.py                # Main GUI Application & Logic
├── test_app.py           # Automated Unit Tests
├── requirements.txt      # Project Dependencies
└── README.md             # Documentation for GitHub

# Create a virtual environment:
python -m venv venv
source venv/Scripts/activate

# Install dependencies:
pip install -r requirements.txt

# Running Tests
pytest test_app.py

# Compiling to Executable (.exe)
pyinstaller --noconsole --onefile --name "PayrollToQBO" app.py


---

### Key Implementation Details for the Developer:
1.  **Security:** The `clean_data` method is called immediately after `pd.read_csv`. This ensures that PII is not stored in the primary working dataframe used for calculations.
2.  **Accounting Integrity:** The `transform` method uses `round(val, 2)` before comparison. This is critical in financial programming to avoid floating-point errors where `$100.00` might be evaluated as `$100.0000000001`.
3.  **GUI:** Used `tkinter.ttk` for a slightly more modern "themed" look on Windows compared to standard tkinter.
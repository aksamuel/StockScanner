# Python environment setup

Windows PowerShell commands to create and activate a virtual environment, install dependencies from `requirements.txt`, and verify installation.

1. Create a venv and activate (PowerShell):

```powershell
python -m venv .venv
./.venv/Scripts/Activate.ps1
```

2. Install dependencies:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

3. Quick verification:

```powershell
python -c "import pandas; import yfinance; import ta; import openpyxl; print('OK')"
```

If the last command prints `OK`, the environment is set up.

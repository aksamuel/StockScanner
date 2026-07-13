import os
from datetime import datetime
import pandas as pd


def export_report(results):

    df = pd.DataFrame(results)

    df = df.sort_values(
        by="Score",
        ascending=False
    )

    os.makedirs("reports", exist_ok=True)

    filename = datetime.now().strftime(
        "reports/StockScanner_%Y-%m-%d.xlsx"
    )

    with pd.ExcelWriter(
        filename,
        engine="openpyxl"
    ) as writer:

        df.to_excel(
            writer,
            sheet_name="Recommendations",
            index=False
        )

    print()
    print("=" * 80)
    print("Report saved successfully")
    print(filename)
    print("=" * 80)

    return filename
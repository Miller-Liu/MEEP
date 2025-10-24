import sqlite3
import csv
import os

class EmailViewer:
    def __init__(self, db_path):
        self.db_path = db_path
            
    def convert_to_csv(self, csv_path):
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM emails")
            rows = c.fetchall()
            col_names = [description[0] for description in c.description]

            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(col_names)   # header row
                writer.writerows(rows)
            print(f"[✓] Exported {len(rows)} rows to {csv_path}")

if __name__ == "__main__":   
    filename = "inbox"
    gmail_path = os.path.join(os.getcwd(), "memory", filename + ".db")
    obj = EmailViewer(gmail_path)
    
    csv_path = os.path.join(os.getcwd(), "memory", filename + ".csv")
    obj.convert_to_csv(csv_path)
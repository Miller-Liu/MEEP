import csv
import os
import sqlite3

class EmailViewer:
    def __init__(self, file_name : str):
        self.db_path = os.path.join(os.getcwd(), "memory", file_name + ".db")
            
    def convert_to_csv(self):
        csv_path = self.db_path[:-2] + "csv"
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
            
            c.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            c.execute("PRAGMA journal_mode=DELETE;")
            conn.commit()

        # Remove WAL and SHM files
        for db_name in ["inbox", "outbox"]:
            db_path = os.path.join(os.getcwd(), "memory", f"{db_name}.db")
            for ext in ["-wal", "-shm"]:
                try:
                    os.remove(db_path + ext)
                except FileNotFoundError:
                    pass


if __name__ == "__main__":   
    file_name = "inbox"
    obj = EmailViewer(file_name)
    obj.convert_to_csv()
import csv
import os
import sqlite3

class EmailViewer:
    def __init__(self):
        self.dir_path = os.path.join(os.getcwd(), "memory")
            
    def convert_to_csv(self, file_name : str):
        db_path = os.path.join(self.dir_path, file_name + ".db")
        csv_path = os.path.join(self.dir_path, file_name + ".csv")
        with sqlite3.connect(db_path) as conn:
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
        for ext in ["-wal", "-shm"]:
            try:
                os.remove(db_path + ext)
            except FileNotFoundError:
                pass
    
    def update_to_db(self, file_name : str):
        db_path = os.path.join(self.dir_path, file_name + ".db")
        csv_path = os.path.join(self.dir_path, file_name + ".csv")
        with sqlite3.connect(db_path) as conn:
            c = conn.cursor()

            # Read CSV
            with open(csv_path, newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                col_names = next(reader)
                rows = list(reader)

            if "msg_id" not in col_names:
                raise ValueError(f"CSV must include a unique identifier column 'msg_id'")

            # Build SQL update statement dynamically
            set_clause = ", ".join([f"{col} = ?" for col in col_names if col != "msg_id"])
            update_sql = f"UPDATE emails SET {set_clause} WHERE {'msg_id'} = ?"

            # Find index of msg_id
            id_idx = col_names.index("msg_id")

            # Perform updates
            updated = 0
            for row in rows:
                values = [v for i, v in enumerate(row) if i != id_idx]
                values.append(row[id_idx])  # last param is id for WHERE clause
                c.execute(update_sql, values)
                if c.rowcount:
                    updated += 1

            conn.commit()

            # Cleanup WAL files
            c.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            c.execute("PRAGMA journal_mode=DELETE;")
            conn.commit()

        # Remove WAL and SHM files
        for ext in ["-wal", "-shm"]:
            try:
                os.remove(db_path + ext)
            except FileNotFoundError:
                pass

        print(f"[✓] Updated {updated} existing rows to db from csv file")


if __name__ == "__main__":   
    obj = EmailViewer()

    for file_name in ["inbox", "outbox"]:
        # obj.update_to_db(file_name)
        obj.convert_to_csv(file_name)
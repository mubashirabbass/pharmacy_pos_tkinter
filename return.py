import sqlite3

con = sqlite3.connect("pharmacy.db")   # adjust path if needed
cur = con.cursor()
cur.execute("PRAGMA table_info(returns);")
print(cur.fetchall())
con.close()

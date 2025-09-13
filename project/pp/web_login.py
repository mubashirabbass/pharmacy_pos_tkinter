from flask import Flask, render_template, request
import sqlite3, hashlib, os, subprocess, sys

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "pharmacy.db")

# Hashing function (same as your Tkinter app)
def hash_pw(pw: str) -> str:
    import hashlib
    return hashlib.sha256(pw.encode()).hexdigest()

def check_login(username, password, role):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE username=?;", (username,))
    row = cur.fetchone()
    con.close()
    if not row:
        return False
    return row["password_hash"] == hash_pw(password) and row["role"] == role

app = Flask(__name__, template_folder=".")

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        role = request.form.get("role")

        if check_login(username, password, role):
            # Launch Tkinter dashboard
            subprocess.Popen([sys.executable, "mainproject.py"])
            return """
            <h2 style="font-family:sans-serif;color:green;">✅ Login successful</h2>
            <p>The Tkinter dashboard is opening. You can now close this tab.</p>
            """
        else:
            return """
            <h2 style="font-family:sans-serif;color:red;">❌ Invalid credentials</h2>
            <a href="/">Try again</a>
            """
    return render_template("login.html")

if __name__ == "__main__":
    app.run(debug=True, port=5000)



import os
import sqlite3
import hashlib
import csv
import threading
import time
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# Optional libraries
try:
    import ttkbootstrap as tb
    from ttkbootstrap.icons import Icon  # may raise if icons missing
    TTB_AVAILABLE = True
except Exception:
    tb = None
    Icon = None
    TTB_AVAILABLE = False

try:
    from tkcalendar import DateEntry
    TKCAL_AVAILABLE = True
except Exception:
    DateEntry = None
    TKCAL_AVAILABLE = False

try:
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    MATPLOTLIB_AVAILABLE = True
except Exception:
    MATPLOTLIB_AVAILABLE = False

try:
    import openpyxl
    OPENPYXL_AVAILABLE = True
except Exception:
    OPENPYXL_AVAILABLE = False

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as pdf_canvas
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

# Constants
DB_PATH = os.path.join(os.path.dirname(__file__), 'pharmacy.db')
BACKUP_FOLDER = os.path.join(os.path.dirname(__file__), 'backups')
os.makedirs(BACKUP_FOLDER, exist_ok=True)


# -----------------------------
# Utility / DB
# -----------------------------
def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


def now_str(): return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


class DB:
    def __init__(self, path=DB_PATH):
        self.path = path
        self._ensure()

    def connect(self):
        con = sqlite3.connect(self.path, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys = ON;')
        return con

    def _ensure(self):
        con = self.connect()
        cur = con.cursor()
        # users
        cur.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password_hash TEXT,
            role TEXT CHECK(role IN ('admin','staff','cashier')) NOT NULL
        );''')
        # seed admin & cashier only if no users exist
        cur.execute('SELECT COUNT(*) as c FROM users;')
        if cur.fetchone()['c'] == 0:
            cur.executemany('INSERT INTO users(username,password_hash,role) VALUES(?,?,?);', [
                ('admin', hash_pw('admin123'), 'admin'),
                ('cashier', hash_pw('cashier123'), 'cashier'),
            ])
        # customers
        cur.execute('''CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            phone TEXT UNIQUE,
            notes TEXT
        );''')
        # categories/manufacturers/suppliers/formulas
        cur.execute('''CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, notes TEXT);''')
        cur.execute('''CREATE TABLE IF NOT EXISTS manufacturers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, contact TEXT, notes TEXT);''')
        cur.execute('''CREATE TABLE IF NOT EXISTS suppliers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, phone TEXT, email TEXT, address TEXT);''')
        cur.execute('''CREATE TABLE IF NOT EXISTS formulas (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, composition TEXT);''')
        # products & batches
        cur.execute('''CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            sku TEXT UNIQUE,
            is_medical INTEGER DEFAULT 1,
            category_id INTEGER,
            manufacturer_id INTEGER,
            formula_id INTEGER,
            unit TEXT,
            sale_price REAL DEFAULT 0,
            notes TEXT
        );''')
        cur.execute('''CREATE TABLE IF NOT EXISTS batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            supplier_id INTEGER,
            batch_no TEXT,
            quantity INTEGER NOT NULL,
            expiry_date TEXT,
            cost_price REAL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
            FOREIGN KEY(supplier_id) REFERENCES suppliers(id) ON DELETE SET NULL
        );''')
        # sales & items
        cur.execute('''CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            total REAL NOT NULL,
            customer_id INTEGER,
            customer_name TEXT,
            customer_phone TEXT,
            discount REAL DEFAULT 0,
            tax REAL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE SET NULL
        );''')
        cur.execute('''CREATE TABLE IF NOT EXISTS sale_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL,
            FOREIGN KEY(sale_id) REFERENCES sales(id) ON DELETE CASCADE,
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
        );''')
        cur.execute('''CREATE TABLE IF NOT EXISTS sale_item_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_item_id INTEGER NOT NULL,
            batch_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            FOREIGN KEY(sale_item_id) REFERENCES sale_items(id) ON DELETE CASCADE,
            FOREIGN KEY(batch_id) REFERENCES batches(id) ON DELETE CASCADE
        );''')
        cur.execute('''CREATE TABLE IF NOT EXISTS returns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_item_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(sale_item_id) REFERENCES sale_items(id) ON DELETE CASCADE
        );''')
        # settings
        cur.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);''')
        # default settings if missing
        def set_if_missing(k, v):
            cur.execute('SELECT value FROM settings WHERE key=?;', (k,))
            if not cur.fetchone():
                cur.execute('INSERT INTO settings(key,value) VALUES(?,?);', (k, v))
        set_if_missing('tax_percent', '0.0')
        set_if_missing('default_discount', '0.0')
        set_if_missing('auto_backup_enabled', '0')
        con.commit()
        con.close()

    # DB helpers
    def query(self, sql, params=()):
        with self.connect() as con:
            cur = con.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def execute(self, sql, params=()):
        with self.connect() as con:
            cur = con.execute(sql, params)
            con.commit()
            return cur.lastrowid


db = DB()


# -----------------------------
# Small reusable widgets
# -----------------------------
class AutocompleteEntry(ttk.Entry):
    """Simple autocomplete with popup Listbox. suggestions_getter(term)->list[str]"""
    def __init__(self, master, suggestions_getter=None, width=30, **kwargs):
        super().__init__(master, width=width, **kwargs)
        self.suggestions_getter = suggestions_getter
        self.var = tk.StringVar()
        self.config(textvariable=self.var)
        self.var.trace_add('write', self._on_change)
        self.listbox = None
        self.bind('<Down>', self._focus_listbox)
        self.bind('<Escape>', lambda e: self._hide())
        self.bind('<Return>', self._select_first)

    def _on_change(self, *args):
        term = self.var.get().strip()
        if not term:
            self._hide(); return
        try:
            suggestions = self.suggestions_getter(term) if self.suggestions_getter else []
        except Exception:
            suggestions = []
        if not suggestions:
            self._hide(); return
        if not self.listbox:
            self.listbox = tk.Listbox(self.master, height=6)
            self.listbox.bind('<<ListboxSelect>>', self._on_select)
            self.listbox.bind('<Return>', self._on_select)
            self.listbox.bind('<Escape>', lambda e: self._hide())
        self.listbox.delete(0, 'end')
        for s in suggestions:
            self.listbox.insert('end', s)
        # place right under entry
        x = self.winfo_rootx() - self.master.winfo_rootx()
        y = self.winfo_rooty() - self.master.winfo_rooty() + self.winfo_height()
        self.listbox.place(x=x, y=y, width=self.winfo_width())

    def _on_select(self, event=None):
        if not self.listbox: return
        sel = self.listbox.curselection()
        if not sel: return
        val = self.listbox.get(sel[0])
        self.var.set(val)
        self._hide()

    def _focus_listbox(self, event=None):
        if self.listbox:
            self.listbox.focus_set()
            self.listbox.selection_set(0)

    def _hide(self):
        if self.listbox:
            self.listbox.destroy()
            self.listbox = None

    def _select_first(self, event=None):
        if self.listbox and self.listbox.size() > 0:
            val = self.listbox.get(0)
            self.var.set(val)
            self._hide()


# -----------------------------
# Form dialog helper
# -----------------------------
class FormDialog(tk.Toplevel):
    def __init__(self, master, title, fields, initial=None, on_submit=None):
        super().__init__(master)
        self.title(title)
        self.on_submit = on_submit
        self.result = None
        pad = 8
        frm = ttk.Frame(self, padding=pad); frm.pack(fill='both', expand=True)
        self.widgets = {}
        for i, f in enumerate(fields):
            ttk.Label(frm, text=f.get('label', f['key'])).grid(row=i, column=0, sticky='w', pady=4)
            widget = f.get('widget','entry')
            if widget == 'entry':
                w = ttk.Entry(frm)
                if initial and f['key'] in initial and initial[f['key']] is not None: w.insert(0, str(initial[f['key']]))
            elif widget == 'combobox':
                state = f.get('state', 'readonly')
                values = f.get('values', [])
                w = ttk.Combobox(frm, values=values, state=state)
                if initial and f['key'] in initial and initial[f['key']] is not None:
                    try: w.set(str(initial[f['key']]))
                    except: pass
            elif widget == 'spinbox':
                w = ttk.Spinbox(frm, from_=f.get('from',0), to=f.get('to',999999), increment=f.get('inc',1))
                if initial and f['key'] in initial and initial[f['key']] is not None: w.set(str(initial[f['key']]))
            elif widget == 'text':
                w = tk.Text(frm, height=f.get('height',3), width=40)
                if initial and f['key'] in initial and initial[f['key']] is not None: w.insert('1.0', str(initial[f['key']]))
            else:
                w = ttk.Entry(frm)
            w.grid(row=i, column=1, sticky='we', pady=4)
            self.widgets[f['key']] = (w, f)
        btns = ttk.Frame(frm); btns.grid(row=len(fields), column=0, columnspan=2, pady=(10,0))
        ttk.Button(btns, text='Save', command=self._save).pack(side='left', padx=6)
        ttk.Button(btns, text='Cancel', command=self.destroy).pack(side='left')
        self.bind('<Return>', lambda e: self._save()); self.bind('<Escape>', lambda e: self.destroy())

    def _save(self):
        data = {}
        for key, (w, f) in self.widgets.items():
            widget = f.get('widget','entry')
            if widget in ('entry','combobox','spinbox'):
                try: data[key] = w.get().strip()
                except: data[key] = ''
            elif widget == 'text':
                data[key] = w.get('1.0', 'end').strip()
            else:
                data[key] = w.get().strip()
        self.result = data
        if self.on_submit: self.on_submit(data)
        self.destroy()


# -----------------------------
# App UI: Main window & frames
# -----------------------------
class App:
    def __init__(self):
        # root window
        if TTB_AVAILABLE:
            self.root = tb.Window(themename='flatly')
            # small style tweak
            try:
                style = tb.Style()
                style.configure('Card.TFrame', padding=12, relief='raised')
            except Exception:
                pass
        else:
            self.root = tk.Tk()
        self.root.title('Pharmacy Management System')
        self.root.geometry('1200x780')
        self.db = db
        self.user = None
        self._build_login()

    # ---------------- Login ----------------
    def _build_login(self):
        for w in self.root.winfo_children(): w.destroy()
        frm = ttk.Frame(self.root, padding=20); frm.pack(expand=True)
        ttk.Label(frm, text='Welcome to Pharmacy System', font=('Segoe UI', 20, 'bold')).grid(row=0, column=0, columnspan=2, pady=(0,12))
        ttk.Label(frm, text='Role').grid(row=1, column=0, sticky='e')
        role_cb = ttk.Combobox(frm, values=['admin','staff','cashier'], state='readonly'); role_cb.set('admin'); role_cb.grid(row=1, column=1, sticky='w', pady=4)
        ttk.Label(frm, text='Username').grid(row=2, column=0, sticky='e')
        user_e = ttk.Entry(frm); user_e.grid(row=2, column=1, sticky='w', pady=4)
        ttk.Label(frm, text='Password').grid(row=3, column=0, sticky='e')
        pw_e = ttk.Entry(frm, show='•'); pw_e.grid(row=3, column=1, sticky='w', pady=4)
        def try_login():
            u = user_e.get().strip(); p = pw_e.get().strip(); r = role_cb.get().strip()
            if not u or not p: return messagebox.showerror('Error','Enter username & password')
            rows = self.db.query('SELECT * FROM users WHERE username=?;',(u,))
            if not rows or rows[0]['password_hash'] != hash_pw(p) or rows[0]['role'] != r:
                return messagebox.showerror('Error','Invalid credentials or role')
            self.user = {'id':rows[0]['id'],'username':u,'role':rows[0]['role']}
            self._build_main()
        ttk.Button(frm, text='Login', command=try_login).grid(row=4, column=0, columnspan=2, pady=8)
        user_e.focus_set()
        self.root.bind('<Return>', lambda e: try_login())

    # ---------------- Main app (notebook) ----------------
    def _build_main(self):
        for w in self.root.winfo_children(): w.destroy()
        # top bar
        top = ttk.Frame(self.root); top.pack(fill='x')
        ttk.Label(top, text=f"Welcome, {self.user['username'].title()}", font=('Segoe UI',14,'bold')).pack(side='left', padx=10, pady=8)
        ttk.Button(top, text='Profile', command=self._open_profile).pack(side='right', padx=6)
        ttk.Button(top, text='Logout', command=self._logout).pack(side='right')
        # notebook
        self.nb = ttk.Notebook(self.root); self.nb.pack(fill='both', expand=True, padx=8, pady=8)
        # tabs
        self.tab_dashboard = ttk.Frame(self.nb); self.nb.add(self.tab_dashboard, text='Dashboard')
        self.tab_inventory = ttk.Frame(self.nb); self.nb.add(self.tab_inventory, text='Inventory')
        self.tab_pos = ttk.Frame(self.nb); self.nb.add(self.tab_pos, text='POS')
        self.tab_reports = ttk.Frame(self.nb); self.nb.add(self.tab_reports, text='Sale Report')
        self.tab_sale_history = ttk.Frame(self.nb); self.nb.add(self.tab_sale_history, text='Sale History')
        self.tab_return_history = ttk.Frame(self.nb); self.nb.add(self.tab_return_history, text='Return History')
        if self.user['role'] in ('admin','staff'):
            self.nb.add(ttk.Frame(self.nb), text='Suppliers/Manufacturers')  # placeholder alignment
        if self.user['role'] == 'admin':
            self.tab_manage_staff = ttk.Frame(self.nb); self.nb.add(self.tab_manage_staff, text='Manage Staff')
            self.tab_import_export = ttk.Frame(self.nb); self.nb.add(self.tab_import_export, text='Import/Export')
            self.tab_settings = ttk.Frame(self.nb); self.nb.add(self.tab_settings, text='Settings')
        # build content of tabs
        self._build_dashboard_tab()
        self._build_inventory_tab()
        self._build_pos_tab()
        self._build_sale_history_tab()
        self._build_return_history_tab()
        self._build_reports_tab()
        if self.user['role'] == 'admin':
            self._build_manage_staff_tab()
            self._build_import_export_tab()
            self._build_settings_tab()
        # helper to open tabs by name
        self._tab_name_map = {self.nb.tab(i, option='text'): i for i in range(self.nb.index('end'))}

    def _logout(self):
        self.user = None
        self._build_login()

    def _open_profile(self):
        def save(d):
            pw = d.get('new_password','').strip()
            if pw:
                self.db.execute('UPDATE users SET password_hash=? WHERE id=?;', (hash_pw(pw), self.user['id']))
                messagebox.showinfo('Profile','Password updated.')
        FormDialog(self.root, 'Profile - Change Password', [
            {'key':'username','label':'Username','widget':'entry'},
            {'key':'role','label':'Role','widget':'entry'},
            {'key':'new_password','label':'New Password','widget':'entry'},
        ], initial={'username':self.user['username'],'role':self.user['role']}, on_submit=save)

    # ---------------- Dashboard ----------------
    def _build_dashboard_tab(self):
        for w in self.tab_dashboard.winfo_children(): w.destroy()
        frame = self.tab_dashboard
        # welcome
        welcome = ttk.Label(frame, text=f"Welcome back, {self.user['username'].title()}!", font=('Segoe UI',18,'bold'), anchor='center')
        welcome.pack(pady=10)
        # stat cards container
        cards_row = ttk.Frame(frame)
        cards_row.pack(fill='x', padx=12, pady=6)

        # helper to create colored card with icon + animated number
        def make_card(parent, title, value, icon_name, bootstyle, onclick):
            if TTB_AVAILABLE:
                card = tb.Frame(parent, bootstyle=bootstyle)
            else:
                card = ttk.Frame(parent, padding=8, relief='raised')
            card.pack(side='left', expand=True, fill='both', padx=8, pady=8)

            # icon
            if TTB_AVAILABLE and Icon:
                try:
                    ic = Icon(icon_name, size=36)
                    icon_lbl = ttk.Label(card, image=ic)
                    icon_lbl.image = ic
                except Exception:
                    icon_lbl = ttk.Label(card, text='●', font=('Segoe UI', 24))
            else:
                icon_lbl = ttk.Label(card, text='●', font=('Segoe UI', 24))
            icon_lbl.pack(side='left', padx=12, pady=8)

            # text and value
            txt_fr = ttk.Frame(card)
            txt_fr.pack(side='left', fill='both', expand=True, padx=6)
            ttk.Label(txt_fr, text=title, font=('Segoe UI',11,'bold')).pack(anchor='w')
            val_lbl = ttk.Label(txt_fr, text='0', font=('Segoe UI',20,'bold'))
            val_lbl.pack(anchor='w', pady=(4,0))

            # animate count-up (1 second total)
            def animate_to(target):
                target = int(target)
                steps = 25
                for i in range(1, steps+1):
                    v = int(target * i / steps)
                    val_lbl.config(text=str(v))
                    time.sleep(1.0/steps)
            threading.Thread(target=lambda: animate_to(value), daemon=True).start()

            # click behaviour
            def on_click(e=None):
                try:
                    if onclick: onclick()
                except Exception as ex:
                    print('card click error', ex)
            for w in (card, icon_lbl, txt_fr, val_lbl):
                w.bind('<Button-1>', on_click)
            return card

        # queries for values
        sales_total = self.db.query("SELECT COALESCE(SUM(total),0) AS s FROM sales WHERE strftime('%Y-%m',created_at)=strftime('%Y-%m','now');")[0]['s']
        low_stock_count = self.db.query("""SELECT COUNT(*) AS c FROM (
            SELECT p.id, COALESCE(SUM(b.quantity),0) AS stock FROM products p LEFT JOIN batches b ON b.product_id=p.id GROUP BY p.id HAVING stock<=5
        ) t;""")[0]['c']
        near_expiry_count = self.db.query("SELECT COUNT(*) AS c FROM batches WHERE expiry_date IS NOT NULL AND julianday(expiry_date)-julianday('now')<=30 AND quantity>0;")[0]['c']
        staff_count = self.db.query("SELECT COUNT(*) AS c FROM users WHERE role IN ('staff','cashier');")[0]['c']

        # create cards
        make_card(cards_row, 'Sales (This Month)', int(sales_total), 'currency-dollar', 'success', lambda: self._open_tab_by_name('Sale History'))
        make_card(cards_row, 'Low Stock', int(low_stock_count), 'exclamation-triangle', 'danger', lambda: self._open_low_stock())
        make_card(cards_row, 'Near Expiry (30d)', int(near_expiry_count), 'clock', 'warning', lambda: self._open_near_expiry())
        if self.user['role'] == 'admin':
            make_card(cards_row, 'Staff Count', int(staff_count), 'people-fill', 'info', lambda: self._open_tab_by_name('Manage Staff'))

        # optional sales graph (if matplotlib)
        if MATPLOTLIB_AVAILABLE:
            try:
                fig = Figure(figsize=(8,2.2), dpi=90); ax = fig.add_subplot(111)
                days = []
                totals = []
                for i in range(6,-1,-1):
                    d = (datetime.now().date() - timedelta(days=i)).strftime('%Y-%m-%d')
                    days.append(d[5:])
                    r = self.db.query('SELECT COALESCE(SUM(total),0) AS s FROM sales WHERE substr(created_at,1,10)=?;', (d,))
                    totals.append(float(r[0]['s']))
                ax.plot(days, totals, marker='o'); ax.set_title('Sales — Last 7 days'); ax.grid(True)
                canvas = FigureCanvasTkAgg(fig, master=frame); canvas.draw(); canvas.get_tk_widget().pack(fill='x', padx=12, pady=10)
            except Exception as e:
                print('graph error', e)

    # ---------------- Inventory ----------------
    def _build_inventory_tab(self):
        for w in self.tab_inventory.winfo_children(): w.destroy()
        frame = self.tab_inventory
        header = ttk.Frame(frame); header.pack(fill='x', pady=6)
        ttk.Label(header, text='Inventory', font=('Segoe UI',14,'bold')).pack(side='left', padx=10)
        ttk.Button(header, text='Add Product', command=self._inv_add_product).pack(side='right', padx=8)
        ttk.Button(header, text='Refresh', command=self._inv_refresh).pack(side='right')
        # product tree
        cols = ('id','name','sku','unit','category','manufacturer','price','stock')
        tree = ttk.Treeview(frame, columns=cols, show='headings', height=18)
        for c in cols:
            tree.heading(c, text=c.capitalize())
            tree.column(c, width=120, anchor='w')
        tree.pack(fill='both', expand=True, padx=10, pady=8)
        self._inv_tree = tree
        self._inv_refresh()

    def _inv_refresh(self):
        tree = getattr(self, '_inv_tree', None)
        if not tree: return
        for r in tree.get_children(): tree.delete(r)
        rows = self.db.query('''SELECT p.id,p.name,p.sku,p.unit,c.name AS category,m.name AS manufacturer,p.sale_price AS price,
            COALESCE((SELECT SUM(quantity) FROM batches b WHERE b.product_id=p.id),0) AS stock
            FROM products p LEFT JOIN categories c ON p.category_id=c.id LEFT JOIN manufacturers m ON p.manufacturer_id=m.id
            ORDER BY p.name;''')
        for r in rows:
            tree.insert('', 'end', iid=r['id'], values=(r['id'], r['name'], r['sku'] or '', r['unit'] or '', r['category'] or '', r['manufacturer'] or '', f"{r['price']:.2f}", r['stock']))

    def _inv_add_product(self):
        # fields: name, sku, unit (editable combobox), category, manufacturer, formula, price, notes
        cats = [r['name'] for r in self.db.query('SELECT name FROM categories ORDER BY name;')]
        mans = [r['name'] for r in self.db.query('SELECT name FROM manufacturers ORDER BY name;')]
        forms = [r['name'] for r in self.db.query('SELECT name FROM formulas ORDER BY name;')]
        units = ['mg','ml','g','IU','tablet','capsule','bottle','strip','box']
        def save(d):
            if not d['name']:
                return messagebox.showerror('Error','Name required')
            # map names to ids if possible
            cat_id = None; man_id = None; form_id = None
            if d.get('category'):
                row = self.db.query('SELECT id FROM categories WHERE name=?;',(d['category'],))
                if row: cat_id = row[0]['id']
                else:
                    try: cat_id = self.db.execute('INSERT INTO categories(name) VALUES(?);',(d['category'],))
                    except: cat_id=None
            if d.get('manufacturer'):
                row = self.db.query('SELECT id FROM manufacturers WHERE name=?;',(d['manufacturer'],))
                if row: man_id = row[0]['id']
                else:
                    try: man_id = self.db.execute('INSERT INTO manufacturers(name) VALUES(?);',(d['manufacturer'],))
                    except: man_id=None
            if d.get('formula'):
                row = self.db.query('SELECT id FROM formulas WHERE name=?;',(d['formula'],))
                if row: form_id = row[0]['id']
                else:
                    try: form_id = self.db.execute('INSERT INTO formulas(name) VALUES(?);',(d['formula'],))
                    except: form_id=None
            try:
                self.db.execute('INSERT INTO products(name,sku,is_medical,category_id,manufacturer_id,formula_id,unit,sale_price,notes) VALUES(?,?,?,?,?,?,?,?,?);',
                                (d.get('name'), d.get('sku') or None, 1, cat_id, man_id, form_id, d.get('unit') or '', float(d.get('price') or 0), d.get('notes') or ''))
                messagebox.showinfo('Saved','Product added'); self._inv_refresh()
            except sqlite3.IntegrityError:
                return messagebox.showerror('Error','SKU must be unique')
        fields = [
            {'key':'name','label':'Name'},
            {'key':'sku','label':'SKU'},
            {'key':'unit','label':'Unit','widget':'combobox','values':units,'state':'normal'},
            {'key':'category','label':'Category','widget':'combobox','values':cats,'state':'normal'},
            {'key':'manufacturer','label':'Manufacturer','widget':'combobox','values':mans,'state':'normal'},
            {'key':'formula','label':'Formula','widget':'combobox','values':forms,'state':'normal'},
            {'key':'price','label':'Sale Price'},
            {'key':'notes','label':'Notes','widget':'text'}
        ]
        FormDialog(self.root, 'Add Product', fields, on_submit=save)

    # ---------------- POS ----------------
    def _build_pos_tab(self):
        for w in self.tab_pos.winfo_children(): w.destroy()
        top = ttk.Frame(self.tab_pos); top.pack(fill='x', padx=8, pady=6)
        ttk.Label(top, text='Customer Name').pack(side='left'); cust_e = ttk.Entry(top, width=20); cust_e.pack(side='left', padx=6)
        ttk.Label(top, text='Mobile').pack(side='left'); phone_e = ttk.Entry(top, width=14); phone_e.pack(side='left', padx=6)
        ttk.Label(top, text='Product').pack(side='left', padx=(8,0))
        prod_entry = AutocompleteEntry(top, suggestions_getter=self._product_suggestions, width=40); prod_entry.pack(side='left', padx=6)
        ttk.Label(top, text='Qty').pack(side='left', padx=(8,0)); qty_e = ttk.Entry(top, width=6); qty_e.pack(side='left', padx=6)
        ttk.Button(top, text='Add', command=lambda: add_to_cart()).pack(side='left', padx=6)
        # cart tree
        cols = ('product','unit','qty','price','expiry','subtotal')
        tree = ttk.Treeview(self.tab_pos, columns=cols, show='headings', height=14)
        for c in cols:
            tree.heading(c, text=c.capitalize()); tree.column(c, width=120, anchor='w')
        tree.pack(fill='both', expand=True, padx=8, pady=8)
        total_lbl = ttk.Label(self.tab_pos, text='Total: 0.00', font=('Segoe UI',12,'bold')); total_lbl.pack(anchor='e', padx=12)
        cart = []
        def refresh_cart():
            tree.delete(*tree.get_children())
            total = 0.0
            for it in cart:
                tree.insert('', 'end', values=(it['name'], it.get('unit',''), it['qty'], f"{it['price']:.2f}", it.get('expiry',''), f"{it['subtotal']:.2f}"))
                total += it['subtotal']
            total_lbl.config(text=f'Total: {total:.2f}')
        def add_to_cart():
            pname = prod_entry.get().strip()
            try:
                qty = int(qty_e.get().strip())
            except:
                qty = 0
            if not pname or qty <= 0:
                return messagebox.showwarning('Input','Enter product and qty>0')
            rows = self.db.query('SELECT * FROM products WHERE name=? LIMIT 1;',(pname,))
            if not rows:
                return messagebox.showwarning('Not found','Product not found. Use autocomplete.')
            p = rows[0]
            # get nearest expiry batch with quantity
            batches = self.db.query('SELECT id,quantity,expiry_date FROM batches WHERE product_id=? AND quantity>0 ORDER BY expiry_date ASC NULLS LAST, created_at ASC;',(p['id'],))
            expiry = batches[0]['expiry_date'] if batches else ''
            cart.append({'id':p['id'],'name':p['name'],'unit':p.get('unit',''),'qty':qty,'price':p['sale_price'],'subtotal':p['sale_price']*qty,'expiry':expiry})
            prod_entry.delete(0,'end'); qty_e.delete(0,'end'); refresh_cart()
        def checkout():
            if not cart: return messagebox.showwarning('Empty','Cart is empty')
            # check stock: ensure sum of batches >= qty for each product
            shortages = []
            for it in cart:
                total_stock = self.db.query('SELECT COALESCE(SUM(quantity),0) AS s FROM batches WHERE product_id=?;',(it['id'],))[0]['s']
                if total_stock < it['qty']:
                    shortages.append((it['name'], total_stock, it['qty']))
            if shortages:
                msg = "Cannot complete sale. Out of stock for:\n"
                for s in shortages:
                    msg += f"- {s[0]} (available {s[1]}, requested {s[2]})\n"
                return messagebox.showerror('Out of stock', msg)
            # save customer or link existing by phone
            cname = cust_e.get().strip(); cphone = phone_e.get().strip()
            cust_id = None
            if cphone:
                existing = self.db.query('SELECT id FROM customers WHERE phone=?;',(cphone,))
                if existing: cust_id = existing[0]['id']
                else:
                    cust_id = self.db.execute('INSERT INTO customers(name,phone) VALUES(?,?);',(cname or 'Guest', cphone))
            total = sum(it['subtotal'] for it in cart)
            # apply settings tax/discount
            tax_percent = float(self.db.query('SELECT value FROM settings WHERE key="tax_percent";')[0]['value'] or 0)
            disc_percent = float(self.db.query('SELECT value FROM settings WHERE key="default_discount";')[0]['value'] or 0)
            tax_val = total * tax_percent/100.0
            disc_val = total * disc_percent/100.0
            sale_id = self.db.execute('INSERT INTO sales(user_id,total,customer_id,customer_name,customer_phone,discount,tax,created_at) VALUES(?,?,?,?,?,?,?,?);',
                                      (self.user['id'], total, cust_id, cname, cphone, disc_val, tax_val, now_str()))
            # create sale_items and deduct batches FIFO
            for it in cart:
                si = self.db.execute('INSERT INTO sale_items(sale_id,product_id,quantity,price) VALUES(?,?,?,?);',(sale_id, it['id'], it['qty'], it['price']))
                qty_needed = it['qty']
                batches = self.db.query('SELECT id,quantity FROM batches WHERE product_id=? AND quantity>0 ORDER BY created_at ASC;',(it['id'],))
                for b in batches:
                    if qty_needed <= 0: break
                    take = min(qty_needed, b['quantity'])
                    self.db.execute('UPDATE batches SET quantity=quantity-? WHERE id=?;',(take, b['id']))
                    self.db.execute('INSERT INTO sale_item_batches(sale_item_id,batch_id,quantity) VALUES(?,?,?);',(si, b['id'], take))
                    qty_needed -= take
            # optionally print receipt
            if REPORTLAB_AVAILABLE and messagebox.askyesno('Receipt','Print receipt now?'):
                self._print_receipt(sale_id)
            messagebox.showinfo('Sale','Sale completed'); cart.clear(); refresh_cart(); self._inv_refresh(); self._sale_history_refresh()
        ttk.Button(self.tab_pos, text='Checkout', command=checkout).pack(anchor='e', padx=10, pady=6)

    def _product_suggestions(self, term):
        rows = self.db.query('SELECT name, sale_price FROM products WHERE name LIKE ? ORDER BY name LIMIT 12;', (f'%{term}%',))
        return [r['name'] for r in rows]

    # ---------------- Sale History ----------------
    def _build_sale_history_tab(self):
        for w in self.tab_sale_history.winfo_children(): w.destroy()
        header = ttk.Frame(self.tab_sale_history); header.pack(fill='x', pady=6)
        ttk.Label(header, text='Sale History', font=('Segoe UI',14,'bold')).pack(side='left', padx=8)
        ttk.Button(header, text='Refresh', command=self._sale_history_refresh).pack(side='right', padx=6)
        ttk.Button(header, text='Print Receipt (Selected)', command=self._sale_history_print_selected).pack(side='right')
        cols = ('sale_id','date','customer','product','qty','price','expiry','supplier','manufacturer','subtotal')
        tree = ttk.Treeview(self.tab_sale_history, columns=cols, show='headings', height=18)
        for c in cols: tree.heading(c, text=c.capitalize()); tree.column(c, width=120, anchor='w')
        tree.pack(fill='both', expand=True, padx=8, pady=8)
        self._sale_history_tree = tree
        self._sale_history_refresh()

    def _sale_history_refresh(self):
        tree = getattr(self, '_sale_history_tree', None)
        if not tree: return
        tree.delete(*tree.get_children())
        rows = self.db.query('''SELECT s.id AS sale_id, s.created_at AS date, s.customer_name AS customer,
            p.name AS product, sib.quantity AS qty, si.price AS price, b.expiry_date AS expiry,
            sup.name AS supplier, m.name AS manufacturer, (sib.quantity*si.price) AS subtotal
            FROM sales s
            JOIN sale_items si ON si.sale_id=s.id
            JOIN sale_item_batches sib ON sib.sale_item_id=si.id
            JOIN batches b ON b.id=sib.batch_id
            JOIN products p ON p.id=si.product_id
            LEFT JOIN suppliers sup ON sup.id=b.supplier_id
            LEFT JOIN manufacturers m ON m.id=p.manufacturer_id
            ORDER BY s.created_at DESC LIMIT 200;''')
        for r in rows:
            tree.insert('', 'end', values=(r['sale_id'], r['date'], r['customer'] or '', r['product'], r['qty'], f"{r['price']:.2f}", r['expiry'] or '', r['supplier'] or '', r['manufacturer'] or '', f"{r['subtotal']:.2f}"))

    def _sale_history_print_selected(self):
        sel = self._sale_history_tree.selection()
        if not sel: return messagebox.showwarning('Select','Select a row (sale item) to print its sale receipt')
        item = self._sale_history_tree.item(sel[0])['values']
        sale_id = item[0]
        if REPORTLAB_AVAILABLE:
            self._print_receipt(sale_id)
        else:
            messagebox.showwarning('Missing','reportlab required for PDF receipt')

    def _print_receipt(self, sale_id):
        if not REPORTLAB_AVAILABLE:
            return messagebox.showerror('Missing','reportlab is required to generate PDF receipts')
        items = self.db.query('SELECT si.quantity,si.price,p.name FROM sale_items si JOIN products p ON si.product_id=p.id WHERE si.sale_id=?;', (sale_id,))
        sale = self.db.query('SELECT * FROM sales WHERE id=?;', (sale_id,))
        if not sale:
            return messagebox.showerror('Error','Sale not found')
        sale = sale[0]
        receipts_dir = os.path.join(os.path.dirname(__file__), 'receipts'); os.makedirs(receipts_dir, exist_ok=True)
        fp = os.path.join(receipts_dir, f'receipt_{sale_id}.pdf')
        c = pdf_canvas.Canvas(fp, pagesize=A4); width, height = A4; y = height - 60
        c.setFont('Helvetica-Bold', 14); c.drawString(50, y, 'Pharmacy Receipt'); y -= 25
        c.setFont('Helvetica', 10); c.drawString(50, y, f'Sale ID: {sale_id}'); c.drawString(300, y, f'Date: {sale["created_at"]}'); y -= 20
        if sale['customer_name']: c.drawString(50, y, f'Customer: {sale["customer_name"]}'); c.drawString(300, y, f'Phone: {sale["customer_phone"] or ""}'); y -= 20
        c.drawString(50, y, f'Cashier ID: {sale["user_id"]}'); y -= 25
        c.setFont('Helvetica-Bold', 10); c.drawString(50, y, 'Product'); c.drawString(300, y, 'Qty'); c.drawString(360, y, 'Price'); c.drawString(430, y, 'Subtotal'); y -= 15
        c.setFont('Helvetica', 10)
        for it in items:
            c.drawString(50, y, str(it['name'])); c.drawString(300, y, str(it['quantity'])); c.drawString(360, y, f"{it['price']:.2f}"); c.drawString(430, y, f"{it['price']*it['quantity']:.2f}"); y -= 15
            if y < 80:
                c.showPage(); y = height - 60
        c.setFont('Helvetica-Bold', 12); c.drawString(50, y-20, f'Total: {sale["total"]:.2f}')
        c.save()
        try:
            os.startfile(fp)
        except Exception:
            pass
        messagebox.showinfo('Receipt Saved', f'Saved to {fp}')

    # ---------------- Return History ----------------
    def _build_return_history_tab(self):
        for w in self.tab_return_history.winfo_children(): w.destroy()
        cols = ('id','sale_item','product','qty','reason','created','expiry')
        tree = ttk.Treeview(self.tab_return_history, columns=cols, show='headings')
        for c in cols: tree.heading(c, text=c.capitalize()); tree.column(c, width=120, anchor='w')
        tree.pack(fill='both', expand=True, padx=8, pady=8)
        self._return_tree = tree
        self._return_refresh()

    def _return_refresh(self):
        tree = getattr(self, '_return_tree', None)
        if not tree: return
        tree.delete(*tree.get_children())
        rows = self.db.query('''SELECT r.id, r.sale_item_id AS sale_item, p.name AS product, r.quantity AS qty, r.reason, r.created_at AS created, b.expiry_date AS expiry
            FROM returns r JOIN sale_items si ON si.id=r.sale_item_id JOIN products p ON p.id=si.product_id
            LEFT JOIN sale_item_batches sib ON sib.sale_item_id=si.id LEFT JOIN batches b ON b.id=sib.batch_id
            ORDER BY r.id DESC LIMIT 500;''')
        for r in rows:
            tree.insert('', 'end', values=(r['id'], r['sale_item'], r['product'], r['qty'], r['reason'], r['created'], r['expiry'] or ''))

    # ---------------- Sale Report (filters + autocomplete + date) ----------------
    def _build_reports_tab(self):
        for w in self.tab_reports.winfo_children(): w.destroy()
        f = ttk.Frame(self.tab_reports); f.pack(fill='x', padx=8, pady=6)
        # supplier, manufacturer, product autocomplete fields
        ttk.Label(f, text='Supplier').grid(row=0, column=0, sticky='e', padx=4, pady=4)
        sup_e = AutocompleteEntry(f, suggestions_getter=self._supplier_suggestions, width=30); sup_e.grid(row=0, column=1, padx=4)
        ttk.Label(f, text='Manufacturer').grid(row=0, column=2, sticky='e', padx=4)
        man_e = AutocompleteEntry(f, suggestions_getter=self._manufacturer_suggestions, width=30); man_e.grid(row=0, column=3, padx=4)
        ttk.Label(f, text='Product').grid(row=1, column=0, sticky='e', padx=4)
        prod_e = AutocompleteEntry(f, suggestions_getter=self._product_suggestions, width=30); prod_e.grid(row=1, column=1, padx=4)
        ttk.Label(f, text='From Date').grid(row=1, column=2, sticky='e', padx=4)
        if TKCAL_AVAILABLE:
            from_e = DateEntry(f, width=12); from_e.grid(row=1, column=3, padx=4)
        else:
            from_e = ttk.Entry(f, width=12); from_e.grid(row=1, column=3, padx=4)
        ttk.Button(f, text='Apply', command=lambda: self._apply_report_filters(sup_e.get().strip(), man_e.get().strip(), prod_e.get().strip(), from_e.get().strip())).grid(row=2, column=0, columnspan=4, pady=8)
        # results tree
        cols = ('sale_id','date','customer','product','qty','price','subtotal')
        tree = ttk.Treeview(self.tab_reports, columns=cols, show='headings')
        for c in cols: tree.heading(c, text=c.capitalize()); tree.column(c, width=120, anchor='w')
        tree.pack(fill='both', expand=True, padx=8, pady=6)
        self._report_tree = tree

    def _apply_report_filters(self, supplier, manufacturer, product, from_date):
        tree = getattr(self, '_report_tree', None)
        if not tree: return
        tree.delete(*tree.get_children())
        where = []
        params = []
        if supplier:
            where.append('sup.name LIKE ?'); params.append(f'%{supplier}%')
        if manufacturer:
            where.append('m.name LIKE ?'); params.append(f'%{manufacturer}%')
        if product:
            where.append('p.name LIKE ?'); params.append(f'%{product}%')
        if from_date:
            try:
                # accept YYYY-MM-DD or DateEntry
                dt = from_date
                if len(dt) == 10:
                    where.append("s.created_at >= ?"); params.append(dt + " 00:00:00")
            except:
                pass
        where_sql = ('WHERE ' + ' AND '.join(where)) if where else ''
        sql = f'''SELECT s.id AS sale_id, s.created_at AS date, s.customer_name AS customer, p.name AS product, si.quantity AS qty, si.price AS price, (si.quantity*si.price) AS subtotal
            FROM sales s JOIN sale_items si ON si.sale_id=s.id JOIN products p ON p.id=si.product_id
            LEFT JOIN sale_item_batches sib ON sib.sale_item_id=si.id LEFT JOIN batches b ON b.id=sib.batch_id
            LEFT JOIN suppliers sup ON sup.id=b.supplier_id
            LEFT JOIN manufacturers m ON m.id=p.manufacturer_id
            {where_sql}
            ORDER BY s.created_at DESC LIMIT 1000;'''
        rows = self.db.query(sql, tuple(params))
        for r in rows:
            self._report_tree.insert('', 'end', values=(r['sale_id'], r['date'], r['customer'] or '', r['product'], r['qty'], f"{r['price']:.2f}", f"{r['subtotal']:.2f}"))

    # ---------------- Manage Staff ----------------
    def _build_manage_staff_tab(self):
        for w in self.tab_manage_staff.winfo_children(): w.destroy()
        header = ttk.Frame(self.tab_manage_staff); header.pack(fill='x', pady=6)
        ttk.Label(header, text='Manage Staff', font=('Segoe UI',14,'bold')).pack(side='left', padx=8)
        ttk.Button(header, text='Add Staff', command=self._add_staff).pack(side='right', padx=6)
        tree = ttk.Treeview(self.tab_manage_staff, columns=('id','username','role'), show='headings')
        for c in ('id','username','role'): tree.heading(c, text=c.capitalize()); tree.column(c, width=150, anchor='w')
        tree.pack(fill='both', expand=True, padx=8, pady=8)
        self._staff_tree = tree
        self._refresh_staff()

    def _refresh_staff(self):
        tree = getattr(self, '_staff_tree', None)
        if not tree: return
        tree.delete(*tree.get_children())
        rows = self.db.query("SELECT id,username,role FROM users WHERE role IN ('staff','cashier') ORDER BY role,username;")
        for r in rows: tree.insert('', 'end', values=(r['id'], r['username'], r['role']))

    def _add_staff(self):
        def save(d):
            uname = d.get('username','').strip(); role = d.get('role','staff'); pw = d.get('password','').strip()
            if not uname or not pw: return messagebox.showerror('Error','Username and password required')
            # check duplicate
            exists = self.db.query('SELECT id FROM users WHERE username=?;',(uname,))
            if exists:
                return messagebox.showerror('Error','Username already exists. Choose another username.')
            self.db.execute('INSERT INTO users(username,password_hash,role) VALUES(?,?,?);',(uname, hash_pw(pw), role))
            messagebox.showinfo('Saved','User created'); self._refresh_staff()
        FormDialog(self.root, 'Add Staff', [
            {'key':'username','label':'Username'},
            {'key':'password','label':'Password'},
            {'key':'role','label':'Role','widget':'combobox','values':['staff','cashier'],'state':'readonly'}
        ], initial={'role':'staff'}, on_submit=save)

    # ---------------- Import / Export ----------------
    def _build_import_export_tab(self):
        for w in self.tab_import_export.winfo_children(): w.destroy()
        frm = ttk.Frame(self.tab_import_export); frm.pack(fill='x', padx=8, pady=8)
        ttk.Label(frm, text='Import / Export (Admin)').pack(anchor='w')
        target_cb = ttk.Combobox(frm, values=['products','batches','suppliers','manufacturers','categories','formulas','customers'], state='readonly'); target_cb.set('products'); target_cb.pack(side='left', padx=6)
        ttk.Button(frm, text='Import CSV', command=lambda: self._import_csv(target_cb.get())).pack(side='left', padx=6)
        ttk.Button(frm, text='Export CSV', command=lambda: self._export_csv(target_cb.get())).pack(side='left', padx=6)
        ttk.Button(frm, text='Export XLSX', command=lambda: self._export_xlsx(target_cb.get())).pack(side='left', padx=6)
        # backup controls
        bfr = ttk.Frame(self.tab_import_export); bfr.pack(fill='x', padx=8, pady=8)
        ttk.Button(bfr, text='Backup Now', command=self._backup_now).pack(side='left', padx=6)
        self.auto_backup_var = tk.IntVar(value=int(self.db.query('SELECT value FROM settings WHERE key="auto_backup_enabled";')[0]['value']))
        ttk.Checkbutton(bfr, text='Enable Auto Backup (every 12 hours this session)', variable=self.auto_backup_var, command=self._toggle_auto_backup).pack(side='left', padx=6)
        self._auto_job = None
        if self.auto_backup_var.get(): self._schedule_auto_backup()

    def _import_csv(self, target):
        path = filedialog.askopenfilename(filetypes=[('CSV','*.csv'),('All files','*.*')])
        if not path: return
        cnt = 0
        try:
            with open(path, newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if target == 'products':
                        self.db.execute('INSERT OR IGNORE INTO products(name,sku,unit,sale_price,notes) VALUES(?,?,?,?,?);',
                                        (row.get('name') or row.get('Name'), row.get('sku'), row.get('unit'), float(row.get('sale_price') or 0), row.get('notes') or ''))
                        cnt += 1
                    elif target == 'suppliers':
                        self.db.execute('INSERT OR IGNORE INTO suppliers(name,phone,email,address) VALUES(?,?,?,?);', (row.get('name'), row.get('phone'), row.get('email'), row.get('address'))); cnt += 1
                    elif target == 'manufacturers':
                        self.db.execute('INSERT OR IGNORE INTO manufacturers(name,contact,notes) VALUES(?,?,?);', (row.get('name'), row.get('contact'), row.get('notes'))); cnt += 1
                    elif target == 'categories':
                        self.db.execute('INSERT OR IGNORE INTO categories(name,notes) VALUES(?,?);', (row.get('name'), row.get('notes'))); cnt += 1
                    elif target == 'formulas':
                        self.db.execute('INSERT OR IGNORE INTO formulas(name,composition) VALUES(?,?);', (row.get('name'), row.get('composition'))); cnt += 1
                    elif target == 'customers':
                        self.db.execute('INSERT OR IGNORE INTO customers(name,phone,notes) VALUES(?,?,?);', (row.get('name'), row.get('phone'), row.get('notes'))); cnt += 1
                    elif target == 'batches':
                        # try map by product sku or name
                        pid = None
                        if row.get('product_sku'): 
                            p = self.db.query('SELECT id FROM products WHERE sku=?;',(row.get('product_sku'),))
                            if p: pid = p[0]['id']
                        if not pid and row.get('product_name'):
                            p = self.db.query('SELECT id FROM products WHERE name=?;',(row.get('product_name'),))
                            if p: pid = p[0]['id']
                        sid = None
                        if row.get('supplier'): 
                            s = self.db.query('SELECT id FROM suppliers WHERE name=?;',(row.get('supplier'),))
                            if s: sid = s[0]['id']
                        if pid:
                            self.db.execute('INSERT INTO batches(product_id,supplier_id,batch_no,quantity,expiry_date,cost_price,created_at) VALUES(?,?,?,?,?,?,?);',
                                            (pid, sid, row.get('batch_no') or '', int(row.get('quantity') or 0), row.get('expiry_date') or None, float(row.get('cost_price') or 0), now_str()))
                            cnt += 1
            messagebox.showinfo('Import', f'Imported approx {cnt} rows.')
            self._inv_refresh()
        except Exception as e:
            messagebox.showerror('Import Error', str(e))

    def _export_csv(self, target):
        path = filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV','*.csv')])
        if not path: return
        rows=[]; headers=[]
        if target == 'products':
            rows = self.db.query('SELECT name,sku,unit,sale_price,notes FROM products ORDER BY name;'); headers=['name','sku','unit','sale_price','notes']
        elif target == 'batches':
            rows = self.db.query('SELECT p.name as product, b.batch_no, b.quantity, b.expiry_date, s.name as supplier FROM batches b LEFT JOIN products p ON p.id=b.product_id LEFT JOIN suppliers s ON s.id=b.supplier_id ORDER BY b.id DESC;'); headers=['product','batch_no','quantity','expiry_date','supplier']
        elif target == 'suppliers':
            rows = self.db.query('SELECT name,phone,email,address FROM suppliers ORDER BY name;'); headers=['name','phone','email','address']
        elif target == 'manufacturers':
            rows = self.db.query('SELECT name,contact,notes FROM manufacturers ORDER BY name;'); headers=['name','contact','notes']
        elif target == 'categories':
            rows = self.db.query('SELECT name,notes FROM categories ORDER BY name;'); headers=['name','notes']
        elif target == 'formulas':
            rows = self.db.query('SELECT name,composition FROM formulas ORDER BY name;'); headers=['name','composition']
        elif target == 'customers':
            rows = self.db.query('SELECT name,phone,notes FROM customers ORDER BY name;'); headers=['name','phone','notes']
        with open(path, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f); w.writerow(headers)
            for r in rows: w.writerow([r.get(h,'') for h in headers])
        messagebox.showinfo('Export', f'Exported {len(rows)} rows to {path}')

    def _export_xlsx(self, target):
        if not OPENPYXL_AVAILABLE:
            return messagebox.showerror('Missing', 'openpyxl required for XLSX export')
        path = filedialog.asksaveasfilename(defaultextension='.xlsx', filetypes=[('Excel','*.xlsx')])
        if not path: return
        rows=[]; headers=[]
        if target == 'products':
            rows = self.db.query('SELECT name,sku,unit,sale_price,notes FROM products ORDER BY name;'); headers=['name','sku','unit','sale_price','notes']
        elif target == 'batches':
            rows = self.db.query('SELECT p.name as product, b.batch_no, b.quantity, b.expiry_date, s.name as supplier FROM batches b LEFT JOIN products p ON p.id=b.product_id LEFT JOIN suppliers s ON s.id=b.supplier_id ORDER BY b.id DESC;'); headers=['product','batch_no','quantity','expiry_date','supplier']
        elif target == 'suppliers':
            rows = self.db.query('SELECT name,phone,email,address FROM suppliers ORDER BY name;'); headers=['name','phone','email','address']
        elif target == 'manufacturers':
            rows = self.db.query('SELECT name,contact,notes FROM manufacturers ORDER BY name;'); headers=['name','contact','notes']
        elif target == 'categories':
            rows = self.db.query('SELECT name,notes FROM categories ORDER BY name;'); headers=['name','notes']
        elif target == 'formulas':
            rows = self.db.query('SELECT name,composition FROM formulas ORDER BY name;'); headers=['name','composition']
        elif target == 'customers':
            rows = self.db.query('SELECT name,phone,notes FROM customers ORDER BY name;'); headers=['name','phone','notes']
        from openpyxl import Workbook
        wb = Workbook(); ws = wb.active; ws.append(headers)
        for r in rows: ws.append([r.get(h,'') for h in headers])
        wb.save(path); messagebox.showinfo('Export', f'Exported {len(rows)} rows to {path}')

    def _backup_now(self):
        ts = datetime.now().strftime('%Y%m%d%H%M%S')
        dst = os.path.join(BACKUP_FOLDER, f'pharmacy_backup_{ts}.db')
        try:
            with open(DB_PATH, 'rb') as src, open(dst, 'wb') as out:
                out.write(src.read())
            messagebox.showinfo('Backup', f'Backup saved to {dst}')
        except Exception as e:
            messagebox.showerror('Backup Failed', str(e))

    def _toggle_auto_backup(self):
        val = int(self.auto_backup_var.get())
        self.db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?);', ('auto_backup_enabled', str(val)))
        if val:
            self._schedule_auto_backup()
        else:
            if getattr(self, '_auto_job', None):
                try: self.root.after_cancel(self._auto_job)
                except: pass
                self._auto_job = None

    def _schedule_auto_backup(self):
        # run backup now and schedule next in 12 hours (43200000 ms)
        self._backup_now()
        try:
            self._auto_job = self.root.after(12*3600*1000, self._schedule_auto_backup)
        except Exception:
            pass

    # ---------------- Settings (admin) ----------------
    def _build_settings_tab(self):
        for w in self.tab_settings.winfo_children(): w.destroy()
        f = ttk.Frame(self.tab_settings); f.pack(fill='x', padx=8, pady=8)
        ttk.Label(f, text='Default Tax Percent (%)').grid(row=0, column=0, sticky='w', padx=4, pady=4)
        tax_e = ttk.Entry(f, width=8); tax_e.grid(row=0, column=1, padx=4)
        ttk.Label(f, text='Default Discount (%)').grid(row=1, column=0, sticky='w', padx=4, pady=4)
        disc_e = ttk.Entry(f, width=8); disc_e.grid(row=1, column=1, padx=4)
        tax_val = self.db.query('SELECT value FROM settings WHERE key="tax_percent";')[0]['value']; tax_e.insert(0, tax_val)
        disc_val = self.db.query('SELECT value FROM settings WHERE key="default_discount";')[0]['value']; disc_e.insert(0, disc_val)
        def save():
            self.db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?);', ('tax_percent', tax_e.get().strip()))
            self.db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?);', ('default_discount', disc_e.get().strip()))
            messagebox.showinfo('Saved','Settings saved')
        ttk.Button(f, text='Save Settings', command=save).grid(row=3, column=0, columnspan=2, pady=8)

    # ---------------- Small helpers ----------------
    def _open_tab_by_name(self, name):
        # find index by text
        for i in range(self.nb.index('end')):
            if self.nb.tab(i, option='text') == name:
                self.nb.select(i); return
        messagebox.showinfo('Info', f'Tab {name} not found')

    def _open_low_stock(self):
        self._open_tab_by_name('Inventory')
        # optionally filter view to only low stock - for simplicity we refresh and user can see status in stock col
        # (could implement a filtered tree view modal if required)

    def _open_near_expiry(self):
        self._open_tab_by_name('Inventory')
        # same as above - user can inspect batches view (not implemented as separate view in this simplified merge)

    # suggestions for autocomplete in various places
    def _supplier_suggestions(self, term):
        rows = self.db.query('SELECT name FROM suppliers WHERE name LIKE ? ORDER BY name LIMIT 10;', (f'%{term}%',))
        return [r['name'] for r in rows]

    def _manufacturer_suggestions(self, term):
        rows = self.db.query('SELECT name FROM manufacturers WHERE name LIKE ? ORDER BY name LIMIT 10;', (f'%{term}%',))
        return [r['name'] for r in rows]

    # run
    def run(self):
        # expose root to other methods easily
        self.root = self.root  # no-op
        self.root.mainloop()


if __name__ == '__main__':
    app = App()
    app.run()

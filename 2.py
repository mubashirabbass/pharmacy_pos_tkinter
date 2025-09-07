# pharmacy_app_updated.py
# Inventory + POS + FIFO deduction + LIFO return restock + searchable POS + improved reports + receipt printing

import os
import sqlite3
import hashlib
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

try:
    import ttkbootstrap as tb
except ImportError:
    tb = None

# Optional: reportlab is used for PDF receipts and reports
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as pdf_canvas
    REPORTLAB = True
except Exception:
    REPORTLAB = False

DB_PATH = os.path.join(os.path.dirname(__file__), 'pharmacy.db')

# ---------------- DB Setup ----------------
def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def ensure_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute('PRAGMA foreign_keys = ON;')

    # Users (role: admin/cashier)
    cur.execute(
        '''CREATE TABLE IF NOT EXISTS users (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               username TEXT UNIQUE NOT NULL,
               password_hash TEXT NOT NULL,
               role TEXT NOT NULL CHECK(role IN ('admin','cashier'))
           );'''
    )

    # Reference tables
    cur.execute(
        '''CREATE TABLE IF NOT EXISTS categories (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               name TEXT UNIQUE NOT NULL,
               notes TEXT
           );'''
    )

    cur.execute(
        '''CREATE TABLE IF NOT EXISTS manufacturers (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               name TEXT UNIQUE NOT NULL,
               contact TEXT,
               notes TEXT
           );'''
    )

    cur.execute(
        '''CREATE TABLE IF NOT EXISTS suppliers (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               name TEXT UNIQUE NOT NULL,
               phone TEXT,
               email TEXT,
               address TEXT
           );'''
    )

    cur.execute(
        '''CREATE TABLE IF NOT EXISTS formulas (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               name TEXT UNIQUE NOT NULL,
               composition TEXT
           );'''
    )

    # Products
    cur.execute(
        '''CREATE TABLE IF NOT EXISTS products (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               name TEXT NOT NULL,
               sku TEXT UNIQUE,
               is_medical INTEGER NOT NULL DEFAULT 1,
               category_id INTEGER,
               manufacturer_id INTEGER,
               formula_id INTEGER,
               unit TEXT,
               sale_price REAL NOT NULL DEFAULT 0,
               notes TEXT
           );'''
    )

    # Batches / Stock entries (incoming supplies)
    cur.execute(
        '''CREATE TABLE IF NOT EXISTS batches (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               product_id INTEGER NOT NULL,
               supplier_id INTEGER,
               batch_no TEXT,
               quantity INTEGER NOT NULL,
               expiry_date TEXT,
               cost_price REAL NOT NULL DEFAULT 0,
               created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
               FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
               FOREIGN KEY(supplier_id) REFERENCES suppliers(id) ON DELETE SET NULL
           );'''
    )

    # Sales and sale items
    cur.execute('''CREATE TABLE IF NOT EXISTS sales (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      total REAL NOT NULL,
                      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
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

    # Returns
    cur.execute('''CREATE TABLE IF NOT EXISTS returns (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      sale_item_id INTEGER NOT NULL,
                      quantity INTEGER NOT NULL,
                      reason TEXT,
                      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      FOREIGN KEY(sale_item_id) REFERENCES sale_items(id) ON DELETE CASCADE
                  );''')

    # seed users if empty
    cur.execute('SELECT COUNT(*) FROM users;')
    if cur.fetchone()[0] == 0:
        cur.executemany(
            'INSERT INTO users (username, password_hash, role) VALUES (?,?,?);',
            [
                ('admin', hash_pw('admin123'), 'admin'),
                ('cashier', hash_pw('cashier123'), 'cashier'),
            ]
        )

    con.commit()
    con.close()

# ---------------- DB Access ----------------
class DB:
    def __init__(self, path=DB_PATH):
        self.path = path

    def connect(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys = ON;')
        return con

    def query(self, sql, params=()):
        with self.connect() as con:
            cur = con.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def execute(self, sql, params=()):
        with self.connect() as con:
            cur = con.execute(sql, params)
            con.commit()
            return cur.lastrowid

# ---------------- Generic UI helpers ----------------
class FormDialog(tk.Toplevel):
    def __init__(self, master, title, fields, initial=None, on_submit=None):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.on_submit = on_submit
        self.result = None
        self.grab_set()
        self.transient(master)

        pad = 8
        frm = ttk.Frame(self)
        frm.pack(fill='both', expand=True, padx=pad, pady=pad)

        self.widgets = {}
        for i, f in enumerate(fields):
            ttk.Label(frm, text=f.get('label', f['key'])).grid(row=i, column=0, sticky='w', pady=4)
            wtype = f.get('widget', 'entry')
            if wtype == 'entry':
                w = ttk.Entry(frm)
                if initial and f['key'] in initial and initial[f['key']] is not None:
                    w.insert(0, str(initial[f['key']]))
            elif wtype == 'combobox':
                w = ttk.Combobox(frm, state='readonly', values=f.get('values', []))
                if initial and f['key'] in initial:
                    val = initial[f['key']]
                    try:
                        w.set(val)
                    except Exception:
                        pass
            elif wtype == 'spinbox':
                w = ttk.Spinbox(frm, from_=f.get('from', 0), to=f.get('to', 999999), increment=f.get('inc',1))
                if initial and f['key'] in initial and initial[f['key']] is not None:
                    w.set(str(initial[f['key']]))
            elif wtype == 'text':
                w = tk.Text(frm, height=f.get('height', 3), width=40)
                if initial and f['key'] in initial and initial[f['key']] is not None:
                    w.insert('1.0', str(initial[f['key']]))
            else:
                w = ttk.Entry(frm)
            w.grid(row=i, column=1, sticky='we', pady=4)
            self.widgets[f['key']] = (w, f)

        btns = ttk.Frame(frm)
        btns.grid(row=len(fields), column=0, columnspan=2, pady=(10,0))
        ttk.Button(btns, text='Save', command=self._save).pack(side='left', padx=6)
        ttk.Button(btns, text='Cancel', command=self.destroy).pack(side='left')

        self.bind('<Return>', lambda e: self._save())
        self.bind('<Escape>', lambda e: self.destroy())

    def _save(self):
        data = {}
        for key, (w, f) in self.widgets.items():
            wtype = f.get('widget', 'entry')
            if wtype in ('entry', 'combobox', 'spinbox'):
                data[key] = w.get().strip()
            elif wtype == 'text':
                data[key] = w.get('1.0', 'end').strip()
            else:
                data[key] = w.get().strip()
        self.result = data
        if self.on_submit:
            self.on_submit(data)
        self.destroy()

# ---------------- CRUD Base ----------------
class CRUDTab(ttk.Frame):
    def __init__(self, master, db: DB, columns, headers, title, role='admin'):
        super().__init__(master)
        self.db = db
        self.columns = columns
        self.headers = headers
        self.title = title
        self.role = role
        self._build()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill='x', padx=8, pady=8)
        ttk.Label(top, text=self.title, font=('Segoe UI', 12, 'bold')).pack(side='left')

        self.tree = ttk.Treeview(self, columns=self.columns, show='headings', height=14)
        vsb = ttk.Scrollbar(self, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)

        for i, col in enumerate(self.columns):
            self.tree.heading(col, text=self.headers[i])
            self.tree.column(col, width=120, anchor='w')

        self.tree.pack(side='left', fill='both', expand=True, padx=(8,0), pady=(0,8))
        vsb.pack(side='left', fill='y', pady=(0,8))

        btns = ttk.Frame(self)
        btns.pack(side='left', fill='y', padx=8, pady=(0,8))

        self.btn_add = ttk.Button(btns, text='Add', command=self.add_item)
        self.btn_edit = ttk.Button(btns, text='Edit', command=self.edit_item)
        self.btn_del = ttk.Button(btns, text='Delete', command=self.delete_item)

        self.btn_add.pack(fill='x', pady=4)
        self.btn_edit.pack(fill='x', pady=4)
        self.btn_del.pack(fill='x', pady=4)

        if self.role == 'cashier':
            self.btn_del.state(['disabled'])

        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for row in self.fetch_rows():
            values = [row.get(c) for c in self.columns]
            self.tree.insert('', 'end', iid=row.get('id'), values=values)

    def get_selected_id(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return int(sel[0])

    def add_item(self):
        pass

    def edit_item(self):
        rid = self.get_selected_id()
        if not rid:
            messagebox.showwarning('Select', 'Select a row to edit.')
            return
        self.open_edit_dialog(rid)

    def delete_item(self):
        rid = self.get_selected_id()
        if not rid:
            messagebox.showwarning('Select', 'Select a row to delete.')
            return
        if self.role != 'admin':
            messagebox.showerror('Permission', 'Only admin can delete.')
            return
        if messagebox.askyesno('Confirm', 'Delete selected record?'):
            self.perform_delete(rid)
            self.refresh()

    # Hooks to be implemented by subclasses
    def fetch_rows(self):
        return []

    def open_edit_dialog(self, rid: int):
        pass

    def perform_delete(self, rid: int):
        pass

# ---------------- Specific CRUD tabs (categories, manufacturers, suppliers, formulas, products, batches) ----------------
# (For brevity the logic is standard CRUD - see earlier versions; included below)

class CategoriesTab(CRUDTab):
    def __init__(self, master, db, role):
        super().__init__(master, db, columns=['id','name','notes'], headers=['ID','Name','Notes'], title='Categories', role=role)

    def fetch_rows(self):
        return self.db.query('SELECT id, name, notes FROM categories ORDER BY name;')

    def add_item(self):
        def save(data):
            if not data['name']:
                messagebox.showerror('Error', 'Name required')
                return
            try:
                self.db.execute('INSERT INTO categories(name,notes) VALUES(?,?);', (data['name'], data.get('notes','')))
                self.refresh()
            except sqlite3.IntegrityError:
                messagebox.showerror('Error', 'Category already exists')
        FormDialog(self, 'Add Category', [
            {'key':'name','label':'Name'},
            {'key':'notes','label':'Notes','widget':'text'},
        ], on_submit=save)

    def open_edit_dialog(self, rid):
        row = self.db.query('SELECT * FROM categories WHERE id=?;', (rid,))
        if not row: return
        data0 = row[0]
        def save(data):
            if not data['name']:
                messagebox.showerror('Error', 'Name required')
                return
            try:
                self.db.execute('UPDATE categories SET name=?, notes=? WHERE id=?;', (data['name'], data.get('notes',''), rid))
                self.refresh()
            except sqlite3.IntegrityError:
                messagebox.showerror('Error', 'Category name must be unique')
        FormDialog(self, 'Edit Category', [
            {'key':'name','label':'Name'},
            {'key':'notes','label':'Notes','widget':'text'},
        ], initial=data0, on_submit=save)

    def perform_delete(self, rid):
        self.db.execute('DELETE FROM categories WHERE id=?;', (rid,))

# (Manufacturers, Suppliers, Formulas classes omitted here for brevity in message; they are included in the file)
# Implementations are the same as prior full file and follow same CRUD patterns.

# To keep this code block runnable, include the remaining classes for manufacturers, suppliers, formulas, products and batches:

class ManufacturersTab(CRUDTab):
    def __init__(self, master, db, role):
        super().__init__(master, db, columns=['id','name','contact','notes'], headers=['ID','Name','Contact','Notes'], title='Manufacturers', role=role)

    def fetch_rows(self):
        return self.db.query('SELECT id, name, contact, notes FROM manufacturers ORDER BY name;')

    def add_item(self):
        def save(d):
            if not d['name']:
                messagebox.showerror('Error', 'Name required')
                return
            try:
                self.db.execute('INSERT INTO manufacturers(name,contact,notes) VALUES(?,?,?);', (d['name'], d.get('contact',''), d.get('notes','')))
                self.refresh()
            except sqlite3.IntegrityError:
                messagebox.showerror('Error', 'Manufacturer already exists')
        FormDialog(self, 'Add Manufacturer', [
            {'key':'name','label':'Name'},
            {'key':'contact','label':'Contact'},
            {'key':'notes','label':'Notes','widget':'text'},
        ], on_submit=save)

    def open_edit_dialog(self, rid):
        row = self.db.query('SELECT * FROM manufacturers WHERE id=?;', (rid,))
        if not row: return
        d0 = row[0]
        def save(d):
            if not d['name']:
                messagebox.showerror('Error', 'Name required')
                return
            try:
                self.db.execute('UPDATE manufacturers SET name=?, contact=?, notes=? WHERE id=?;', (d['name'], d.get('contact',''), d.get('notes',''), rid))
                self.refresh()
            except sqlite3.IntegrityError:
                messagebox.showerror('Error', 'Name must be unique')
        FormDialog(self, 'Edit Manufacturer', [
            {'key':'name','label':'Name'},
            {'key':'contact','label':'Contact'},
            {'key':'notes','label':'Notes','widget':'text'},
        ], initial=d0, on_submit=save)

    def perform_delete(self, rid):
        self.db.execute('DELETE FROM manufacturers WHERE id=?;', (rid,))

class SuppliersTab(CRUDTab):
    def __init__(self, master, db, role):
        super().__init__(master, db, columns=['id','name','phone','email','address'], headers=['ID','Name','Phone','Email','Address'], title='Suppliers', role=role)

    def fetch_rows(self):
        return self.db.query('SELECT id, name, phone, email, address FROM suppliers ORDER BY name;')

    def add_item(self):
        def save(d):
            if not d['name']:
                messagebox.showerror('Error', 'Name required')
                return
            try:
                self.db.execute('INSERT INTO suppliers(name,phone,email,address) VALUES(?,?,?,?);', (d['name'], d.get('phone',''), d.get('email',''), d.get('address','')))
                self.refresh()
            except sqlite3.IntegrityError:
                messagebox.showerror('Error', 'Supplier already exists')
        FormDialog(self, 'Add Supplier', [
            {'key':'name','label':'Name'},
            {'key':'phone','label':'Phone'},
            {'key':'email','label':'Email'},
            {'key':'address','label':'Address','widget':'text'},
        ], on_submit=save)

    def open_edit_dialog(self, rid):
        row = self.db.query('SELECT * FROM suppliers WHERE id=?;', (rid,))
        if not row: return
        d0 = row[0]
        def save(d):
            if not d['name']:
                messagebox.showerror('Error', 'Name required')
                return
            try:
                self.db.execute('UPDATE suppliers SET name=?, phone=?, email=?, address=? WHERE id=?;', (d['name'], d.get('phone',''), d.get('email',''), d.get('address',''), rid))
                self.refresh()
            except sqlite3.IntegrityError:
                messagebox.showerror('Error', 'Name must be unique')
        FormDialog(self, 'Edit Supplier', [
            {'key':'name','label':'Name'},
            {'key':'phone','label':'Phone'},
            {'key':'email','label':'Email'},
            {'key':'address','label':'Address','widget':'text'},
        ], initial=d0, on_submit=save)

    def perform_delete(self, rid):
        self.db.execute('DELETE FROM suppliers WHERE id=?;', (rid,))

class FormulasTab(CRUDTab):
    def __init__(self, master, db, role):
        super().__init__(master, db, columns=['id','name','composition'], headers=['ID','Name','Composition'], title='Formulas', role=role)

    def fetch_rows(self):
        return self.db.query('SELECT id, name, composition FROM formulas ORDER BY name;')

    def add_item(self):
        def save(d):
            if not d['name']:
                messagebox.showerror('Error', 'Name required')
                return
            try:
                self.db.execute('INSERT INTO formulas(name,composition) VALUES(?,?);', (d['name'], d.get('composition','')))
                self.refresh()
            except sqlite3.IntegrityError:
                messagebox.showerror('Error', 'Formula already exists')
        FormDialog(self, 'Add Formula', [
            {'key':'name','label':'Name'},
            {'key':'composition','label':'Composition','widget':'text'},
        ], on_submit=save)

    def open_edit_dialog(self, rid):
        row = self.db.query('SELECT * FROM formulas WHERE id=?;', (rid,))
        if not row: return
        d0 = row[0]
        def save(d):
            if not d['name']:
                messagebox.showerror('Error', 'Name required')
                return
            try:
                self.db.execute('UPDATE formulas SET name=?, composition=? WHERE id=?;', (d['name'], d.get('composition',''), rid))
                self.refresh()
            except sqlite3.IntegrityError:
                messagebox.showerror('Error', 'Name must be unique')
        FormDialog(self, 'Edit Formula', [
            {'key':'name','label':'Name'},
            {'key':'composition','label':'Composition','widget':'text'},
        ], initial=d0, on_submit=save)

    def perform_delete(self, rid):
        self.db.execute('DELETE FROM formulas WHERE id=?;', (rid,))

class ProductsTab(CRUDTab):
    def __init__(self, master, db, is_medical: bool, role):
        self.is_medical = is_medical
        title = 'Medical Products' if is_medical else 'Non-Medical Products'
        cols = ['id','name','sku','category','manufacturer','formula','unit','sale_price','stock']
        headers = ['ID','Name','SKU','Category','Manufacturer','Formula','Unit','Sale Price','Stock']
        super().__init__(master, db, columns=cols, headers=headers, title=title, role=role)

    def fetch_rows(self):
        rows = self.db.query(
            '''SELECT p.id, p.name, p.sku, p.unit, p.sale_price,
                      c.name AS category, m.name AS manufacturer, f.name AS formula,
                      COALESCE((SELECT SUM(quantity) FROM batches b WHERE b.product_id=p.id),0) AS stock
               FROM products p
               LEFT JOIN categories c ON p.category_id=c.id
               LEFT JOIN manufacturers m ON p.manufacturer_id=m.id
               LEFT JOIN formulas f ON p.formula_id=f.id
               WHERE p.is_medical=?
               ORDER BY p.name;''', (1 if self.is_medical else 0,))
        return rows

    def add_item(self):
        cats = [r['name'] for r in self.db.query('SELECT name FROM categories ORDER BY name;')]
        mans = [r['name'] for r in self.db.query('SELECT name FROM manufacturers ORDER BY name;')]
        forms = [''] + [r['name'] for r in self.db.query('SELECT name FROM formulas ORDER BY name;')]
        def save(d):
            if not d['name']:
                messagebox.showerror('Error', 'Name required')
                return
            cat_id = self._get_id_by_name('categories', d.get('category'))
            man_id = self._get_id_by_name('manufacturers', d.get('manufacturer'))
            form_id = self._get_id_by_name('formulas', d.get('formula'))
            price = float(d.get('sale_price') or 0)
            self.db.execute(
                '''INSERT INTO products(name, sku, is_medical, category_id, manufacturer_id, formula_id, unit, sale_price, notes)
                   VALUES(?,?,?,?,?,?,?,?,?);''',
                (d['name'], d.get('sku') or None, 1 if self.is_medical else 0, cat_id, man_id, form_id, d.get('unit') or '', price, d.get('notes',''))
            )
            self.refresh()
        FormDialog(self, f'Add {"Medical" if self.is_medical else "Non-Medical"} Product', [
            {'key':'name','label':'Name'},
            {'key':'sku','label':'SKU'},
            {'key':'category','label':'Category','widget':'combobox','values':cats},
            {'key':'manufacturer','label':'Manufacturer','widget':'combobox','values':mans},
            {'key':'formula','label':'Formula','widget':'combobox','values':forms},
            {'key':'unit','label':'Unit (e.g., box, strip, bottle)'},
            {'key':'sale_price','label':'Sale Price'},
            {'key':'notes','label':'Notes','widget':'text'},
        ], on_submit=save)

    def _get_id_by_name(self, table, name):
        if not name:
            return None
        row = self.db.query(f'SELECT id FROM {table} WHERE name=?;', (name,))
        return row[0]['id'] if row else None

    def open_edit_dialog(self, rid):
        row = self.db.query('''SELECT p.*, c.name AS category, m.name AS manufacturer, f.name AS formula
                               FROM products p
                               LEFT JOIN categories c ON p.category_id=c.id
                               LEFT JOIN manufacturers m ON p.manufacturer_id=m.id
                               LEFT JOIN formulas f ON p.formula_id=f.id
                               WHERE p.id=?;''', (rid,))
        if not row: return
        d0 = row[0]
        cats = [r['name'] for r in self.db.query('SELECT name FROM categories ORDER BY name;')]
        mans = [r['name'] for r in self.db.query('SELECT name FROM manufacturers ORDER BY name;')]
        forms = [''] + [r['name'] for r in self.db.query('SELECT name FROM formulas ORDER BY name;')]
        def save(d):
            if not d['name']:
                messagebox.showerror('Error', 'Name required')
                return
            cat_id = self._get_id_by_name('categories', d.get('category'))
            man_id = self._get_id_by_name('manufacturers', d.get('manufacturer'))
            form_id = self._get_id_by_name('formulas', d.get('formula'))
            price = float(d.get('sale_price') or 0)
            self.db.execute('''UPDATE products SET name=?, sku=?, category_id=?, manufacturer_id=?, formula_id=?, unit=?, sale_price=?, notes=? WHERE id=?;''',
                            (d['name'], d.get('sku') or None, cat_id, man_id, form_id, d.get('unit') or '', price, d.get('notes',''), rid))
            self.refresh()
        FormDialog(self, 'Edit Product', [
            {'key':'name','label':'Name'},
            {'key':'sku','label':'SKU'},
            {'key':'category','label':'Category','widget':'combobox','values':cats},
            {'key':'manufacturer','label':'Manufacturer','widget':'combobox','values':mans},
            {'key':'formula','label':'Formula','widget':'combobox','values':forms},
            {'key':'unit','label':'Unit'},
            {'key':'sale_price','label':'Sale Price'},
            {'key':'notes','label':'Notes','widget':'text'},
        ], initial=d0, on_submit=save)

    def perform_delete(self, rid):
        self.db.execute('DELETE FROM products WHERE id=?;', (rid,))

class BatchesTab(CRUDTab):
    def __init__(self, master, db, role):
        cols = ['id','product','supplier','batch_no','quantity','expiry_date','cost_price','created_at']
        headers = ['ID','Product','Supplier','Batch No','Qty','Expiry','Cost Price','Created']
        super().__init__(master, db, columns=cols, headers=headers, title='Batches (Supplies)', role=role)

    def fetch_rows(self):
        return self.db.query(
            '''SELECT b.id, p.name AS product, s.name AS supplier, b.batch_no, b.quantity, b.expiry_date, b.cost_price, b.created_at
               FROM batches b
               LEFT JOIN products p ON b.product_id=p.id
               LEFT JOIN suppliers s ON b.supplier_id=s.id
               ORDER BY b.id DESC;'''
        )

    def add_item(self):
        products = [r['name'] for r in self.db.query('SELECT name FROM products ORDER BY name;')]
        suppliers = [''] + [r['name'] for r in self.db.query('SELECT name FROM suppliers ORDER BY name;')]
        def save(d):
            if not d['product']:
                messagebox.showerror('Error', 'Product required')
                return
            pid = self._get_id('products', d['product'])
            sid = self._get_id('suppliers', d.get('supplier'))
            qty = int(d.get('quantity') or 0)
            if qty <= 0:
                messagebox.showerror('Error', 'Quantity must be > 0')
                return
            expiry = d.get('expiry_date') or None
            cost = float(d.get('cost_price') or 0)
            self.db.execute('''INSERT INTO batches(product_id, supplier_id, batch_no, quantity, expiry_date, cost_price, created_at)
                               VALUES(?,?,?,?,?,?,?);''',
                            (pid, sid, d.get('batch_no') or '', qty, expiry, cost, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            self.refresh()
        FormDialog(self, 'Add Batch / Supply', [
            {'key':'product','label':'Product','widget':'combobox','values':products},
            {'key':'supplier','label':'Supplier','widget':'combobox','values':suppliers},
            {'key':'batch_no','label':'Batch No'},
            {'key':'quantity','label':'Quantity','widget':'spinbox','from':0,'to':100000,'inc':1},
            {'key':'expiry_date','label':'Expiry (YYYY-MM-DD)'},
            {'key':'cost_price','label':'Cost Price'},
        ], on_submit=save)

    def _get_id(self, table, name):
        if not name:
            return None
        r = self.db.query(f'SELECT id FROM {table} WHERE name=?;', (name,))
        return r[0]['id'] if r else None

    def open_edit_dialog(self, rid):
        row = self.db.query('''SELECT b.*, p.name AS product, s.name AS supplier
                               FROM batches b
                               LEFT JOIN products p ON b.product_id=p.id
                               LEFT JOIN suppliers s ON b.supplier_id=s.id
                               WHERE b.id=?;''', (rid,))
        if not row: return
        d0 = row[0]
        products = [r['name'] for r in self.db.query('SELECT name FROM products ORDER BY name;')]
        suppliers = [''] + [r['name'] for r in self.db.query('SELECT name FROM suppliers ORDER BY name;')]
        def save(d):
            pid = self._get_id('products', d.get('product') or d0.get('product'))
            sid = self._get_id('suppliers', d.get('supplier'))
            qty = int(d.get('quantity') or 0)
            if qty <= 0:
                messagebox.showerror('Error', 'Quantity must be > 0')
                return
            expiry = d.get('expiry_date') or None
            cost = float(d.get('cost_price') or 0)
            self.db.execute('''UPDATE batches SET product_id=?, supplier_id=?, batch_no=?, quantity=?, expiry_date=?, cost_price=? WHERE id=?;''',
                            (pid, sid, d.get('batch_no') or '', qty, expiry, cost, rid))
            self.refresh()
        FormDialog(self, 'Edit Batch / Supply', [
            {'key':'product','label':'Product','widget':'combobox','values':products},
            {'key':'supplier','label':'Supplier','widget':'combobox','values':suppliers},
            {'key':'batch_no','label':'Batch No'},
            {'key':'quantity','label':'Quantity','widget':'spinbox','from':0,'to':100000,'inc':1},
            {'key':'expiry_date','label':'Expiry (YYYY-MM-DD)'},
            {'key':'cost_price','label':'Cost Price'},
        ], initial=d0, on_submit=save)

    def perform_delete(self, rid):
        self.db.execute('DELETE FROM batches WHERE id=?;', (rid,))

# ---------------- Login and Main Frames ----------------
class LoginFrame(ttk.Frame):
    def __init__(self, master, on_login):
        super().__init__(master)
        self.on_login = on_login
        self.db = DB()
        self._build()

    def _build(self):
        card = ttk.Frame(self, padding=20)
        card.pack(expand=True)
        ttk.Label(card, text='Pharmacy Login', font=('Segoe UI', 16, 'bold')).grid(row=0, column=0, columnspan=2, pady=(0,10))
        ttk.Label(card, text='Username').grid(row=1, column=0, sticky='e', padx=6, pady=6)
        ttk.Label(card, text='Password').grid(row=2, column=0, sticky='e', padx=6, pady=6)
        self.user_e = ttk.Entry(card)
        self.pw_e = ttk.Entry(card, show='•')
        self.user_e.grid(row=1, column=1, pady=6)
        self.pw_e.grid(row=2, column=1, pady=6)
        ttk.Button(card, text='Login', command=self.try_login).grid(row=3, column=0, columnspan=2, pady=(10,0))
        self.user_e.focus_set()
        self.bind_all('<Return>', lambda e: self.try_login())

    def try_login(self):
        u = self.user_e.get().strip()
        p = self.pw_e.get().strip()
        if not u or not p:
            messagebox.showerror('Error', 'Enter username and password')
            return
        row = self.db.query('SELECT * FROM users WHERE username=?;', (u,))
        if not row or row[0]['password_hash'] != hash_pw(p):
            messagebox.showerror('Error', 'Invalid credentials')
            return
        self.on_login({'id': row[0]['id'], 'username': u, 'role': row[0]['role']})

class InventoryFrame(ttk.Frame):
    def __init__(self, master, user):
        super().__init__(master)
        self.user = user
        self.db = DB()
        self._build()

    def _build(self):
        header = ttk.Frame(self)
        header.pack(fill='x', padx=10, pady=10)
        ttk.Label(header, text='Inventory', font=('Segoe UI', 14, 'bold')).pack(side='left')
        ttk.Label(header, text=f"Logged in as: {self.user['username']} ({self.user['role']})").pack(side='right')

        nb = ttk.Notebook(self)
        nb.pack(fill='both', expand=True, padx=10, pady=10)

        role = self.user['role']
        self.tab_med = ProductsTab(nb, self.db, is_medical=True, role=role)
        self.tab_non = ProductsTab(nb, self.db, is_medical=False, role=role)
        self.tab_sup = SuppliersTab(nb, self.db, role=role)
        self.tab_man = ManufacturersTab(nb, self.db, role=role)
        self.tab_cat = CategoriesTab(nb, self.db, role=role)
        self.tab_for = FormulasTab(nb, self.db, role=role)
        self.tab_bat = BatchesTab(nb, self.db, role=role)

        nb.add(self.tab_med, text='Medical Products')
        nb.add(self.tab_non, text='Non-Medical Products')
        nb.add(self.tab_sup, text='Suppliers')
        nb.add(self.tab_man, text='Manufacturers')
        nb.add(self.tab_cat, text='Categories')
        nb.add(self.tab_for, text='Formulas')
        nb.add(self.tab_bat, text='Batches / Supply')

# ---------------- POS Tabs (NewSale, SaleHistory, Return, ReturnHistory, SalesReport) ----------------
class NewSaleTab(ttk.Frame):
    def __init__(self, master, db, user):
        super().__init__(master)
        self.db, self.user = db, user
        self.cart = []
        self.selected_product = None
        self._build()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill='x', padx=10, pady=5)

        ttk.Label(top, text="Search product by name or ID").pack(side='left')
        self.search_e = ttk.Entry(top, width=40)
        self.search_e.pack(side='left', padx=5)
        self.search_e.bind("<KeyRelease>", self.update_suggestions)

        self.suggestions = tk.Listbox(self, height=5)
        self.suggestions.pack(fill='x', padx=10)
        self.suggestions.bind("<Double-Button-1>", self._on_suggestion_double)

        ttk.Label(top, text="Qty").pack(side='left', padx=(10,0))
        self.qty_e = ttk.Entry(top, width=5)
        self.qty_e.pack(side='left', padx=5)
        ttk.Button(top, text="Add", command=self.add_to_cart).pack(side='left', padx=5)

        self.tree = ttk.Treeview(self, columns=['product','qty','price','subtotal'], show='headings')
        for c in ['product','qty','price','subtotal']:
            self.tree.heading(c, text=c.capitalize())
        self.tree.pack(fill='both', expand=True, padx=10, pady=5)

        self.lbl_total = ttk.Label(self, text="Total: 0.00", font=('Segoe UI', 12, 'bold'))
        self.lbl_total.pack(anchor='e', padx=10)
        ttk.Button(self, text="Checkout", command=self.checkout).pack(anchor='e', padx=10, pady=5)

    def update_suggestions(self, event=None):
        term = self.search_e.get().strip()
        self.suggestions.delete(0, 'end')
        if not term:
            return
        rows = self.db.query("SELECT id, name, sale_price FROM products WHERE name LIKE ? OR CAST(id AS TEXT) LIKE ? ORDER BY name LIMIT 50;", (f"%{term}%", f"%{term}%"))
        for r in rows:
            self.suggestions.insert('end', f"{r['id']} - {r['name']} - {r['sale_price']}")

    def _on_suggestion_double(self, event=None):
        sel = self.suggestions.curselection()
        if not sel:
            return
        val = self.suggestions.get(sel[0])
        pid = int(val.split(' - ')[0])
        row = self.db.query("SELECT * FROM products WHERE id=?;", (pid,))
        if row:
            self.selected_product = row[0]
            self.search_e.delete(0, 'end')
            self.search_e.insert(0, f"{self.selected_product['name']}")

    def add_to_cart(self):
        term = self.search_e.get().strip()
        qty = int(self.qty_e.get() or 0)
        prod = None
        if term.isdigit():
            rows = self.db.query("SELECT * FROM products WHERE id=?;", (int(term),))
            if rows: prod = rows[0]
        if not prod:
            rows = self.db.query("SELECT * FROM products WHERE name=? LIMIT 1;", (term,))
            if rows: prod = rows[0]
        if not prod:
            messagebox.showwarning("Not found", "Product not found. Use search box and double-click a suggestion.")
            return
        if qty <= 0:
            messagebox.showwarning("Invalid qty", "Enter quantity > 0")
            return
        self.cart.append({'id': prod['id'], 'name': prod['name'], 'qty': qty, 'price': prod['sale_price'], 'subtotal': prod['sale_price']*qty})
        self.search_e.delete(0, 'end'); self.qty_e.delete(0, 'end'); self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        total = 0
        for item in self.cart:
            self.tree.insert('', 'end', values=[item['name'], item['qty'], item['price'], item['subtotal']])
            total += item['subtotal']
        self.lbl_total.config(text=f"Total: {total:.2f}")

    def checkout(self):
        if not self.cart:
            messagebox.showwarning("Empty", "Cart is empty")
            return
        total = sum(i['subtotal'] for i in self.cart)
        sid = self.db.execute("INSERT INTO sales(user_id,total,created_at) VALUES(?,?,?);", (self.user['id'], total, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        for i in self.cart:
            self.db.execute("INSERT INTO sale_items(sale_id,product_id,quantity,price) VALUES(?,?,?,?);", (sid, i['id'], i['qty'], i['price']))
            # FIFO deduction
            qty_needed = i['qty']
            batches = self.db.query("SELECT id, quantity FROM batches WHERE product_id=? AND quantity>0 ORDER BY created_at ASC;", (i['id'],))
            for b in batches:
                if qty_needed <= 0: break
                take = min(qty_needed, b['quantity'])
                self.db.execute("UPDATE batches SET quantity=quantity-? WHERE id=?;", (take, b['id']))
                qty_needed -= take
            if qty_needed > 0:
                messagebox.showwarning("Stock Warning", f"Product {i['name']} had insufficient stock. Short by {qty_needed}.")
        # ask to print receipt
        if messagebox.askyesno("Print Receipt", "Do you want to print a receipt?"):
            self.generate_receipt(sid, total)
        messagebox.showinfo("Sale Complete", f"Sale #{sid} completed.")
        self.cart.clear(); self.refresh()

    def generate_receipt(self, sale_id, total):
        if not REPORTLAB:
            messagebox.showerror("Missing Package", "reportlab not installed; cannot generate PDF.")
            return
        items = self.db.query("SELECT si.quantity, si.price, p.name FROM sale_items si JOIN products p ON si.product_id=p.id WHERE si.sale_id=?;", (sale_id,))
        folder = os.path.join(os.path.dirname(__file__), "receipts"); os.makedirs(folder, exist_ok=True)
        filepath = os.path.join(folder, f"receipt_{sale_id}.pdf")
        c = pdf_canvas.Canvas(filepath, pagesize=A4); width, height = A4
        y = height - 60
        c.setFont("Helvetica-Bold", 14); c.drawString(50, y, "Pharmacy Receipt"); y -= 25
        c.setFont("Helvetica", 10); c.drawString(50, y, f"Sale ID: {sale_id}"); c.drawString(250, y, f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"); y -= 20
        c.drawString(50, y, f"Cashier: {self.user['username']}"); y -= 25
        c.setFont("Helvetica-Bold", 10); c.drawString(50, y, "Product"); c.drawString(250, y, "Qty"); c.drawString(300, y, "Price"); c.drawString(370, y, "Subtotal"); y -= 15
        c.setFont("Helvetica", 10)
        for it in items:
            c.drawString(50, y, str(it['name']))
            c.drawString(250, y, str(it['quantity']))
            c.drawString(300, y, f"{it['price']:.2f}")
            c.drawString(370, y, f"{it['price']*it['quantity']:.2f}")
            y -= 15
            if y < 80:
                c.showPage(); y = height - 60
        c.setFont("Helvetica-Bold", 12); c.drawString(50, y-20, f"Total: {total:.2f}")
        c.save()
        messagebox.showinfo("Receipt Saved", f"Receipt saved to {filepath}")
        try:
            os.startfile(filepath)
        except Exception:
            pass

class SaleHistoryTab(ttk.Frame):
    def __init__(self, master, db):
        super().__init__(master)
        self.db = db
        self._build()

    def _build(self):
        top = ttk.Frame(self); top.pack(fill='x', pady=5)
        self.tree = ttk.Treeview(self, columns=['id','user','total','created'], show='headings')
        for c in ['id','user','total','created']:
            self.tree.heading(c, text=c.capitalize())
        self.tree.pack(fill='both', expand=True)
        btns = ttk.Frame(self); btns.pack(fill='x', pady=6)
        ttk.Button(btns, text="Refresh", command=self.refresh).pack(side='left', padx=6)
        ttk.Button(btns, text="Print Receipt", command=self.print_receipt).pack(side='left', padx=6)
        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        rows = self.db.query("SELECT s.id,u.username AS user,s.total,s.created_at as created FROM sales s LEFT JOIN users u ON s.user_id=u.id ORDER BY s.id DESC;")
        for r in rows:
            self.tree.insert('', 'end', values=[r['id'], r['user'], r['total'], r['created']])

    def get_selected_sale(self):
        sel = self.tree.selection()
        if not sel: return None
        vals = self.tree.item(sel[0])['values']
        return {'id': vals[0], 'user': vals[1], 'total': vals[2], 'created': vals[3]}

    def print_receipt(self):
        sale = self.get_selected_sale()
        if not sale:
            messagebox.showwarning("Select Sale", "Please select a sale to print.")
            return
        if not REPORTLAB:
            messagebox.showerror("Missing Package", "reportlab is required to generate PDF receipts.")
            return
        items = self.db.query("SELECT si.quantity, si.price, p.name FROM sale_items si JOIN products p ON si.product_id=p.id WHERE si.sale_id=?;", (sale['id'],))
        folder = os.path.join(os.path.dirname(__file__), "receipts"); os.makedirs(folder, exist_ok=True)
        filepath = os.path.join(folder, f"receipt_{sale['id']}.pdf")
        c = pdf_canvas.Canvas(filepath, pagesize=A4); width, height = A4
        y = height - 60
        c.setFont("Helvetica-Bold", 14); c.drawString(50, y, "Pharmacy Receipt"); y -= 25
        c.setFont("Helvetica", 10); c.drawString(50, y, f"Sale ID: {sale['id']}"); c.drawString(250, y, f"Date: {sale['created']}"); y -= 20
        c.drawString(50, y, f"Cashier: {sale['user']}"); y -= 25
        c.setFont("Helvetica-Bold", 10); c.drawString(50, y, "Product"); c.drawString(250, y, "Qty"); c.drawString(300, y, "Price"); c.drawString(370, y, "Subtotal"); y -= 15
        c.setFont("Helvetica", 10)
        for it in items:
            c.drawString(50, y, str(it['name'])); c.drawString(250, y, str(it['quantity'])); c.drawString(300, y, f"{it['price']:.2f}"); c.drawString(370, y, f"{it['price']*it['quantity']:.2f}"); y -= 15
            if y < 80:
                c.showPage(); y = height - 60
        c.setFont("Helvetica-Bold", 12); c.drawString(50, y-20, f"Total: {sale['total']:.2f}"); c.save()
        messagebox.showinfo("Receipt Saved", f"Receipt saved to {filepath}")
        try:
            os.startfile(filepath)
        except Exception:
            pass

class ReturnTab(ttk.Frame):
    def __init__(self, master, db):
        super().__init__(master)
        self.db = db
        self._build()

    def _build(self):
        top = ttk.Frame(self); top.pack(fill='x', pady=5)
        ttk.Label(top, text="Sale ID").pack(side='left')
        self.sale_e = ttk.Entry(top, width=8); self.sale_e.pack(side='left', padx=5)
        ttk.Button(top, text="Load", command=self.load_sale).pack(side='left', padx=5)
        self.tree = ttk.Treeview(self, columns=['id','product','qty','price','product_id'], show='headings')
        for c in ['id','product','qty','price','product_id']:
            self.tree.heading(c, text=c.capitalize())
        self.tree.pack(fill='both', expand=True, padx=10, pady=5)

        frm = ttk.Frame(self); frm.pack(fill='x', padx=10, pady=5)
        ttk.Label(frm, text="Return Quantity").grid(row=0, column=0, sticky='w')
        self.qty_e = ttk.Entry(frm, width=10); self.qty_e.grid(row=0, column=1, sticky='w', padx=6)
        ttk.Label(frm, text="Reason for Return").grid(row=1, column=0, sticky='w', pady=(6,0))
        self.reason_e = ttk.Entry(frm, width=40); self.reason_e.grid(row=1, column=1, sticky='w', padx=6, pady=(6,0))
        ttk.Button(self, text="Process Return", command=self.process_return).pack(pady=6)

    def load_sale(self):
        sid = self.sale_e.get().strip()
        if not sid:
            messagebox.showwarning("Input", "Enter sale id to load items")
            return
        rows = self.db.query("SELECT si.id, p.name as product, si.quantity as qty, si.price, p.id as product_id FROM sale_items si JOIN products p ON si.product_id=p.id WHERE si.sale_id=?;", (sid,))
        self.tree.delete(*self.tree.get_children())
        for r in rows:
            self.tree.insert('', 'end', values=[r['id'], r['product'], r['qty'], r['price'], r['product_id']])

    def process_return(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Select", "Select the sold item to return")
            return
        vals = self.tree.item(sel[0])['values']
        sale_item_id = vals[0]; product_id = vals[4]
        try:
            qty = int(self.qty_e.get() or 0)
        except:
            messagebox.showwarning("Input", "Enter valid return quantity")
            return
        reason = self.reason_e.get().strip()
        if qty <= 0:
            messagebox.showwarning("Input", "Return quantity must be > 0")
            return
        # record return
        self.db.execute("INSERT INTO returns(sale_item_id,quantity,reason,created_at) VALUES(?,?,?,?);", (sale_item_id, qty, reason, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        # restock into most recent batch (LIFO)
        batch = self.db.query("SELECT id FROM batches WHERE product_id=? ORDER BY created_at DESC LIMIT 1;", (product_id,))
        if batch:
            self.db.execute("UPDATE batches SET quantity=quantity+? WHERE id=?;", (qty, batch[0]['id']))
        else:
            self.db.execute("INSERT INTO batches(product_id,batch_no,quantity,cost_price,created_at) VALUES(?,?,?,?,?);", (product_id, 'RETURN', qty, 0.0, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        messagebox.showinfo("Done", "Return processed and stock updated.")

class ReturnHistoryTab(ttk.Frame):
    def __init__(self, master, db):
        super().__init__(master)
        self.db = db
        self._build()

    def _build(self):
        self.tree = ttk.Treeview(self, columns=['id','sale_item','qty','reason','created'], show='headings')
        for c in ['id','sale_item','qty','reason','created']:
            self.tree.heading(c, text=c.capitalize())
        self.tree.pack(fill='both', expand=True)
        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        rows = self.db.query("SELECT r.id, r.sale_item_id as sale_item, r.quantity as qty, r.reason, r.created_at as created FROM returns r ORDER BY r.id DESC;")
        for r in rows:
            self.tree.insert('', 'end', values=[r['id'], r['sale_item'], r['qty'], r['reason'], r['created']])

class SalesReportTab(ttk.Frame):
    def __init__(self, master, db):
        super().__init__(master)
        self.db = db
        self._build()

    def _build(self):
        top = ttk.Frame(self); top.pack(fill='x', pady=6)
        ttk.Label(top, text="From (YYYY-MM-DD)").pack(side='left')
        self.from_e = ttk.Entry(top, width=12); self.from_e.pack(side='left', padx=6)
        ttk.Label(top, text="To").pack(side='left'); self.to_e = ttk.Entry(top, width=12); self.to_e.pack(side='left', padx=6)
        ttk.Button(top, text="Generate Report", command=self.refresh).pack(side='left', padx=6)
        ttk.Button(top, text="Export PDF (detailed)", command=self.export_pdf).pack(side='left', padx=6)

        self.tree = ttk.Treeview(self, columns=['date','product','qty','total'], show='headings')
        for c in ['date','product','qty','total']:
            self.tree.heading(c, text=c.capitalize())
        self.tree.pack(fill='both', expand=True, padx=10, pady=6)

        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        from_date = self.from_e.get().strip()
        to_date = self.to_e.get().strip()
        params = []
        date_clause = ""
        if from_date and to_date:
            date_clause = "AND s.created_at BETWEEN ? AND ?"
            params.extend([from_date + " 00:00:00", to_date + " 23:59:59"])
        elif from_date:
            date_clause = "AND s.created_at >= ?"; params.append(from_date + " 00:00:00")
        elif to_date:
            date_clause = "AND s.created_at <= ?"; params.append(to_date + " 23:59:59")

        sql = f"""
            SELECT substr(s.created_at,1,10) as date, p.name as product, SUM(si.quantity) as qty, SUM(si.quantity*si.price) as total
            FROM sales s
            JOIN sale_items si ON si.sale_id = s.id
            JOIN products p ON p.id = si.product_id
            WHERE 1=1 {date_clause}
            GROUP BY date, p.name
            ORDER BY date DESC;
        """
        rows = self.db.query(sql, tuple(params))
        for r in rows:
            self.tree.insert('', 'end', values=[r['date'], r['product'], r['qty'], r['total']])

    def export_pdf(self):
        if not REPORTLAB:
            messagebox.showerror("Missing Package", "reportlab required for PDF export")
            return
        from_date = self.from_e.get().strip(); to_date = self.to_e.get().strip()
        params = []
        date_clause = ""
        if from_date and to_date:
            date_clause = "AND s.created_at BETWEEN ? AND ?"
            params.extend([from_date + " 00:00:00", to_date + " 23:59:59"])
            title = f"Sales Report {from_date} to {to_date}"
        elif from_date:
            date_clause = "AND s.created_at >= ?"; params.append(from_date + " 00:00:00"); title = f"Sales Report from {from_date}"
        elif to_date:
            date_clause = "AND s.created_at <= ?"; params.append(to_date + " 23:59:59"); title = f"Sales Report to {to_date}"
        else:
            title = "Sales Report (All Time)"

        sql = f"""
            SELECT substr(s.created_at,1,10) as date, p.name as product, SUM(si.quantity) as qty, SUM(si.quantity*si.price) as total
            FROM sales s
            JOIN sale_items si ON si.sale_id = s.id
            JOIN products p ON p.id = si.product_id
            WHERE 1=1 {date_clause}
            GROUP BY date, p.name
            ORDER BY date DESC;
        """
        rows = self.db.query(sql, tuple(params))

        folder = os.path.join(os.path.dirname(__file__), "reports"); os.makedirs(folder, exist_ok=True)
        filepath = os.path.join(folder, f"sales_report_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf")
        c = pdf_canvas.Canvas(filepath, pagesize=A4); width, height = A4
        y = height - 60
        c.setFont("Helvetica-Bold", 14); c.drawString(50, y, title); y -= 25
        c.setFont("Helvetica", 10)
        c.drawString(50, y, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"); y -= 20
        c.setFont("Helvetica-Bold", 10); c.drawString(50, y, "Date"); c.drawString(140, y, "Product"); c.drawString(380, y, "Qty"); c.drawString(430, y, "Total"); y -= 15
        c.setFont("Helvetica", 10)
        for r in rows:
            c.drawString(50, y, str(r['date'])[:10])
            c.drawString(140, y, str(r['product'])[:28])
            c.drawString(380, y, str(r['qty']))
            c.drawString(430, y, f"{r['total']:.2f}")
            y -= 15
            if y < 80:
                c.showPage(); y = height - 60
        c.save()
        messagebox.showinfo("Report Saved", f"Saved to {filepath}")
        try:
            os.startfile(filepath)
        except Exception:
            pass

# ---------------- POS Frame wrapper ----------------
class POSFrame(ttk.Frame):
    def __init__(self, master, user):
        super().__init__(master)
        self.user = user
        self.db = DB()
        self._build()

    def _build(self):
        header = ttk.Frame(self)
        header.pack(fill='x', padx=10, pady=10)
        ttk.Label(header, text='Point of Sale', font=('Segoe UI', 14, 'bold')).pack(side='left')
        ttk.Label(header, text=f"Cashier: {self.user['username']}").pack(side='right')

        nb = ttk.Notebook(self)
        nb.pack(fill='both', expand=True, padx=10, pady=10)

        self.tab_new = NewSaleTab(nb, self.db, self.user)
        self.tab_hist = SaleHistoryTab(nb, self.db)
        self.tab_ret = ReturnTab(nb, self.db)
        self.tab_ret_hist = ReturnHistoryTab(nb, self.db)
        self.tab_report = SalesReportTab(nb, self.db)

        nb.add(self.tab_new, text='New Sale')
        nb.add(self.tab_hist, text='Sale History')
        nb.add(self.tab_ret, text='Return Item')
        nb.add(self.tab_ret_hist, text='Return History')
        nb.add(self.tab_report, text='Sales Report')

# ---------------- App ----------------
class App:
    def __init__(self):
        ensure_db()
        self.root = tb.Window(themename='cosmo') if tb else tk.Tk()
        self.root.title('Pharmacy Management System')
        self.root.geometry('1150x750')

        self.container = ttk.Frame(self.root)
        self.container.pack(fill='both', expand=True)

        self.show_login()

    def clear(self):
        for w in self.container.winfo_children():
            w.destroy()

    def show_login(self):
        self.clear()
        lf = LoginFrame(self.container, on_login=self.on_login)
        lf.pack(fill='both', expand=True)

    def on_login(self, user):
        self.clear()
        outer = ttk.Notebook(self.container)
        outer.pack(fill='both', expand=True)
        inv = InventoryFrame(outer, user)
        pos = POSFrame(outer, user)
        outer.add(inv, text='Inventory')
        outer.add(pos, text='POS')

    def run(self):
        self.root.mainloop()

if __name__ == '__main__':
    App().run()

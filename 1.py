# pharmacy_app.py
# Advanced Tkinter + ttkbootstrap Pharmacy Management System
# Role-based login (Admin, Cashier), Inventory with sub-tabs and full CRUD
# SQLite database, modern UI

import os
import sqlite3
from datetime import datetime
import hashlib
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk

try:
    import ttkbootstrap as tb
except ImportError:
    tb = None  # App will still run with classic ttk, but recommend installing ttkbootstrap

DB_PATH = os.path.join(os.path.dirname(__file__), 'pharmacy.db')

# ----------------------------- Utilities -----------------------------

def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode('utf-8')).hexdigest()


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
               is_medical INTEGER NOT NULL DEFAULT 1, -- 1 medical, 0 non-medical
               category_id INTEGER,
               manufacturer_id INTEGER,
               formula_id INTEGER,
               unit TEXT,
               sale_price REAL NOT NULL DEFAULT 0,
               notes TEXT,
               FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE SET NULL,
               FOREIGN KEY(manufacturer_id) REFERENCES manufacturers(id) ON DELETE SET NULL,
               FOREIGN KEY(formula_id) REFERENCES formulas(id) ON DELETE SET NULL
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


# ----------------------------- Data Access Layer -----------------------------
class DB:
    def __init__(self, path=DB_PATH):
        self.path = path

    def connect(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys = ON;')
        return con

    # Generic helpers
    def query(self, sql, params=()):
        with self.connect() as con:
            cur = con.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]

    def execute(self, sql, params=()):
        with self.connect() as con:
            cur = con.execute(sql, params)
            con.commit()
            return cur.lastrowid


# ----------------------------- UI Components -----------------------------
class FormDialog(tk.Toplevel):
    """Generic key->widget form dialog. fields: list of dicts: {key,label,widget,options,...}"""
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


class CRUDTab(ttk.Frame):
    """Base class for simple CRUD tabs with a Treeview and buttons."""
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
            # default restriction: view & add batches/products; no deletes
            self.btn_del.state(['disabled'])

        self.refresh()

    # Methods subclasses should override or use
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

    # Hooks
    def fetch_rows(self):
        return []

    def open_edit_dialog(self, rid: int):
        pass

    def perform_delete(self, rid: int):
        pass


# ----------------------------- Specific Tabs -----------------------------
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
            # lookup ids
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


# ----------------------------- Main App -----------------------------
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
        # Sub-tabs
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


class App:
    def __init__(self):
        ensure_db()
        self.root = tb.Window(themename='cosmo') if tb else tk.Tk()
        self.root.title('Pharmacy Management System')
        self.root.geometry('1050x650')

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
        # After login, show an outer notebook with Inventory tab (future: add Reports, Billing, etc.)
        outer = ttk.Notebook(self.container)
        outer.pack(fill='both', expand=True)
        inv = InventoryFrame(outer, user)
        outer.add(inv, text='Inventory')

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    App().run()

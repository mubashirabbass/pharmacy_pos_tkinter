
import os, sqlite3, hashlib, tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'pharmacy.db')
INVOICES_DIR = os.path.join(os.path.dirname(__file__), 'invoices')
os.makedirs(INVOICES_DIR, exist_ok=True)

def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()

def ensure_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute('PRAGMA foreign_keys = ON;')
    cur.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT, role TEXT);''')
    cur.execute('''CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY, name TEXT, sku TEXT, is_medical INTEGER DEFAULT 1, sale_price REAL DEFAULT 0, stock INTEGER DEFAULT 0);''')
    cur.execute('''CREATE TABLE IF NOT EXISTS suppliers (id INTEGER PRIMARY KEY, name TEXT UNIQUE, phone TEXT, email TEXT, address TEXT);''')
    cur.execute('''CREATE TABLE IF NOT EXISTS batches (id INTEGER PRIMARY KEY, product_id INTEGER, supplier_id INTEGER, batch_no TEXT, quantity INTEGER, expiry_date TEXT, created_at TEXT);''')
    cur.execute('''CREATE TABLE IF NOT EXISTS sales (id INTEGER PRIMARY KEY, invoice_no TEXT UNIQUE, sale_date TEXT, cashier_id INTEGER, subtotal REAL, total REAL);''')
    cur.execute('''CREATE TABLE IF NOT EXISTS sale_items (id INTEGER PRIMARY KEY, sale_id INTEGER, product_id INTEGER, quantity INTEGER, unit_price REAL, line_total REAL);''')
    cur.execute('SELECT COUNT(*) FROM users;')
    if cur.fetchone()[0]==0:
        cur.execute('INSERT INTO users(username,password_hash,role) VALUES (?,?,?);', ('admin', hash_pw('admin123'), 'admin'))
        cur.execute('INSERT INTO users(username,password_hash,role) VALUES (?,?,?);', ('cashier', hash_pw('cashier123'), 'cashier'))
    con.commit(); con.close()

class DB:
    def __init__(self,path=DB_PATH): self.path=path
    def connect(self): con=sqlite3.connect(self.path); con.row_factory=sqlite3.Row; return con
    def query(self,sql,params=()):
        with self.connect() as c: cur=c.execute(sql,params); return [dict(r) for r in cur.fetchall()]
    def execute(self,sql,params=()):
        with self.connect() as c: cur=c.execute(sql,params); c.commit(); return cur.lastrowid

class LoginFrame(ttk.Frame):
    def __init__(self,master,on_login): super().__init__(master); self.on_login=on_login; self.db=DB(); self._build()
    def _build(self):
        frm=ttk.Frame(self,padding=20); frm.pack(expand=True)
        ttk.Label(frm,text='Login',font=('Segoe UI',16,'bold')).grid(row=0,column=0,columnspan=2,pady=10)
        ttk.Label(frm,text='Username').grid(row=1,column=0); ttk.Label(frm,text='Password').grid(row=2,column=0)
        self.u=ttk.Entry(frm); self.p=ttk.Entry(frm,show='*'); self.u.grid(row=1,column=1); self.p.grid(row=2,column=1)
        ttk.Button(frm,text='Login',command=self.try_login).grid(row=3,column=0,columnspan=2,pady=8)
        self.bind_all('<Return>', lambda e: self.try_login())
    def try_login(self):
        user=self.u.get().strip(); pwd=self.p.get().strip()
        if not user or not pwd: messagebox.showerror('Error','Enter credentials'); return
        row=self.db.query('SELECT * FROM users WHERE username=?;', (user,))
        if not row or row[0]['password_hash']!=hash_pw(pwd): messagebox.showerror('Error','Invalid'); return
        self.on_login({'id':row[0]['id'],'username':user,'role':row[0]['role']})

class InventoryTab(ttk.Frame):
    def __init__(self,master,db,role): super().__init__(master); self.db=db; self.role=role; self._build()
    def _build(self):
        top=ttk.Frame(self); top.pack(fill='x',padx=8,pady=6)
        ttk.Label(top,text='Products',font=('Segoe UI',12,'bold')).pack(side='left')
        self.search_var=tk.StringVar(); ttk.Entry(top,textvariable=self.search_var).pack(side='right'); ttk.Label(top,text='Search').pack(side='right')
        self.search_var.trace_add('write', lambda *a: self.refresh())
        self.tree=ttk.Treeview(self, columns=('id','name','price','stock'), show='headings', height=15)
        for h,w in (('id',50),('name',300),('price',80),('stock',80)): self.tree.heading(h,text=h.title()); self.tree.column(h,width=w)
        vsb=ttk.Scrollbar(self,orient='vertical',command=self.tree.yview); self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side='left',fill='both',expand=True); vsb.pack(side='left',fill='y')
        frm=ttk.Frame(self); frm.pack(side='left',fill='y',padx=8)
        ttk.Button(frm,text='Add',command=self.add).pack(fill='x',pady=4); ttk.Button(frm,text='Edit',command=self.edit).pack(fill='x',pady=4); ttk.Button(frm,text='Delete',command=self.delete).pack(fill='x',pady=4)
        self.refresh()
    def refresh(self):
        term=self.search_var.get().strip().lower(); self.tree.delete(*self.tree.get_children())
        rows=self.db.query('SELECT id,name,sale_price AS price,COALESCE(stock,0) AS stock FROM products ORDER BY name;')
        for r in rows:
            if term and term not in (str(r['id'])+r['name']).lower(): continue
            self.tree.insert('', 'end', iid=r['id'], values=(r['id'], r['name'], f"{r['price']:.2f}", r['stock']))
    def add(self):
        def save(d):
            if not d['name']: messagebox.showerror('Error','Name required'); return
            self.db.execute('INSERT INTO products(name,sku,is_medical,sale_price,stock) VALUES(?,?,?,?,?);', (d['name'], d.get('sku'), 1, float(d.get('price') or 0), int(d.get('stock') or 0))); self.refresh()
        FormDialog(self,'Add Product',[{'key':'name','label':'Name'},{'key':'sku','label':'SKU'},{'key':'price','label':'Price'},{'key':'stock','label':'Stock'}], on_submit=save)
    def edit(self):
        sel=self.tree.selection(); 
        if not sel: messagebox.showinfo('Select','Select product'); return
        pid=int(sel[0]); row=self.db.query('SELECT * FROM products WHERE id=?;', (pid,))
        if not row: return
        d0=row[0]
        def save(d): self.db.execute('UPDATE products SET name=?, sku=?, sale_price=?, stock=? WHERE id=?;', (d['name'], d.get('sku'), float(d.get('price') or 0), int(d.get('stock') or 0), pid)); self.refresh()
        FormDialog(self,'Edit Product',[{'key':'name','label':'Name'},{'key':'sku','label':'SKU'},{'key':'price','label':'Price'},{'key':'stock','label':'Stock'}], initial=d0, on_submit=save)
    def delete(self):
        sel=self.tree.selection(); 
        if not sel: messagebox.showinfo('Select','Select product'); return
        if messagebox.askyesno('Confirm','Delete?'): self.db.execute('DELETE FROM products WHERE id=?;', (int(sel[0]),)); self.refresh()

class FormDialog(tk.Toplevel):
    def __init__(self, master, title, fields, initial=None, on_submit=None):
        super().__init__(master); self.title(title); self.on_submit=on_submit; self.resizable(False,False); self.transient(master); self.grab_set()
        frm=ttk.Frame(self,padding=8); frm.pack(fill='both',expand=True)
        self.widgets={}
        for i,f in enumerate(fields):
            ttk.Label(frm,text=f.get('label', f['key'])).grid(row=i,column=0,sticky='w',pady=4)
            w=ttk.Entry(frm) if f.get('widget','entry')!='text' else tk.Text(frm,height=3,width=30)
            if initial and f['key'] in initial and initial[f['key']] is not None:
                try:
                    if isinstance(w, tk.Text): w.insert('1.0', str(initial[f['key']]))
                    else: w.insert(0, str(initial[f['key']]))
                except: pass
            w.grid(row=i,column=1,pady=4)
            self.widgets[f['key']]=(w,f)
        btns=ttk.Frame(frm); btns.grid(row=len(fields),column=0,columnspan=2,pady=8)
        ttk.Button(btns,text='Save',command=self._save).pack(side='left',padx=6); ttk.Button(btns,text='Cancel',command=self.destroy).pack(side='left')
    def _save(self):
        data={}
        for key,(w,f) in self.widgets.items():
            if isinstance(w, tk.Text): data[key]=w.get('1.0','end').strip()
            else: data[key]=w.get().strip()
        if self.on_submit: self.on_submit(data); self.destroy()

class NewSaleFrame(ttk.Frame):
    def __init__(self, master, db, user): super().__init__(master); self.db=db; self.user=user; self.cart=[]; self._build()
    def _build(self):
        top=ttk.Frame(self); top.pack(fill='x',padx=8,pady=6)
        ttk.Label(top,text='POS - New Sale',font=('Segoe UI',12,'bold')).pack(side='left')
        ttk.Label(top,text='Search:').pack(side='left',padx=6); self.search_e=ttk.Entry(top,width=40); self.search_e.pack(side='left')
        ttk.Label(top,text='Qty:').pack(side='left',padx=6); self.qty=ttk.Spinbox(top,from_=1,to=9999,width=6); self.qty.set('1'); self.qty.pack(side='left')
        ttk.Button(top,text='Add',command=self.search_add).pack(side='left',padx=6)
        body=ttk.Frame(self); body.pack(fill='both',expand=True,padx=8,pady=6)
        left=ttk.Frame(body); left.pack(side='left',fill='both',expand=True)
        self.prod_tree=ttk.Treeview(left,columns=('id','name','price','stock'),show='headings',height=15)
        for h,w in (('id',60),('name',300),('price',80),('stock',80)): self.prod_tree.heading(h,text=h.title()); self.prod_tree.column(h,width=w)
        vsb=ttk.Scrollbar(left,orient='vertical',command=self.prod_tree.yview); self.prod_tree.configure(yscrollcommand=vsb.set)
        self.prod_tree.pack(side='left',fill='both',expand=True); vsb.pack(side='left',fill='y')
        ttk.Button(left,text='Refresh',command=self.refresh_products).pack(pady=6); ttk.Button(left,text='Add Selected',command=self.add_selected).pack(pady=6)
        right=ttk.Frame(body); right.pack(side='right',fill='y',padx=8)
        ttk.Label(right,text='Cart',font=('Segoe UI',12,'bold')).pack()
        self.cart_tree=ttk.Treeview(right,columns=('name','qty','price','total'),show='headings',height=12)
        for h,w in (('name',160),('qty',50),('price',80),('total',80)): self.cart_tree.heading(h,text=h.title()); self.cart_tree.column(h,width=w)
        self.cart_tree.pack(fill='both'); ttk.Button(right,text='Checkout',command=self.checkout).pack(fill='x',pady=6)
        self.refresh_products(); self.refresh_cart()

    def refresh_products(self):
        self.prod_tree.delete(*self.prod_tree.get_children()); rows=self.db.query('SELECT id,name,sale_price AS price,COALESCE(stock,0) AS stock FROM products ORDER BY name;')
        for r in rows: self.prod_tree.insert('', 'end', iid=r['id'], values=(r['id'],r['name'],f"{r['price']:.2f}",r['stock']))

    def search_add(self):
        txt=self.search_e.get().strip().lower()
        if not txt: messagebox.showinfo('Info','Enter product name or id'); return
        rows=self.db.query('SELECT id,name,sale_price AS price,COALESCE(stock,0) AS stock FROM products WHERE lower(name) LIKE ? OR CAST(id AS TEXT)=? LIMIT 1;', (f"%{txt}%", txt))
        if not rows: messagebox.showinfo('Not found','Product not found'); return
        item=rows[0]; qty=int(self.qty.get() or 1)
        if item['stock'] < qty: messagebox.showerror('Stock','Not enough stock'); return
        for c in self.cart:
            if c['product_id']==item['id']: c['qty']+=qty; self.refresh_cart(); return
        self.cart.append({'product_id':item['id'],'name':item['name'],'unit_price':float(item['price']),'qty':qty}); self.refresh_cart()

    def add_selected(self):
        sel=self.prod_tree.selection(); 
        if not sel: messagebox.showinfo('Select','Select product'); return
        pid=int(sel[0]); row=self.db.query('SELECT id,name,sale_price AS price,COALESCE(stock,0) AS stock FROM products WHERE id=?;', (pid,))
        if not row: return
        item=row[0]; qty=1
        if item['stock']<qty: messagebox.showerror('Stock','Not enough stock'); return
        for c in self.cart:
            if c['product_id']==item['id']: c['qty']+=qty; self.refresh_cart(); return
        self.cart.append({'product_id':item['id'],'name':item['name'],'unit_price':float(item['price']),'qty':qty}); self.refresh_cart()

    def refresh_cart(self):
        self.cart_tree.delete(*self.cart_tree.get_children()); subtotal=0.0
        for c in self.cart:
            total=c['unit_price']*c['qty']; subtotal+=total; self.cart_tree.insert('', 'end', iid=str(c['product_id']), values=(c['name'],c['qty'],f"{c['unit_price']:.2f}",f"{total:.2f}"))
        # show subtotal in title bar
        self.master.master.master.title(f"Pharmacy Management System - Subtotal: {subtotal:.2f}")

    def checkout(self):
        if not self.cart: messagebox.showwarning('Empty','Cart empty'); return
        with self.db.connect() as con:
            cur=con.cursor()
            for c in self.cart:
                r=cur.execute('SELECT COALESCE(stock,0) AS stock FROM products WHERE id=?;', (c['product_id'],)).fetchone()
                if not r or int(r['stock']) < c['qty']: messagebox.showerror('Stock',f"Insufficient for {c['name']}"); return
            invoice = 'INV-'+datetime.now().strftime('%Y%m%d%H%M%S')
            subtotal = sum(ci['qty']*ci['unit_price'] for ci in self.cart)
            cur.execute('INSERT INTO sales(invoice_no,sale_date,cashier_id,subtotal,total) VALUES(?,?,?,?,?);', (invoice, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), self.user['id'], subtotal, subtotal))
            sale_id = cur.lastrowid
            for ci in self.cart:
                cur.execute('INSERT INTO sale_items(sale_id,product_id,quantity,unit_price,line_total) VALUES(?,?,?,?,?);', (sale_id, ci['product_id'], ci['qty'], ci['unit_price'], ci['qty']*ci['unit_price']))
                cur.execute('UPDATE products SET stock = stock - ? WHERE id=?;', (ci['qty'], ci['product_id']))
            con.commit()
        inv_txt = os.path.join(INVOICES_DIR, f"{invoice}.txt")
        with open(inv_txt,'w',encoding='utf-8') as f:
            f.write(f"Invoice: {invoice}\nDate: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            for ci in self.cart: f.write(f"{ci['name']} x{ci['qty']} @ {ci['unit_price']:.2f} = {ci['qty']*ci['unit_price']:.2f}\n")
            f.write(f"\nTotal: {subtotal:.2f}\n")
        messagebox.showinfo('Sale','Recorded: '+invoice); self.cart=[]; self.refresh_cart(); self.refresh_products()

class MainApp:
    def __init__(self):
        ensure_db(); self.db=DB(); self.root = tk.Tk(); self.root.geometry('1000x640'); self.root.title('Pharmacy Management System')
        self.container = ttk.Frame(self.root); self.container.pack(fill='both',expand=True); self.show_login()
    def clear(self): 
        for w in self.container.winfo_children(): w.destroy()
    def show_login(self):
        self.clear(); lf = LoginFrame(self.container, on_login=self.on_login); lf.pack(fill='both',expand=True)
    def on_login(self,user):
        self.clear()
        header = ttk.Frame(self.container); header.pack(fill='x',padx=8,pady=6)
        ttk.Label(header, text=f"Welcome {user['username']} ({user['role']})", font=('Segoe UI',12,'bold')).pack(side='left')
        ttk.Button(header, text='Logout', command=self.show_login).pack(side='right')
        nb = ttk.Notebook(self.container); nb.pack(fill='both',expand=True,padx=8,pady=8)
        nb.add(InventoryTab(nb, self.db, user['role']), text='Inventory')
        nb.add(NewSaleFrame(nb, self.db, user), text='Sales / POS')
    def run(self): self.root.mainloop()

if __name__ == '__main__':
    MainApp().run()

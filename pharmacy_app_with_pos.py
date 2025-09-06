
import os, sqlite3, hashlib, tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime, timedelta
try: import ttkbootstrap as tb
except: tb=None
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as pdf_canvas
    REPORTLAB=True
except:
    REPORTLAB=False
BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, 'pharmacy.db')
INVOICES_DIR = os.path.join(BASE_DIR, 'invoices')
os.makedirs(INVOICES_DIR, exist_ok=True)
def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()
class DB:
    def __init__(self,path=DB_PATH): self.path=path
    def connect(self): con=sqlite3.connect(self.path); con.row_factory=sqlite3.Row; con.execute('PRAGMA foreign_keys=ON;'); return con
    def query(self,sql,params=()):
        with self.connect() as c:
            cur=c.execute(sql,params)
            return [dict(r) for r in cur.fetchall()]
    def execute(self,sql,params=()):
        with self.connect() as c:
            cur=c.execute(sql,params)
            c.commit()
            return cur.lastrowid
def generate_invoice_file(path, sale_id):
    db=DB(); sale=db.query('SELECT s.*, u.username FROM sales s LEFT JOIN users u ON s.cashier_id=u.id WHERE s.id=?;', (sale_id,))
    if not sale: return False
    s=sale[0]
    items=db.query('SELECT si.*, p.name FROM sale_items si LEFT JOIN products p ON si.product_id=p.id WHERE si.sale_id=?;', (sale_id,))
    if REPORTLAB:
        c=pdf_canvas.Canvas(path, pagesize=A4); w,h=A4; y=h-20*mm
        c.setFont('Helvetica-Bold',14); c.drawString(20*mm,y,'Invoice'); y-=8*mm
        c.setFont('Helvetica',10); c.drawString(20*mm,y,f"Invoice: {s['invoice_no']}"); c.drawRightString(w-20*mm,y,f"Date: {s['sale_date']}"); y-=6*mm
        c.drawString(20*mm,y,f"Cashier: {s['username']}"); y-=8*mm
        for it in items:
            line=f"{it['name']} x{it['quantity']} @ {it['unit_price']:.2f} = {it['line_total']:.2f}"
            c.drawString(20*mm,y,line); y-=6*mm
            if y<30*mm: c.showPage(); y=h-20*mm
        y-=4*mm
        c.drawRightString(w-20*mm,y,f"Subtotal: {s['subtotal']:.2f}"); y-=6*mm
        c.drawRightString(w-20*mm,y,f"Tax: {s['tax']:.2f}"); y-=6*mm
        c.drawRightString(w-20*mm,y,f"Total: {s['total']:.2f}"); c.showPage(); c.save()
        return True
    else:
        with open(path,'w',encoding='utf-8') as f:
            f.write(f"Invoice: {s['invoice_no']}\nDate: {s['sale_date']}\nCashier: {s['username']}\n\n")
            for it in items:
                f.write(f"{it['name']} x{it['quantity']} @ {it['unit_price']:.2f} = {it['line_total']:.2f}\n")
            f.write(f"\nSubtotal: {s['subtotal']:.2f}\nTax: {s['tax']:.2f}\nTotal: {s['total']:.2f}\n")
        return True
# Minimal GUI components: Login, Inventory tabs, POS tabs
class LoginFrame(ttk.Frame):
    def __init__(self,master,on_login): super().__init__(master); self.on_login=on_login; self.db=DB(); self._build()
    def _build(self):
        frm=ttk.Frame(self,padding=20); frm.pack(expand=True)
        ttk.Label(frm,text='Login',font=('Segoe UI',16,'bold')).grid(row=0,column=0,columnspan=2,pady=8)
        ttk.Label(frm,text='Username').grid(row=1,column=0); ttk.Label(frm,text='Password').grid(row=2,column=0)
        self.u=ttk.Entry(frm); self.p=ttk.Entry(frm,show='•'); self.u.grid(row=1,column=1); self.p.grid(row=2,column=1)
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
            self.db.execute('INSERT INTO products(name,sku,is_medical,sale_price,stock) VALUES(?,?,?,?,?);', (d['name'], d.get('sku'), 1, float(d.get('price') or 0), int(d.get('stock') or 0)))
            self.refresh()
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
            ttk.Label(frm,text=f.get('label',f['key'])).grid(row=i,column=0,sticky='w',pady=4)
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
        if self.on_submit: self.on_submit(data)
        self.destroy()
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
            cur.execute('INSERT INTO sales(invoice_no,sale_date,cashier_id,subtotal,tax,total) VALUES(?,?,?,?,?,?);', (invoice, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), self.user['id'], subtotal, 0.0, subtotal))
            sale_id = cur.lastrowid
            for ci in self.cart:
                cur.execute('INSERT INTO sale_items(sale_id,product_id,quantity,unit_price,line_total) VALUES(?,?,?,?,?);', (sale_id, ci['product_id'], ci['qty'], ci['unit_price'], ci['qty']*ci['unit_price']))
                cur.execute('UPDATE products SET stock = stock - ? WHERE id=?;', (ci['qty'], ci['product_id']))
            con.commit()
        messagebox.showinfo('Sale','Recorded: '+invoice); self.cart=[]; self.refresh_cart(); self.refresh_products()
class SaleHistoryFrame(ttk.Frame):
    def __init__(self, master, db): super().__init__(master); self.db=db; self._build()
    def _build(self):
        top=ttk.Frame(self); top.pack(fill='x',padx=8,pady=6)
        ttk.Label(top,text='Sale History',font=('Segoe UI',12,'bold')).pack(side='left')
        self.tree=ttk.Treeview(self, columns=('id','invoice','date','cashier','total'), show='headings', height=18)
        for h,w in (('id',60),('invoice',180),('date',180),('cashier',120),('total',80)): self.tree.heading(h,text=h.title()); self.tree.column(h,width=w)
        vsb=ttk.Scrollbar(self,orient='vertical',command=self.tree.yview); self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side='left',fill='both',expand=True); vsb.pack(side='left',fill='y')
        btns=ttk.Frame(self); btns.pack(side='left',fill='y',padx=8)
        ttk.Button(btns,text='View Items',command=self.view_items).pack(fill='x',pady=6)
        ttk.Button(btns,text='Print/Save Invoice',command=self.print_invoice).pack(fill='x',pady=6)
        self.refresh()
    def refresh(self):
        self.tree.delete(*self.tree.get_children()); rows=self.db.query("SELECT s.id,s.invoice_no AS invoice,s.sale_date AS date,COALESCE(u.username,'') AS cashier,s.total FROM sales s LEFT JOIN users u ON s.cashier_id=u.id ORDER BY s.id DESC;")
        for r in rows: self.tree.insert('', 'end', iid=r['id'], values=(r['id'], r['invoice'], r['date'], r['cashier'], f"{r['total']:.2f}"))
    def view_items(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo('Select','Select a sale')
            return
        sid = int(sel[0])
        rows = self.db.query(
            'SELECT si.quantity,si.unit_price,si.line_total,p.name '
            'FROM sale_items si LEFT JOIN products p ON si.product_id=p.id '
            'WHERE si.sale_id=?;', (sid,)
        )
        txt = ''
        for r in rows:
            txt += f"{r['name']} x{r['quantity']} @ {r['unit_price']:.2f} = {r['line_total']:.2f}\n"
        messagebox.showinfo('Items', txt or 'No items')


def print_invoice(self):
    sel = self.tree.selection()
    if not sel:
        messagebox.showinfo('Select','Select a sale')
        return
    sid = int(sel[0])
    ext = '.pdf' if REPORTLAB else '.txt'
    path = filedialog.asksaveasfilename(defaultextension=ext)
    if not path:
        return
    ok = generate_invoice_file(path, sid)
    if ok:
        messagebox.showinfo('Saved', f'Invoice saved to {path}')
    else:
        messagebox.showerror('Error','Could not generate')

class ReturnFrame(ttk.Frame):
    def __init__(self, master, db, user): super().__init__(master); self.db=db; self.user=user; self.sale=None; self.sale_items=[]; self.to_return={}; self._build()
    def _build(self):
        top=ttk.Frame(self); top.pack(fill='x',padx=8,pady=6)
        ttk.Label(top,text='Return Item',font=('Segoe UI',12,'bold')).pack(side='left')
        ttk.Label(top,text='Invoice:').pack(side='left',padx=6); self.inv_e=ttk.Entry(top,width=30); self.inv_e.pack(side='left')
        ttk.Button(top,text='Fetch',command=self.fetch_sale).pack(side='left',padx=6)
        self.tree=ttk.Treeview(self, columns=('sale_item_id','product','qty','unit_price','line_total'), show='headings', height=12)
        for h,w in (('sale_item_id',80),('product',260),('qty',60),('unit_price',80),('line_total',80)): self.tree.heading(h,text=h.title()); self.tree.column(h,width=w)
        vsb=ttk.Scrollbar(self,orient='vertical',command=self.tree.yview); self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side='left',fill='both',expand=True); vsb.pack(side='left',fill='y')
        bot=ttk.Frame(self); bot.pack(fill='x',padx=8,pady=6)
        ttk.Label(bot,text='Return Qty:').pack(side='left',padx=4); self.ret_qty=ttk.Spinbox(bot,from_=1,to=9999,width=6); self.ret_qty.set('1'); self.ret_qty.pack(side='left')
        ttk.Button(bot,text='Mark For Return',command=self.mark_return).pack(side='left',padx=6)
        ttk.Button(bot,text='Process Return',command=self.process_return).pack(side='right',padx=6)
    def fetch_sale(self):
        inv = self.inv_e.get().strip()
        if not inv:
            messagebox.showerror('Error','Enter invoice')
            return

        rows = self.db.query('SELECT * FROM sales WHERE invoice_no=?;', (inv,))
        if not rows:
            messagebox.showerror('Not found','Sale not found')
            return

        self.sale = rows[0]
        self.sale_items = self.db.query(
            'SELECT si.id as sale_item_id, p.name, si.quantity, si.unit_price, si.line_total '
            'FROM sale_items si LEFT JOIN products p ON si.product_id=p.id '
            'WHERE si.sale_id=?;', (self.sale['id'],)
        )

        self.tree.delete(*self.tree.get_children())
        for r in self.sale_items:
            self.tree.insert(
                '', 'end', iid=r['sale_item_id'],
                values=(r['sale_item_id'], r['name'], r['quantity'],
                        f"{r['unit_price']:.2f}", f"{r['line_total']:.2f}")
            )
        self.to_return = {}


    def mark_return(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo('Select','Select item')
            return

        sid = int(sel[0])
        qty = int(self.ret_qty.get())

        item = next((i for i in self.sale_items if i['sale_item_id'] == sid), None)
        if not item:
            return

        if qty > item['quantity']:
            messagebox.showerror('Error','Return qty exceeds sold qty')
            return

        self.to_return[sid] = self.to_return.get(sid, 0) + qty
        messagebox.showinfo('Marked', f"Marked {qty} of item id {sid} for return")


    def process_return(self):
        if not self.to_return: messagebox.showwarning('Empty','No items marked'); return
        import uuid; retno='RET-'+datetime.now().strftime('%Y%m%d%H%M%S')+'-'+uuid.uuid4().hex[:4].upper(); total_refund=0.0
        with self.db.connect() as con:
            cur=con.cursor(); cur.execute('INSERT INTO returns(return_no,sale_id,return_date,cashier_id,total_refund) VALUES(?,?,?,?,?);', (retno, self.sale['id'], datetime.now().strftime('%Y-%m-%d %H:%M:%S'), self.user['id'], 0.0)); rid=cur.lastrowid
            for sid, qty in self.to_return.items():
                row=cur.execute('SELECT product_id, unit_price FROM sale_items WHERE id=?;', (sid,)).fetchone()
                if not row: continue
                pid=row[0]; unit_price=float(row[1]); refund=unit_price*qty; total_refund+=refund
                cur.execute('INSERT INTO return_items(return_id,sale_item_id,product_id,quantity,refund_amount) VALUES(?,?,?,?,?);', (rid, sid, pid, qty, refund))
                cur.execute('UPDATE products SET stock = stock + ? WHERE id=?;', (qty, pid))
            cur.execute('UPDATE returns SET total_refund=? WHERE id=?;', (total_refund, rid)); con.commit()
        messagebox.showinfo('Return', f'Return: {retno}\nRefund: {total_refund:.2f}'); self.to_return={}; self.fetch_sale()
class ReturnHistoryFrame(ttk.Frame):
    def __init__(self, master, db):
        super().__init__(master)
        self.db = db
        self._build()

    def _build(self):
        self.tree = ttk.Treeview(
            self,
            columns=('id', 'return_no', 'sale_id', 'date', 'cashier', 'refund'),
            show='headings',
            height=18
        )
        for h, w in (
            ('id', 60),
            ('return_no', 160),
            ('sale_id', 80),
            ('date', 180),
            ('cashier', 120),
            ('refund', 80)
        ):
            self.tree.heading(h, text=h.title())
            self.tree.column(h, width=w)

        vsb = ttk.Scrollbar(self, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)

        self.tree.pack(side='left', fill='both', expand=True)
        vsb.pack(side='left', fill='y')

        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        rows = self.db.query(
            "SELECT r.id, r.return_no, r.sale_id, r.return_date as date, "
            "COALESCE(u.username,'') as cashier, r.total_refund as refund "
            "FROM returns r LEFT JOIN users u ON r.cashier_id=u.id "
            "ORDER BY r.id DESC;"
        )
        for r in rows:
            self.tree.insert(
                '', 'end', iid=r['id'],
                values=(r['id'], r['return_no'], r['sale_id'],
                        r['date'], r['cashier'], f"{r['refund']:.2f}")
            )

class App:
    def __init__(self):
        if not os.path.exists(DB_PATH): messagebox.showerror('Error','Database missing'); raise SystemExit
        self.db=DB(); self.root = tb.Window(themename='cosmo') if tb else tk.Tk(); self.root.title('Pharmacy Management Demo'); self.root.geometry('1000x640')
        self.container=ttk.Frame(self.root); self.container.pack(fill='both',expand=True)
        self.show_login()
    def clear(self):
        for w in self.container.winfo_children(): w.destroy()
    def show_login(self): self.clear(); lf=LoginFrame(self.container, on_login=self.on_login); lf.pack(fill='both',expand=True)
    def on_login(self,user):
        self.clear(); header=ttk.Frame(self.container); header.pack(fill='x',padx=8,pady=6)
        ttk.Label(header, text=f"Welcome {user['username']} ({user['role']})", font=('Segoe UI',12,'bold')).pack(side='left')
        ttk.Button(header, text='Logout', command=self.show_login).pack(side='right')
        nb=ttk.Notebook(self.container); nb.pack(fill='both',expand=True,padx=8,pady=8)
        nb.add(InventoryTab(nb, self.db, user['role']), text='Inventory')
        pos_frame=ttk.Frame(nb); pos_nb=ttk.Notebook(pos_frame); pos_nb.pack(fill='both',expand=True)
        pos_nb.add(NewSaleFrame(pos_nb, self.db, user), text='New Sale')
        pos_nb.add(SaleHistoryFrame(pos_nb, self.db), text='Sale History')
        pos_nb.add(ReturnFrame(pos_nb, self.db, user), text='Return Item')
        pos_nb.add(ReturnHistoryFrame(pos_nb, self.db), text='Return History')
        nb.add(pos_frame, text='Sales / POS')
    def run(self): self.root.mainloop()

if __name__=='__main__': App().run()
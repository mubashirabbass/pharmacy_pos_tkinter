
# 🏥 Pharmacy Management System

A **full-featured Pharmacy Management System** built in **Python** with a modern GUI, sales management, inventory tracking, customer records, receipt generation, and direct printing support.

## 📌 Features

✅ **User Authentication & Roles**

* Secure login with password hashing
* Roles: **Admin, Staff, Cashier**

✅ **Inventory Management**

* Add, edit, and delete products
* Manage suppliers, manufacturers, and formulas
* Track **stock levels, expiry dates, and low stock alerts**

✅ **Point of Sale (POS)**

* Quick product search with **autocomplete**
* Cart system with quantity & subtotal calculation
* Checkout with **receipt generation (PDF/thermal print)**

✅ **Dashboard & Analytics**

* Monthly sales statistics
* Low stock and near-expiry product alerts
* Interactive charts powered by **Matplotlib**

✅ **Customer & Sales Records**

* Customer profiles with purchase history
* Sales and returns tracking

✅ **Receipts & Printing**

* Auto-generated **PDF receipts** using **ReportLab**
* Supports **direct printing to thermal printers**

✅ **Modern GUI**

* Built with **Tkinter** and **ttkbootstrap** for a clean look
* Sidebar navigation with hover effects

---

## 🛠 Tech Stack

* **Python 3.x**
* **SQLite3** (Database)
* **Tkinter & ttkbootstrap** (GUI)
* **Matplotlib** (Charts & Analytics)
* **ReportLab** (PDF Generation)
* **PIL / Pillow** (Image handling)
* **OpenPyXL** (Excel export support)

---

## 🚀 Installation

1. **Clone the Repository**

```bash
git clone https://github.com/mubashirabbass/pharmacy-management-system.git
cd pharmacy-management-system
```

2. **Install Dependencies**

```bash
pip install -r requirements.txt
```

3. **Run the Application**

```bash
python mainproject.py
```

---

## 📂 Project Structure

```
pharmacy-management-system/
│── mainproject.py       # Main application
│── pharmacy.db          # SQLite database (auto-created if missing)
│── receipts/            # Auto-generated receipts (PDF format)
│── backups/             # Database backups
│── icons/               # Sidebar and GUI icons
│── logo.png             # App logo
│── requirements.txt     # Dependencies
└── README.md            # Project documentation
```

---

## 📸 Screenshots

👉 *(Add screenshots of your dashboard, POS screen, and receipt preview here)*

---

## 👨‍💻 Author

Developed by **Mubashir Abbas**
📧 Email: *(mubashirabbasedu12@gmail.com)*
🔗 LinkedIn: [Your LinkedIn Profile](www.linkedin.com/in/mubashirabbas)
🔗 GitHub: [Your GitHub Profile](https://github.com/mubashirabbass)

---

## 🏆 Future Improvements

* 🔐 User authentication with JWT (for web version)
* 🌐 Flask/Django web integration
* 📱 Mobile App (Kivy/React Native)
* 📊 Advanced analytics & reporting

---

## 📜 License

This project is licensed under the **MIT License** – feel free to use and improve it!



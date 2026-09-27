"""
سكريبت ترحيل لمرة واحدة: بياخد بيانات قاعدة SQLite القديمة (db/shop.db -
اللي كانت مستخدمة قبل التحويل لـ SQL Server) وينقلها لقاعدة بيانات
SQL Server الجديدة تحت "الفرع الرئيسي".

طريقة الاستخدام:
    python dev_tools/migrate_sqlite_to_mssql.py
    python dev_tools/migrate_sqlite_to_mssql.py --sqlite-path "D:\\old\\shop.db"

قبل التشغيل: لازم يكون عندك إعداد اتصال SQL Server محفوظ بالفعل (شغّل
البرنامج مرة واحدة الأول وأدخل بيانات السيرفر من نافذة الإعداد اللي
بتظهر أول تشغيل)، عشان السكريبت ده بيستخدم نفس الإعداد.
"""
import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import database as db  # noqa: E402

# الجداول اللي بتترحّل، بالترتيب اللي بيحترم العلاقات (FK) بين بعضها -
# لازم نرحّل الجدول الأب قبل الابن (مثلاً suppliers قبل products).
MIGRATE_ORDER = [
    "customers", "suppliers", "employees",
    "products",
    "sales", "sale_items",
    "purchases", "purchase_items",
    "treasury_accounts", "treasury_transactions",
    "expenses", "advances",
    "debts", "debt_payments",
    "settlement_companies", "company_settlements",
    "maintenance",
]


def _sqlite_columns(sconn, table):
    cur = sconn.execute(f"PRAGMA table_info({table})")
    return [r[1] for r in cur.fetchall()]


def migrate_settings(sconn):
    print("-- ترحيل settings...")
    for row in sconn.execute("SELECT key, value FROM settings"):
        key, value = row[0], row[1]
        exists = db.fetch_one("SELECT 1 FROM settings WHERE setting_key=?", (key,))
        if exists:
            db.execute("UPDATE settings SET value=? WHERE setting_key=?", (value, key))
        else:
            db.execute("INSERT INTO settings (setting_key, value) VALUES (?,?)", (key, value))


def migrate_users(sconn, main_branch_id):
    print("-- ترحيل users...")
    db.execute("DELETE FROM users")
    for row in sconn.execute("SELECT username, password_hash, role, full_name FROM users"):
        username, password_hash, role, full_name = row
        branch_id = None if role == "admin" else main_branch_id
        db.execute(
            "INSERT INTO users (username, password_hash, role, full_name, branch_id) VALUES (?,?,?,?,?)",
            (username, password_hash, role, full_name, branch_id),
        )


def migrate_table(sconn, conn, table, main_branch_id):
    cols = _sqlite_columns(sconn, table)
    rows = sconn.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
    print(f"-- ترحيل {table} ({len(rows)} صف)...")
    if not rows:
        return

    cur = conn.cursor()
    cur.execute(f"SET IDENTITY_INSERT {table} ON")
    try:
        insert_cols = cols + ["branch_id"]
        placeholders = ", ".join("?" for _ in insert_cols)
        sql = f"INSERT INTO {table} ({', '.join(insert_cols)}) VALUES ({placeholders})"
        for row in rows:
            cur.execute(sql, tuple(row) + (main_branch_id,))
        conn.commit()
    finally:
        cur.execute(f"SET IDENTITY_INSERT {table} OFF")
        conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sqlite-path",
        default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db", "shop.db"),
    )
    parser.add_argument("--branch-name", default="الفرع الرئيسي")
    args = parser.parse_args()

    if not os.path.exists(args.sqlite_path):
        print(f"مفيش ملف SQLite في المسار ده: {args.sqlite_path}")
        sys.exit(1)

    print("== جاري تجهيز قاعدة بيانات SQL Server (إنشاء الجداول لو مش موجودة) ==")
    db.init_db()

    main_branch = db.fetch_one("SELECT id FROM branches WHERE name=?", (args.branch_name,))
    if not main_branch:
        main_branch = db.fetch_one("SELECT TOP 1 id FROM branches ORDER BY id")
    main_branch_id = main_branch["id"]
    print(f"== هيتم ترحيل كل البيانات تحت الفرع (id={main_branch_id}) ==")

    # لازم نحط الجلسة في وضع "أدمن" قبل أي DELETE/SELECT على جداول
    # محكومة بـ RLS، وإلا سياسة عزل الفروع هتمنعنا نشوف/نمسح أي صف
    # (من غير branch_id محدد في الجلسة، الفلتر بيرفض كل الصفوف).
    db.set_session_branch(main_branch_id, is_admin=True)
    conn = db.get_connection()

    # نشيل بيانات الزرع الافتراضي (حسابات خزنة/شركة تحصيل) قبل ما نستورد
    # النسخ الحقيقية من القاعدة القديمة بنفس الـ id الأصلي بتاعها.
    conn.cursor().execute("DELETE FROM treasury_accounts WHERE branch_id=?", (main_branch_id,))
    conn.cursor().execute("DELETE FROM settlement_companies WHERE branch_id=?", (main_branch_id,))
    conn.commit()

    sconn = sqlite3.connect(args.sqlite_path)
    try:
        migrate_settings(sconn)
        migrate_users(sconn, main_branch_id)
        for table in MIGRATE_ORDER:
            migrate_table(sconn, conn, table, main_branch_id)
    finally:
        sconn.close()

    print("== تم الترحيل بنجاح ==")


if __name__ == "__main__":
    main()

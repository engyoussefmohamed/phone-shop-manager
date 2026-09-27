"""
طبقة قاعدة البيانات - نظام إدارة محل التلفونات
Microsoft SQL Server (عن طريق pyodbc) - قاعدة بيانات واحدة مركزية تقدر
توصلها من أكتر من جهاز/فرع في نفس الوقت، وتقدر تفتحها وتشوف كل الجداول
من SQL Server Management Studio عادي.

عزل بيانات الفروع عن بعض بيبقى على مستوى القاعدة نفسها (Row-Level
Security): كل جدول عملياتي فيه عمود branch_id مربوط بجدول branches،
وفيه Security Policy بتفلتر تلقائي أي SELECT/UPDATE/DELETE على الفرع
الحالي المحفوظ في SESSION_CONTEXT بتاع الاتصال - المستخدم (الأدمن أو
الموظف) مبيحتاجش يحدد الفرع في كل استعلام، القاعدة نفسها بتتكفل بيه.
"""
import datetime
import json
import re
import threading

import pyodbc

from app import db_config
from app import i18n

BASE_DIR = db_config.BASE_DIR

# ---------------- الاتصال ----------------

_local = threading.local()
_current_branch_id = None
_current_is_admin = False


class NotConfiguredError(Exception):
    """لسه معملناش إعداد اتصال بقاعدة البيانات (أول تشغيل)."""


def get_connection():
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.cursor().execute("SELECT 1")
            return conn
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            _local.conn = None

    if not db_config.is_configured():
        raise NotConfiguredError("لسه مفيش إعداد اتصال بقاعدة بيانات SQL Server")

    cfg = db_config.load_config()
    conn = pyodbc.connect(db_config.build_connection_string(cfg), timeout=8)
    conn.autocommit = False
    _local.conn = conn
    _apply_session_context(conn)
    return conn


def _apply_session_context(conn):
    cur = conn.cursor()
    cur.execute(
        "EXEC sp_set_session_context @key=N'branch_id', @value=?, @read_only=0",
        (_current_branch_id,),
    )
    cur.execute(
        "EXEC sp_set_session_context @key=N'is_admin', @value=?, @read_only=0",
        (1 if _current_is_admin else 0,),
    )
    conn.commit()


def set_session_branch(branch_id, is_admin=False):
    """بتتنادى بعد تسجيل الدخول (أو لما الأدمن يغيّر الفرع اللي شغال عليه
    دلوقتي) - بتحدد أي فرع هيتحط تلقائي في أي صف جديد يتضاف، وبتحدد كمان
    لو المستخدم أدمن (يشوف كل الفروع) أو موظف (يشوف فرعه بس)."""
    global _current_branch_id, _current_is_admin
    _current_branch_id = branch_id
    _current_is_admin = is_admin
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            _apply_session_context(conn)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            _local.conn = None


def get_session_branch():
    return _current_branch_id, _current_is_admin


# ---------------- ترجمة اختلافات SQLite -> T-SQL ----------------
# استعلامات الشاشات لسه مكتوبة بنفس صيغة LIMIT (من عهد SQLite) - بدل ما
# نلف على كل شاشة ونصلّحها واحدة واحدة، بنترجمها هنا مركزيًا لصيغة
# TOP بتاعة SQL Server قبل التنفيذ.

_LIMIT_RE = re.compile(r"\bLIMIT\s+(\d+)\s*$", re.IGNORECASE)
_SELECT_RE = re.compile(r"\bSELECT\s+(DISTINCT\s+)?", re.IGNORECASE)


def _translate(query):
    m = _LIMIT_RE.search(query.strip())
    if not m:
        return query
    n = m.group(1)
    head = query[: m.start()].rstrip()
    return _SELECT_RE.sub(lambda mm: mm.group(0) + f"TOP {n} ", head, count=1)


def _rows_to_dicts(cur):
    if cur.description is None:
        return []
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


# ---------------- الجداول ----------------

_BRANCH_DEFAULT = "DEFAULT (TRY_CONVERT(int, SESSION_CONTEXT(N'branch_id')))"

# (اسم الجدول, تعريف الأعمدة/القيود)
TABLES = [
    ("branches", """
        id INT IDENTITY(1,1) PRIMARY KEY,
        name NVARCHAR(255) NOT NULL UNIQUE,
        address NVARCHAR(255),
        phone NVARCHAR(50),
        is_active INT NOT NULL DEFAULT 1,
        created_at NVARCHAR(19) DEFAULT (CONVERT(varchar(19), GETDATE(), 120))
    """),
    ("users", """
        id INT IDENTITY(1,1) PRIMARY KEY,
        username NVARCHAR(100) NOT NULL UNIQUE,
        password_hash NVARCHAR(255) NOT NULL,
        role NVARCHAR(20) NOT NULL CHECK(role IN ('admin','supervisor','employee')),
        full_name NVARCHAR(255),
        branch_id INT NULL REFERENCES branches(id),
        must_change_password INT NOT NULL DEFAULT 0,
        dashboard_hidden_cards NVARCHAR(MAX),
        created_at NVARCHAR(19) DEFAULT (CONVERT(varchar(19), GETDATE(), 120))
    """),
    ("settings", """
        setting_key NVARCHAR(100) PRIMARY KEY,
        value NVARCHAR(MAX)
    """),
    ("customers", f"""
        id INT IDENTITY(1,1) PRIMARY KEY,
        name NVARCHAR(255) NOT NULL,
        phone NVARCHAR(50),
        address NVARCHAR(255),
        gender NVARCHAR(20),
        notes NVARCHAR(MAX),
        branch_id INT NOT NULL {_BRANCH_DEFAULT} REFERENCES branches(id),
        created_at NVARCHAR(19) DEFAULT (CONVERT(varchar(19), GETDATE(), 120))
    """),
    ("suppliers", f"""
        id INT IDENTITY(1,1) PRIMARY KEY,
        name NVARCHAR(255) NOT NULL,
        goods_type NVARCHAR(255),
        phone NVARCHAR(50),
        address NVARCHAR(255),
        notes NVARCHAR(MAX),
        branch_id INT NOT NULL {_BRANCH_DEFAULT} REFERENCES branches(id),
        created_at NVARCHAR(19) DEFAULT (CONVERT(varchar(19), GETDATE(), 120))
    """),
    ("products", f"""
        id INT IDENTITY(1,1) PRIMARY KEY,
        code NVARCHAR(50),
        name NVARCHAR(255) NOT NULL,
        model NVARCHAR(255),
        imei NVARCHAR(100),
        imei2 NVARCHAR(100),
        category NVARCHAR(100) DEFAULT N'جهاز',
        condition_type NVARCHAR(50) DEFAULT N'جديد',
        storage NVARCHAR(100),
        ram NVARCHAR(50),
        color NVARCHAR(50),
        wholesale_price FLOAT NOT NULL DEFAULT 0,
        sale_price FLOAT NOT NULL DEFAULT 0,
        max_discount FLOAT NOT NULL DEFAULT 0,
        quantity INT NOT NULL DEFAULT 1,
        supplier_id INT REFERENCES suppliers(id),
        status NVARCHAR(20) NOT NULL DEFAULT 'in_stock' CHECK(status IN ('in_stock','sold')),
        branch_id INT NOT NULL {_BRANCH_DEFAULT} REFERENCES branches(id),
        created_at NVARCHAR(19) DEFAULT (CONVERT(varchar(19), GETDATE(), 120))
    """),
    ("sales", f"""
        id INT IDENTITY(1,1) PRIMARY KEY,
        invoice_no NVARCHAR(100),
        customer_id INT REFERENCES customers(id),
        total FLOAT NOT NULL DEFAULT 0,
        paid_amount FLOAT NOT NULL DEFAULT 0,
        payment_type NVARCHAR(20) NOT NULL DEFAULT 'cash'
            CHECK(payment_type IN ('cash','wallet','instapay','visa','credit')),
        created_at NVARCHAR(19) DEFAULT (CONVERT(varchar(19), GETDATE(), 120)),
        created_by NVARCHAR(100),
        branch_id INT NOT NULL {_BRANCH_DEFAULT} REFERENCES branches(id)
    """),
    ("sale_items", f"""
        id INT IDENTITY(1,1) PRIMARY KEY,
        sale_id INT NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
        product_id INT REFERENCES products(id),
        product_name NVARCHAR(255),
        price FLOAT NOT NULL,
        cost_price FLOAT NOT NULL DEFAULT 0,
        qty INT NOT NULL DEFAULT 1,
        branch_id INT NOT NULL {_BRANCH_DEFAULT} REFERENCES branches(id)
    """),
    ("purchases", f"""
        id INT IDENTITY(1,1) PRIMARY KEY,
        supplier_id INT REFERENCES suppliers(id),
        total FLOAT NOT NULL DEFAULT 0,
        paid_amount FLOAT NOT NULL DEFAULT 0,
        payment_type NVARCHAR(20) NOT NULL DEFAULT 'cash' CHECK(payment_type IN ('cash','credit')),
        created_at NVARCHAR(19) DEFAULT (CONVERT(varchar(19), GETDATE(), 120)),
        created_by NVARCHAR(100),
        branch_id INT NOT NULL {_BRANCH_DEFAULT} REFERENCES branches(id)
    """),
    ("purchase_items", f"""
        id INT IDENTITY(1,1) PRIMARY KEY,
        purchase_id INT NOT NULL REFERENCES purchases(id) ON DELETE CASCADE,
        product_id INT REFERENCES products(id),
        product_name NVARCHAR(255),
        cost_price FLOAT NOT NULL,
        qty INT NOT NULL DEFAULT 1,
        branch_id INT NOT NULL {_BRANCH_DEFAULT} REFERENCES branches(id)
    """),
    ("treasury_accounts", f"""
        id INT IDENTITY(1,1) PRIMARY KEY,
        name NVARCHAR(255) NOT NULL,
        type NVARCHAR(50) NOT NULL DEFAULT 'cash',
        balance FLOAT NOT NULL DEFAULT 0,
        branch_id INT NOT NULL {_BRANCH_DEFAULT} REFERENCES branches(id)
    """),
    ("treasury_transactions", f"""
        id INT IDENTITY(1,1) PRIMARY KEY,
        account_id INT REFERENCES treasury_accounts(id),
        amount FLOAT NOT NULL,
        type NVARCHAR(10) NOT NULL CHECK(type IN ('in','out')),
        description NVARCHAR(MAX),
        date NVARCHAR(19) DEFAULT (CONVERT(varchar(19), GETDATE(), 120)),
        branch_id INT NOT NULL {_BRANCH_DEFAULT} REFERENCES branches(id)
    """),
    ("expenses", f"""
        id INT IDENTITY(1,1) PRIMARY KEY,
        category NVARCHAR(100),
        description NVARCHAR(MAX),
        amount FLOAT NOT NULL,
        date NVARCHAR(10) DEFAULT (CONVERT(varchar(10), GETDATE(), 120)),
        created_by NVARCHAR(100),
        treasury_transaction_id INT REFERENCES treasury_transactions(id),
        branch_id INT NOT NULL {_BRANCH_DEFAULT} REFERENCES branches(id)
    """),
    ("employees", f"""
        id INT IDENTITY(1,1) PRIMARY KEY,
        name NVARCHAR(255) NOT NULL,
        job_title NVARCHAR(255),
        salary FLOAT DEFAULT 0,
        phone NVARCHAR(50),
        hire_date NVARCHAR(10),
        notes NVARCHAR(MAX),
        branch_id INT NOT NULL {_BRANCH_DEFAULT} REFERENCES branches(id)
    """),
    ("advances", f"""
        id INT IDENTITY(1,1) PRIMARY KEY,
        employee_id INT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
        amount FLOAT NOT NULL,
        settled INT NOT NULL DEFAULT 0,
        date NVARCHAR(10) DEFAULT (CONVERT(varchar(10), GETDATE(), 120)),
        notes NVARCHAR(MAX),
        treasury_transaction_id INT REFERENCES treasury_transactions(id),
        branch_id INT NOT NULL {_BRANCH_DEFAULT} REFERENCES branches(id)
    """),
    ("debts", f"""
        id INT IDENTITY(1,1) PRIMARY KEY,
        party_type NVARCHAR(20) NOT NULL CHECK(party_type IN ('customer','supplier')),
        party_id INT,
        party_name NVARCHAR(255),
        amount FLOAT NOT NULL,
        original_amount FLOAT,
        debt_type NVARCHAR(20) NOT NULL CHECK(debt_type IN ('owed_to_me','i_owe')),
        due_date NVARCHAR(10),
        status NVARCHAR(20) NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','paid')),
        description NVARCHAR(MAX),
        created_at NVARCHAR(19) DEFAULT (CONVERT(varchar(19), GETDATE(), 120)),
        branch_id INT NOT NULL {_BRANCH_DEFAULT} REFERENCES branches(id)
    """),
    ("debt_payments", f"""
        id INT IDENTITY(1,1) PRIMARY KEY,
        debt_id INT NOT NULL REFERENCES debts(id) ON DELETE CASCADE,
        amount FLOAT NOT NULL,
        payment_date NVARCHAR(10) DEFAULT (CONVERT(varchar(10), GETDATE(), 120)),
        notes NVARCHAR(MAX),
        treasury_transaction_id INT REFERENCES treasury_transactions(id),
        created_at NVARCHAR(19) DEFAULT (CONVERT(varchar(19), GETDATE(), 120)),
        branch_id INT NOT NULL {_BRANCH_DEFAULT} REFERENCES branches(id)
    """),
    ("settlement_companies", f"""
        id INT IDENTITY(1,1) PRIMARY KEY,
        name NVARCHAR(255) NOT NULL,
        branch_id INT NOT NULL {_BRANCH_DEFAULT} REFERENCES branches(id),
        CONSTRAINT UQ_settlement_companies_branch_name UNIQUE(branch_id, name)
    """),
    ("company_settlements", f"""
        id INT IDENTITY(1,1) PRIMARY KEY,
        company_name NVARCHAR(255) NOT NULL,
        amount FLOAT NOT NULL,
        transaction_date NVARCHAR(10) DEFAULT (CONVERT(varchar(10), GETDATE(), 120)),
        expected_date NVARCHAR(10),
        status NVARCHAR(20) NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','collected')),
        collected_date NVARCHAR(10),
        notes NVARCHAR(MAX),
        treasury_transaction_id INT REFERENCES treasury_transactions(id),
        created_at NVARCHAR(19) DEFAULT (CONVERT(varchar(19), GETDATE(), 120)),
        branch_id INT NOT NULL {_BRANCH_DEFAULT} REFERENCES branches(id)
    """),
    ("maintenance", f"""
        id INT IDENTITY(1,1) PRIMARY KEY,
        customer_id INT,
        customer_name NVARCHAR(255),
        customer_phone NVARCHAR(50),
        device_name NVARCHAR(255),
        imei NVARCHAR(100),
        problem_description NVARCHAR(MAX),
        status NVARCHAR(20) NOT NULL DEFAULT 'received' CHECK(status IN ('received','in_progress','done','delivered')),
        cost FLOAT DEFAULT 0,
        customer_price FLOAT DEFAULT 0,
        sale_id INT REFERENCES sales(id),
        received_date NVARCHAR(10) DEFAULT (CONVERT(varchar(10), GETDATE(), 120)),
        delivered_date NVARCHAR(10),
        notes NVARCHAR(MAX),
        branch_id INT NOT NULL {_BRANCH_DEFAULT} REFERENCES branches(id)
    """),
    ("capital_entries", f"""
        id INT IDENTITY(1,1) PRIMARY KEY,
        amount FLOAT NOT NULL,
        description NVARCHAR(255),
        date NVARCHAR(19) DEFAULT (CONVERT(varchar(19), GETDATE(), 120)),
        created_by NVARCHAR(100),
        branch_id INT NOT NULL {_BRANCH_DEFAULT} REFERENCES branches(id)
    """),
    ("day_closings", f"""
        id INT IDENTITY(1,1) PRIMARY KEY,
        total_amount FLOAT NOT NULL DEFAULT 0,
        closed_by NVARCHAR(100),
        closed_at NVARCHAR(19) DEFAULT (CONVERT(varchar(19), GETDATE(), 120)),
        branch_id INT NOT NULL {_BRANCH_DEFAULT} REFERENCES branches(id)
    """),
    ("day_closing_items", f"""
        id INT IDENTITY(1,1) PRIMARY KEY,
        day_closing_id INT NOT NULL REFERENCES day_closings(id) ON DELETE CASCADE,
        account_id INT REFERENCES treasury_accounts(id),
        account_name NVARCHAR(255),
        amount FLOAT NOT NULL,
        branch_id INT NOT NULL {_BRANCH_DEFAULT} REFERENCES branches(id)
    """),
]

# الجداول اللي لازم تتفلتر تلقائي على الفرع الحالي (كل حاجة عدا
# branches/users/settings اللي المفروض تفضل ظاهرة بغض النظر عن الفرع
# المختار دلوقتي، خصوصًا إن تسجيل الدخول نفسه بيحتاج يقرا users قبل ما
# يكون فيه فرع محدد أصلًا).
_RLS_TABLES = [name for name, _ in TABLES if name not in ("branches", "users", "settings")]

_FUNCTION_SQL = """
CREATE FUNCTION dbo.fn_branch_access(@branch_id INT)
RETURNS TABLE
WITH SCHEMABINDING
AS
RETURN SELECT 1 AS fn_result
WHERE @branch_id = TRY_CONVERT(int, SESSION_CONTEXT(N'branch_id'))
   OR TRY_CONVERT(int, SESSION_CONTEXT(N'is_admin')) = 1
"""


def _table_exists(cur, name):
    cur.execute("SELECT 1 FROM sys.tables WHERE name = ?", (name,))
    return cur.fetchone() is not None


def _ensure_tables(conn):
    cur = conn.cursor()
    for name, cols in TABLES:
        if _table_exists(cur, name):
            continue
        cur.execute(f"CREATE TABLE {name} (\n{cols}\n)")
        conn.commit()


def _ensure_branch_function(conn):
    cur = conn.cursor()
    # الدالة دي "inline table-valued function" (جملة RETURN SELECT واحدة
    # من غير BEGIN/END) - نوعها في sys.objects هو 'IF' مش 'TF' (اللي ده
    # بس لدوال متعددة الجمل). الغلط في الشرط ده كان بيخلّي الكود يحاول
    # ينشئها من الأول كل مرة ويطلع خطأ "already exists".
    cur.execute("SELECT 1 FROM sys.objects WHERE type IN ('IF','TF') AND name='fn_branch_access'")
    if cur.fetchone() is None:
        cur.execute(_FUNCTION_SQL)
        conn.commit()


def _ensure_security_policy(conn):
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM sys.security_policies WHERE name='BranchAccessPolicy'")
    if cur.fetchone() is None:
        predicates = ", ".join(
            f"ADD FILTER PREDICATE dbo.fn_branch_access(branch_id) ON dbo.{t}"
            for t in _RLS_TABLES
        )
        cur.execute(f"CREATE SECURITY POLICY BranchAccessPolicy {predicates} WITH (STATE = ON)")
        conn.commit()
        return

    # الـ policy موجودة أصلًا من نسخة سابقة - لو اتضاف جدول جديد لـ
    # _RLS_TABLES بعد كده (زي day_closings/capital_entries) لازم نلحقه
    # بـ ALTER بدل ما نسيبه من غير عزل فروع (RLS) خالص.
    cur.execute("""
        SELECT OBJECT_NAME(sp.target_object_id)
        FROM sys.security_predicates sp
        JOIN sys.security_policies p ON p.object_id = sp.object_id
        WHERE p.name = 'BranchAccessPolicy'
    """)
    covered = {row[0] for row in cur.fetchall()}
    missing = [t for t in _RLS_TABLES if t not in covered]
    for t in missing:
        cur.execute(
            f"ALTER SECURITY POLICY BranchAccessPolicy ADD FILTER PREDICATE dbo.fn_branch_access(branch_id) ON dbo.{t}"
        )
    if missing:
        conn.commit()


def _add_column_if_missing(conn, table, column, coltype):
    """أعمدة اتضافت لجداول موجودة بالفعل بعد أول نسخة من السكيما - ALTER
    TABLE هنا ماليهوش تأثير على بيانات الصفوف الموجودة، القيمة
    الافتراضية بتتحط لهم تلقائي."""
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=? AND COLUMN_NAME=?",
        (table, column),
    )
    if cur.fetchone() is None:
        cur.execute(f"ALTER TABLE {table} ADD {column} {coltype}")
        conn.commit()


def _ensure_role_supervisor_allowed(conn):
    """قواعد بيانات اتعملت قبل إضافة دور "سوبر فايزر" لسه عندها CHECK
    CONSTRAINT قديم بيسمح بس بـ admin/employee على عمود users.role - اسم
    الـ constraint ده متولّد تلقائيًا من SQL Server (مالوش اسم ثابت)، فلازم
    نلاقيه بالاستعلام على sys.check_constraints قبل ما نمسحه ونحط واحد
    جديد يسمح بـ supervisor كمان."""
    cur = conn.cursor()
    cur.execute("""
        SELECT cc.name, cc.definition
        FROM sys.check_constraints cc
        WHERE cc.parent_object_id = OBJECT_ID('users')
          AND cc.definition LIKE '%role%'
    """)
    row = cur.fetchone()
    if row and "supervisor" in row[1].lower():
        return
    if row:
        cur.execute(f"ALTER TABLE users DROP CONSTRAINT [{row[0]}]")
    cur.execute(
        "ALTER TABLE users WITH CHECK ADD CONSTRAINT CK_users_role CHECK (role IN ('admin','supervisor','employee'))"
    )
    conn.commit()


def _ensure_filtered_unique_index(conn, table, column, index_name):
    """عمود لازم يكون فريد لو موجود، بس ممكن يبقى فاضي (NULL) في أغلب
    الصفوف - زي imei (الإكسسوارات مالهاش IMEI) أو code (منتجات قديمة من
    قبل ما نضيف الأكواد). UNIQUE CONSTRAINT عادي في SQL Server بيسمح
    بقيمة NULL واحدة بس (مش زي SQLite اللي بيسمح بأي عدد)، فأي صف تاني
    بقيمة NULL كان بيفشل بخطأ تكرار مفتاح ويسيب transaction عالق. الحل:
    فهرس فريد "مفلتر" بيتجاهل NULL تمامًا ومبيقيدش غيره."""
    cur = conn.cursor()
    cur.execute("""
        SELECT kc.name
        FROM sys.key_constraints kc
        JOIN sys.index_columns ic ON ic.object_id = kc.parent_object_id AND ic.index_id = kc.unique_index_id
        JOIN sys.columns col ON col.object_id = ic.object_id AND col.column_id = ic.column_id
        WHERE kc.parent_object_id = OBJECT_ID(?) AND col.name = ?
    """, (table, column))
    row = cur.fetchone()
    if row:
        cur.execute(f"ALTER TABLE {table} DROP CONSTRAINT [{row[0]}]")
        conn.commit()

    cur.execute(
        "SELECT 1 FROM sys.indexes WHERE name=? AND object_id=OBJECT_ID(?)", (index_name, table)
    )
    if cur.fetchone() is None:
        cur.execute(f"CREATE UNIQUE INDEX {index_name} ON {table}({column}) WHERE {column} IS NOT NULL")
        conn.commit()


def _ensure_general_accounts(conn):
    """الفروع اللي اتعملت قبل إضافة حساب 'الخزنة العامة' معدّاش عليها
    من _seed_branch_accounts (بترجع فورًا لو الفرع عنده حسابات أصلًا) -
    فبنلف هنا على كل الفروع ونضيفلها الحساب لو ناقص.

    الدالة دي بتتنادى في init_db() قبل ما يبقى فيه أي مستخدم مسجّل دخول
    (session context لسه مش admin ومفيش branch_id محدد) - يعني الـ RLS
    (BranchAccessPolicy) بتخبي كل صفوف treasury_accounts عن أي SELECT هنا،
    فحتى لو الحساب موجود فعلاً الفحص كان دايمًا بيرجّع "مش موجود" ويكرر
    الإدراج في كل تشغيل. لازم نرفع صلاحية admin مؤقتًا هنا بس عشان الفحص
    يشوف الصفوف الحقيقية، ونرجّعها زي ما كانت بعد كده."""
    cur = conn.cursor()
    cur.execute("EXEC sp_set_session_context @key=N'is_admin', @value=1, @read_only=0")
    try:
        cur.execute("SELECT id FROM branches")
        branch_ids = [row[0] for row in cur.fetchall()]
        added = False
        for branch_id in branch_ids:
            cur.execute(
                "SELECT 1 FROM treasury_accounts WHERE branch_id=? AND type='general'", (branch_id,)
            )
            if cur.fetchone() is None:
                cur.execute(
                    "INSERT INTO treasury_accounts (name, type, balance, branch_id) VALUES (?,?,?,?)",
                    ("الخزنة العامة (مرحّل يوميًا)", "general", 0, branch_id),
                )
                added = True
        if added:
            conn.commit()
    finally:
        cur.execute(
            "EXEC sp_set_session_context @key=N'is_admin', @value=?, @read_only=0",
            (1 if _current_is_admin else 0,),
        )
        conn.commit()


def generate_product_code(product_id):
    return f"P{product_id:05d}"


def init_db():
    """بتتنادى أول ما البرنامج يفتح: بتتأكد إن قاعدة البيانات والجداول
    وسياسة عزل الفروع (RLS) كلها موجودة، وبتزرع بيانات افتراضية (فرع
    رئيسي + مستخدمين) لو القاعدة جديدة تمامًا."""
    cfg = db_config.load_config()
    db_config.ensure_database_exists(cfg)

    conn = get_connection()
    _ensure_tables(conn)
    _add_column_if_missing(conn, "products", "max_discount", "FLOAT NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "products", "code", "NVARCHAR(50)")
    _add_column_if_missing(conn, "products", "imei2", "NVARCHAR(100)")
    # storage كانت NVARCHAR(50) قبل ما نوسّعها عشان تستحمل تفاصيل سعة
    # الشواحن/الباور بانك (زي "65W Fast Charging PD3.0") - توسيع العمود
    # آمن يتنفذ كل مرة حتى لو مقاسه صح خلاص.
    conn.cursor().execute("ALTER TABLE products ALTER COLUMN storage NVARCHAR(100)")
    conn.commit()
    _ensure_filtered_unique_index(conn, "products", "imei", "UQ_products_imei_notnull")
    _ensure_filtered_unique_index(conn, "products", "imei2", "UQ_products_imei2_notnull")
    _ensure_filtered_unique_index(conn, "products", "code", "UQ_products_code_notnull")
    _add_column_if_missing(conn, "maintenance", "customer_phone", "NVARCHAR(50)")
    _add_column_if_missing(conn, "treasury_transactions", "phone_number", "NVARCHAR(50)")
    _add_column_if_missing(conn, "treasury_transactions", "receipt_image_path", "NVARCHAR(500)")
    _add_column_if_missing(conn, "users", "must_change_password", "INT NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "users", "dashboard_hidden_cards", "NVARCHAR(MAX)")
    _ensure_role_supervisor_allowed(conn)
    _ensure_branch_function(conn)
    _ensure_security_policy(conn)

    _seed_defaults()
    _ensure_general_accounts(conn)


def _seed_branch_accounts(branch_id):
    """بتزرع الحسابات الافتراضية لأي فرع جديد (كاش/فيزا/محفظة/انستاباي)
    وشركة تحصيل افتراضية - بنحدد الـ branch_id صراحة هنا لأن ممكن نزرعهم
    قبل ما يبقى فيه فرع محدد في جلسة العمل الحالية."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM treasury_accounts WHERE branch_id=?", (branch_id,))
    if cur.fetchone() is None:
        cur.execute(
            "INSERT INTO treasury_accounts (name, type, balance, branch_id) VALUES (?,?,?,?)",
            ("الخزنة الرئيسية (كاش)", "cash", 0, branch_id),
        )
        cur.execute(
            "INSERT INTO treasury_accounts (name, type, balance, branch_id) VALUES (?,?,?,?)",
            ("فيزا/تحويلات", "visa", 0, branch_id),
        )
        cur.execute(
            "INSERT INTO treasury_accounts (name, type, balance, branch_id) VALUES (?,?,?,?)",
            ("محفظة إلكترونية", "wallet", 0, branch_id),
        )
        cur.execute(
            "INSERT INTO treasury_accounts (name, type, balance, branch_id) VALUES (?,?,?,?)",
            ("انستاباي", "instapay", 0, branch_id),
        )
        cur.execute(
            "INSERT INTO treasury_accounts (name, type, balance, branch_id) VALUES (?,?,?,?)",
            ("الخزنة العامة (مرحّل يوميًا)", "general", 0, branch_id),
        )
    cur.execute("SELECT 1 FROM settlement_companies WHERE branch_id=?", (branch_id,))
    if cur.fetchone() is None:
        cur.execute(
            "INSERT INTO settlement_companies (name, branch_id) VALUES (?,?)",
            ("مايلو", branch_id),
        )
    conn.commit()


def create_branch(name, address="", phone=""):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO branches (name, address, phone) VALUES (?,?,?)",
        (name, address, phone),
    )
    cur.execute("SELECT CAST(SCOPE_IDENTITY() AS INT)")
    branch_id = cur.fetchone()[0]
    conn.commit()
    _seed_branch_accounts(branch_id)
    return branch_id


def _seed_defaults():
    import hashlib

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM branches")
    if cur.fetchone()[0] == 0:
        main_branch_id = create_branch("الفرع الرئيسي")
    else:
        cur.execute("SELECT TOP 1 id FROM branches ORDER BY id")
        main_branch_id = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        def h(p):
            return hashlib.sha256(p.encode("utf-8")).hexdigest()
        cur.execute(
            """INSERT INTO users (username, password_hash, role, full_name, branch_id, must_change_password)
               VALUES (?,?,?,?,?,?)""",
            ("admin", h("admin123"), "admin", "المدير", None, 1),
        )
        cur.execute(
            """INSERT INTO users (username, password_hash, role, full_name, branch_id, must_change_password)
               VALUES (?,?,?,?,?,?)""",
            ("employee", h("emp123"), "employee", "موظف الشيفت", main_branch_id, 1),
        )
        conn.commit()

    defaults = {
        "shop_name": i18n.tr("app.default_shop_name"),
        "shop_phone": "",
        "shop_address": "",
        "monthly_sales_target": "",
        "theme": "dark",
        "language": "ar",
    }
    for k, v in defaults.items():
        cur.execute(
            "IF NOT EXISTS (SELECT 1 FROM settings WHERE setting_key=?) INSERT INTO settings (setting_key, value) VALUES (?,?)",
            (k, k, v),
        )
    conn.commit()


# الباسوردات الافتراضية الموثّقة في README لحسابات الاختبار المزروعة -
# مستخدمة كخط دفاع تاني (بجانب عمود must_change_password) عشان أي قاعدة
# بيانات قديمة اتعملت قبل إضافة العمود ده لسه تتحمي لو حد بيسجل دخول
# بالباسورد الافتراضي بالظبط.
DEFAULT_LOGIN_PASSWORDS = {"admin": "admin123", "employee": "emp123"}


def needs_password_change(user, plain_password):
    if user.get("must_change_password"):
        return True
    default_password = DEFAULT_LOGIN_PASSWORDS.get(user["username"])
    return default_password is not None and plain_password == default_password


def update_user_password(user_id, new_password_hash):
    execute(
        "UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?",
        (new_password_hash, user_id),
    )


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str():
    return datetime.date.today().strftime("%Y-%m-%d")


# ---------------- Generic helpers ----------------
#
# لازم كل استعلام يعمل commit (لو نجح) أو rollback (لو فشل) قبل ما
# يرجّع - عشان الاتصال (autocommit=False دايمًا) ميفضلش واقف على
# transaction عالق. لو حصل استثناء في نص عملية وسابنا transaction مفتوح
# من غير commit/rollback، القفل بتاعه بيقعّد أي عملية تانية (حتى من
# اتصال تاني) على نفس الصفوف/الجدول لحد ما البرنامج يتقفل - وده اللي
# كان بيحصل قبل الإصلاح ده (مثلاً IMEI مكرر بيوقف كل حاجة من غير أي
# رسالة خطأ واضحة).

def fetch_all(query, params=()):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(_translate(query), params)
        rows = _rows_to_dicts(cur)
        conn.commit()
        return rows
    except Exception:
        conn.rollback()
        raise


def fetch_one(query, params=()):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(_translate(query), params)
        if cur.description is None:
            conn.commit()
            return None
        cols = [c[0] for c in cur.description]
        row = cur.fetchone()
        conn.commit()
        return dict(zip(cols, row)) if row else None
    except Exception:
        conn.rollback()
        raise


def execute_autocommit(query, params=(), timeout=120):
    """لتنفيذ أوامر إدارية زي BACKUP DATABASE اللي SQL Server مبيسمحش
    بتنفيذها جوه transaction مفتوح (والاتصال العادي بتاعنا autocommit=False
    دايمًا) - بيفتح اتصال منفصل مؤقت بوضع autocommit ويقفله بعد كده."""
    if not db_config.is_configured():
        raise NotConfiguredError("لسه مفيش إعداد اتصال بقاعدة بيانات SQL Server")
    cfg = db_config.load_config()
    conn = pyodbc.connect(db_config.build_connection_string(cfg), timeout=timeout, autocommit=True)
    try:
        cur = conn.cursor()
        cur.execute(query, params)
    finally:
        conn.close()


_VALUES_RE = re.compile(r"\bVALUES\b", re.IGNORECASE)


def execute(query, params=()):
    conn = get_connection()
    cur = conn.cursor()
    try:
        translated = _translate(query)
        lastrowid = None
        if translated.lstrip()[:6].upper() == "INSERT" and _VALUES_RE.search(translated):
            # SCOPE_IDENTITY() في استعلام منفصل بعد الـ INSERT مش موثوق فيه
            # مع pyodbc/الـ ODBC driver - أحيانًا بيرجع NULL حتى لو الإدراج
            # نجح، لإن كل استدعاء execute() بيتنفذ زي "scope" منفصل. OUTPUT
            # INSERTED.id جوه نفس جملة الـ INSERT مضمونة 100% لإنها نفس الأمر.
            translated = _VALUES_RE.sub("OUTPUT INSERTED.id VALUES", translated, count=1)
            cur.execute(translated, params)
            row = cur.fetchone()
            lastrowid = int(row[0]) if row and row[0] is not None else None
        else:
            cur.execute(translated, params)
        conn.commit()
        return lastrowid
    except Exception:
        conn.rollback()
        raise


# ---------------- Dashboard aggregates ----------------

def dashboard_summary(date_from=None, date_to=None):
    """date_from/date_to (نص "YYYY-MM-DD") بيفلتروا الأرقام اللي طبيعتها
    "حركة خلال فترة" (الإيرادات/المصروفات/الربح/المشتريات) بس - أما أرقام
    "الرصيد الحالي" (المخزون والديون المعلقة) فهي بطبيعتها لحظة آنية
    (رصيد دلوقتي مش حركة حصلت خلال فترة معيّنة)، فبتفضل زي ما هي بغض
    النظر عن الفلتر، زي أي نظام مخزون عادي."""
    ranged = bool(date_from and date_to)
    end = f"{date_to} 23:59:59" if ranged else None

    if ranged:
        revenue = fetch_one(
            "SELECT COALESCE(SUM(total),0) v FROM sales WHERE created_at>=? AND created_at<=?",
            (date_from, end),
        )["v"]
        expenses_total = fetch_one(
            "SELECT COALESCE(SUM(amount),0) v FROM expenses WHERE date>=? AND date<=?",
            (date_from, date_to),
        )["v"]
        purchases_cost = fetch_one(
            "SELECT COALESCE(SUM(total),0) v FROM purchases WHERE created_at>=? AND created_at<=?",
            (date_from, end),
        )["v"]
        cogs = fetch_one("""
            SELECT COALESCE(SUM(si.cost_price * si.qty),0) v
            FROM sale_items si
            JOIN sales s ON s.id = si.sale_id
            WHERE s.created_at>=? AND s.created_at<=?
        """, (date_from, end))["v"]
    else:
        revenue = fetch_one("SELECT COALESCE(SUM(total),0) v FROM sales")["v"]
        expenses_total = fetch_one("SELECT COALESCE(SUM(amount),0) v FROM expenses")["v"]
        purchases_cost = fetch_one("SELECT COALESCE(SUM(total),0) v FROM purchases")["v"]
        cogs = fetch_one("""
            SELECT COALESCE(SUM(si.cost_price * si.qty),0) v
            FROM sale_items si
        """)["v"]

    profit = revenue - cogs - expenses_total
    stock_qty = fetch_one("SELECT COALESCE(SUM(quantity),0) v FROM products WHERE status='in_stock'")["v"]
    stock_value_sale = fetch_one("SELECT COALESCE(SUM(sale_price*quantity),0) v FROM products WHERE status='in_stock'")["v"]
    stock_value_cost = fetch_one("SELECT COALESCE(SUM(wholesale_price*quantity),0) v FROM products WHERE status='in_stock'")["v"]
    owed_to_me = fetch_one("SELECT COALESCE(SUM(amount),0) v FROM debts WHERE debt_type='owed_to_me' AND status='pending'")["v"]
    i_owe = fetch_one("SELECT COALESCE(SUM(amount),0) v FROM debts WHERE debt_type='i_owe' AND status='pending'")["v"]
    return {
        "revenue": revenue,
        "expenses": expenses_total,
        "profit": profit,
        "purchases_cost": purchases_cost,
        "stock_qty": stock_qty,
        "stock_value_sale": stock_value_sale,
        "stock_value_cost": stock_value_cost,
        "owed_to_me": owed_to_me,
        "i_owe": i_owe,
    }


def get_dashboard_hidden_cards(user_id):
    row = fetch_one("SELECT dashboard_hidden_cards FROM users WHERE id=?", (user_id,))
    if not row or not row["dashboard_hidden_cards"]:
        return set()
    try:
        return set(json.loads(row["dashboard_hidden_cards"]))
    except (ValueError, TypeError):
        return set()


def set_dashboard_hidden_cards(user_id, hidden_keys):
    execute(
        "UPDATE users SET dashboard_hidden_cards=? WHERE id=?",
        (json.dumps(sorted(hidden_keys)), user_id),
    )

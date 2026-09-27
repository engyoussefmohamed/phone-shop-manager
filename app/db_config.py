"""
إعدادات الاتصال بقاعدة بيانات Microsoft SQL Server.
بيتخزن الإعداد في ملف db_config.json جنب البرنامج (أو جنب ملف الـ exe لو
البرنامج شغال كملف مبني)، عشان كل جهاز يقدر يتوصل بسيرفر مختلف (أو بنفس
السيرفر لو أكتر من جهاز/فرع بيشتغلوا على نفس القاعدة).
"""
import json
import os
import sys

import pyodbc

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_PATH = os.path.join(BASE_DIR, "db_config.json")

DEFAULT_CONFIG = {
    "server": "",          # مثال: localhost\SQLEXPRESS أو 192.168.1.10
    "port": "",            # اختياري - سيبه فاضي لو بتستخدم اسم انستانس زي SQLEXPRESS
    "database": "PhoneShopManager",
    "auth": "sql",         # "sql" أو "windows"
    "username": "",
    "password": "",
    "driver": "",           # اختياري - لو فاضي بيتم اكتشافه تلقائي
}

_PREFERRED_DRIVERS = [
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "ODBC Driver 13 for SQL Server",
    "SQL Server Native Client 11.0",
    "SQL Server",
]


def detect_driver():
    installed = set(pyodbc.drivers())
    for name in _PREFERRED_DRIVERS:
        if name in installed:
            return name
    return _PREFERRED_DRIVERS[-1]


def is_configured():
    """مش بس نتأكد إن الملف موجود - لازم نتأكد كمان إن فيه server وdatabase
    متسجلين فعلاً، عشان ملف db_config.json بقيم فاضية (زي اللي بيتوزع مع
    المشروع) ميخليش شاشة إعداد الاتصال الأولى تتخطّى غلط."""
    if not os.path.exists(CONFIG_PATH):
        return False
    cfg = load_config()
    return bool((cfg.get("server") or "").strip()) and bool((cfg.get("database") or "").strip())


def load_config():
    if not os.path.exists(CONFIG_PATH):
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_CONFIG)
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(data or {})
    return cfg


def save_config(cfg):
    to_save = dict(DEFAULT_CONFIG)
    to_save.update(cfg or {})
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(to_save, f, ensure_ascii=False, indent=2)


def _server_part(cfg):
    server = (cfg.get("server") or "").strip()
    port = (cfg.get("port") or "").strip()
    if port:
        return f"{server},{port}"
    return server


def build_connection_string(cfg, database=None):
    driver = (cfg.get("driver") or "").strip() or detect_driver()
    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={_server_part(cfg)}",
        f"DATABASE={database or cfg.get('database') or 'PhoneShopManager'}",
        "Encrypt=yes",
        "TrustServerCertificate=yes",
    ]
    if (cfg.get("auth") or "sql") == "windows":
        parts.append("Trusted_Connection=yes")
    else:
        parts.append(f"UID={cfg.get('username', '')}")
        parts.append(f"PWD={cfg.get('password', '')}")
    return ";".join(parts) + ";"


def test_connection(cfg):
    """بيحاول يتصل بقاعدة master (موجودة دايمًا) للتأكد إن بيانات الاتصال
    صحيحة قبل ما نحاول ننشئ/نفتح قاعدة بيانات البرنامج نفسها."""
    try:
        conn_str = build_connection_string(cfg, database="master")
        conn = pyodbc.connect(conn_str, timeout=5)
        conn.close()
        return True, "تم الاتصال بنجاح"
    except Exception as e:
        return False, str(e)


def data_dir():
    """المسار اللي هتتخزن فيه ملفات قاعدة البيانات الفعلية (.mdf/.ldf) -
    جوه فولدر db\\ بتاع المشروع، جنب مكان ملف SQLite القديم بالظبط.
    ده بيشتغل بس لو SQL Server شغال على نفس الجهاز اللي فيه المشروع
    (السيرفر هو اللي فعليًا بيكتب الملفات في المسار ده، مش البرنامج)."""
    path = os.path.join(BASE_DIR, "db")
    os.makedirs(path, exist_ok=True)
    return path


def receipts_dir():
    """المسار اللي هتتخزن فيه صور إيصالات التحويلات (انستاباي/محفظة/فيزا)
    اللي بتتضاف من شاشة الخزنة - جنب البرنامج نفسه (أو جنب الـ exe لو
    البرنامج شغال كملف مبني)، نفس فكرة data_dir() بالظبط."""
    path = os.path.join(BASE_DIR, "receipts")
    os.makedirs(path, exist_ok=True)
    return path


def ensure_database_exists(cfg):
    conn_str = build_connection_string(cfg, database="master")
    conn = pyodbc.connect(conn_str, timeout=5)
    conn.autocommit = True
    try:
        db_name = cfg.get("database") or "PhoneShopManager"
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM sys.databases WHERE name = ?", (db_name,))
        if cur.fetchone() is not None:
            return  # القاعدة موجودة بالفعل - مانلمسش مكان ملفاتها

        path = data_dir()
        mdf_path = os.path.join(path, f"{db_name}.mdf")
        ldf_path = os.path.join(path, f"{db_name}_log.ldf")
        cur.execute(
            f"""
            CREATE DATABASE [{db_name}]
            ON PRIMARY (NAME = N'{db_name}', FILENAME = N'{mdf_path}')
            LOG ON (NAME = N'{db_name}_log', FILENAME = N'{ldf_path}')
            """
        )
    finally:
        conn.close()

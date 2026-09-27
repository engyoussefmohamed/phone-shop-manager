"""
إدارة فترة التجربة (7 أيام) بشكل مقاوم للتلاعب البسيط:
- بنسجل تاريخ أول تشغيل + آخر تشغيل، مشفرين بمفتاح مشتق من بصمة الجهاز
  (فملف التجربة لو اتنقل لجهاز تاني هيبقى غير صالح تلقائياً).
- بنحتفظ بنسخة احتياطية في مكانين مختلفين على الجهاز. لو نسخة اتمسحت
  ولسه فيه التانية، بنعتمد عليها. لو الاتنين مختلفين، بناخد الأسوأ للعميل
  (الأقرب للانتهاء) عشان منديش فرصة لإعادة ضبط التجربة بمسح ملف واحد.
- لو المستخدم رجّع ساعة الجهاز للخلف، النظام بيكتشف إن "آخر تشغيل" المسجل
  أكبر من الوقت الحالي، فبيعتبر التجربة انتهت فوراً (منع التحايل بالساعة).
"""
import base64
import hashlib
import json
import os
import time

from . import hwid

TRIAL_DAYS = 7

APPDATA_DIR = os.environ.get("APPDATA") or os.path.expanduser("~")
PROGRAMDATA_DIR = os.environ.get("PROGRAMDATA") or os.path.expanduser("~")

LOCATION_1 = os.path.join(APPDATA_DIR, "PSM_Data", ".sys_cache")
LOCATION_2 = os.path.join(PROGRAMDATA_DIR, "PSM_Shared", ".idx_cache")


def _key():
    raw = hwid.get_hardware_id().encode("utf-8")
    return hashlib.sha256(raw).digest()


def _xor_bytes(data, key):
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def _encrypt(obj):
    raw = json.dumps(obj).encode("utf-8")
    enc = _xor_bytes(raw, _key())
    return base64.b64encode(enc).decode("utf-8")


def _decrypt(token):
    try:
        enc = base64.b64decode(token.encode("utf-8"))
        raw = _xor_bytes(enc, _key())
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def _read(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            token = f.read().strip()
        return _decrypt(token)
    except Exception:
        return None


def _write(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        token = _encrypt(data)
        if os.name == "nt":
            os.system(f'attrib -h "{path}" >nul 2>&1')
        with open(path, "w", encoding="utf-8") as f:
            f.write(token)
        if os.name == "nt":
            os.system(f'attrib +h "{path}" >nul 2>&1')
    except OSError:
        # ملف مقفول مؤقتاً (نسخة تانية شغالة، برنامج حماية بيفحصه، إلخ).
        # منسيبش البرنامج يقفل بسبب كده - التجربة هتتسجل صح المرة الجاية.
        pass


def _merge(d1, d2):
    """يرجع أسوأ حالة للمستخدم بين النسختين (أقدم first_run وأكبر last_seen)."""
    if d1 is None:
        return d2
    if d2 is None:
        return d1
    return {
        "first_run": min(d1["first_run"], d2["first_run"]),
        "last_seen": max(d1["last_seen"], d2["last_seen"]),
    }


def get_trial_status():
    """
    يرجع dict فيه:
      started: bool
      expired: bool
      days_left: int
      tampered: bool  (لو اكتشفنا محاولة تلاعب بالساعة)
    """
    now = time.time()
    d1 = _read(LOCATION_1)
    d2 = _read(LOCATION_2)
    data = _merge(d1, d2)

    tampered = False
    if data is None:
        data = {"first_run": now, "last_seen": now}
    else:
        if now < data["last_seen"] - 60:  # الساعة اترجعت للخلف
            tampered = True
            now = data["last_seen"]
        data["last_seen"] = max(data["last_seen"], now)

    _write(LOCATION_1, data)
    _write(LOCATION_2, data)

    elapsed_seconds = data["last_seen"] - data["first_run"]
    elapsed_days = elapsed_seconds / 86400.0
    days_left = max(0, int(TRIAL_DAYS - elapsed_days))
    expired = elapsed_days >= TRIAL_DAYS

    return {
        "started": True,
        "expired": expired,
        "days_left": days_left,
        "tampered": tampered,
    }

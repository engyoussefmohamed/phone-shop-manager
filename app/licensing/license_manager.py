"""
نظام الترخيص الدائم بعد التجربة.
مبني على توقيع رقمي (RSA) غير متماثل:
- المفتاح الخاص (private_key.pem) يفضل عندك انت بس (في dev_tools)، ومبيتشحنش
  مع البرنامج للعميل نهائياً.
- المفتاح العام (public_key.pem) بيتشحن جوه البرنامج، وبيستخدم للتحقق فقط
  (مينفعش حد يزوّر ترخيص بيه لأنه مش قادر يوقّع بيه، بس قادر يتأكد من التوقيع).

آلية العمل:
1. العميل بيفتح شاشة الترخيص، البرنامج بيوريله "كود الجهاز" (hwid.get_device_code).
2. العميل يبعتلك الكود.
3. انت بتشغل dev_tools/generate_license.py بالكود ده، وبيطلعلك ملف .lic موقّع.
4. العميل يستورد ملف .lic من شاشة الإعدادات، والبرنامج يتحقق من التوقيع
   ومن تطابق بصمة الجهاز قبل ما يفعّل الترخيص.
"""
import base64
import json
import os

from . import hwid

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_KEY_PATH = os.path.join(os.path.dirname(__file__), "keys", "public_key.pem")

LICENSE_STORE_DIR = os.path.join(
    os.environ.get("APPDATA") or os.path.expanduser("~"), "PSM_Data"
)
LICENSE_STORE_PATH = os.path.join(LICENSE_STORE_DIR, "license.lic")


def _load_public_key():
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    with open(PUBLIC_KEY_PATH, "rb") as f:
        return load_pem_public_key(f.read())


def _verify_signature(payload_bytes, signature_bytes):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.exceptions import InvalidSignature

    public_key = _load_public_key()
    try:
        public_key.verify(
            signature_bytes,
            payload_bytes,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
        return True
    except InvalidSignature:
        return False
    except Exception:
        return False


def parse_license_file(path):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()
    envelope = json.loads(base64.b64decode(content))
    return envelope  # {"data": {...}, "signature": "base64..."}


def verify_license_data(envelope):
    """يرجع (valid: bool, info: dict, reason: str)"""
    try:
        data = envelope["data"]
        signature = base64.b64decode(envelope["signature"])
        payload_bytes = json.dumps(data, sort_keys=True).encode("utf-8")

        if not _verify_signature(payload_bytes, signature):
            return False, {}, "توقيع الترخيص غير صالح"

        current_hwid = hwid.get_hardware_id()
        if data.get("hwid") != current_hwid:
            return False, {}, "الترخيص ده مربوط بجهاز تاني"

        expires_at = data.get("expires_at")
        if expires_at:
            import datetime
            if datetime.date.today().isoformat() > expires_at:
                return False, data, "الترخيص منتهي الصلاحية"

        return True, data, "صالح"
    except Exception as e:
        return False, {}, f"ملف ترخيص غير صالح ({e})"


def install_license_file(source_path):
    """ينسخ ملف الترخيص لمكانه الدائم بعد التحقق منه."""
    envelope = parse_license_file(source_path)
    valid, info, reason = verify_license_data(envelope)
    if not valid:
        return False, reason
    os.makedirs(LICENSE_STORE_DIR, exist_ok=True)
    with open(source_path, "r", encoding="utf-8") as src:
        content = src.read()
    with open(LICENSE_STORE_PATH, "w", encoding="utf-8") as dst:
        dst.write(content)
    return True, "تم تفعيل الترخيص بنجاح"


def get_current_license_status():
    if not os.path.exists(LICENSE_STORE_PATH):
        return False, {}, "لا يوجد ترخيص مفعّل"
    try:
        envelope = parse_license_file(LICENSE_STORE_PATH)
        return verify_license_data(envelope)
    except Exception as e:
        return False, {}, f"خطأ في قراءة الترخيص ({e})"

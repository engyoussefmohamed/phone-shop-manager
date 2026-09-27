"""
[أداة للمطوّر فقط - متتشحنش للعميل]
بتولّد ملف ترخيص (.lic) لعميل معيّن، موقّع بمفتاحك الخاص، ومربوط بجهازه فقط.

الاستخدام (الطريقة الأسهل - ملف طلب الترخيص):
    python generate_license.py --request-file "طلب_ترخيص_XXXX.txt" --days 365

    العميل بيصدّر الملف ده من شاشة الإعدادات > الترخيص > "تصدير ملف طلب
    الترخيص" وبيبعتهولك واتساب/إيميل. الأداة بتاخد منه اسم المحل والـHWID
    الكامل تلقائياً.

الاستخدام اليدوي (لو معاك الـHWID الكامل مباشرة):
    python generate_license.py --hwid <الـHWID الكامل> --customer "اسم العميل" --days 365

    ملحوظة: "كود الجهاز" المختصر اللي بيظهر في الشاشة (زي ABCD-1234-EFGH)
    مش كافي هنا - محتاج الـHWID الكامل (سلسلة طويلة)، وده بالظبط اللي
    بيوفره لك ملف طلب الترخيص.
"""
import argparse
import base64
import datetime
import json
import os
import sys

DEV_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(DEV_TOOLS_DIR)
sys.path.insert(0, PROJECT_ROOT)

PRIVATE_KEY_PATH = os.path.join(DEV_TOOLS_DIR, "private_key.pem")
OUTPUT_DIR = os.path.join(DEV_TOOLS_DIR, "issued_licenses")


def sign_payload(payload_bytes):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    with open(PRIVATE_KEY_PATH, "rb") as f:
        private_key = load_pem_private_key(f.read(), password=None)

    signature = private_key.sign(
        payload_bytes,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH,
        ),
        hashes.SHA256(),
    )
    return signature


def main():
    parser = argparse.ArgumentParser(description="توليد ملف ترخيص موقّع لعميل")
    parser.add_argument("--request-file", help="ملف طلب الترخيص (.txt) اللي بعته العميل من شاشة الإعدادات")
    parser.add_argument("--hwid", help="بصمة الجهاز الكاملة (لو مش مستخدم --request-file)")
    parser.add_argument("--customer", help="اسم العميل/المحل (لو مش مستخدم --request-file)")
    parser.add_argument("--days", type=int, default=0, help="مدة الترخيص بالأيام (0 = بدون انتهاء)")
    args = parser.parse_args()

    hwid_value = args.hwid
    customer_value = args.customer

    if args.request_file:
        with open(args.request_file, "r", encoding="utf-8") as f:
            request_data = json.load(f)
        hwid_value = request_data["hwid"]
        customer_value = args.customer or request_data.get("shop_name") or request_data.get("device_code")
        print(f"تم قراءة طلب الترخيص: المحل = {request_data.get('shop_name') or '(بدون اسم)'}, "
              f"كود الجهاز = {request_data.get('device_code')}")

    if not hwid_value or not customer_value:
        parser.error("لازم تحدد --request-file، أو --hwid و--customer مع بعض")

    data = {
        "hwid": hwid_value,
        "customer": customer_value,
        "issued_at": datetime.date.today().isoformat(),
        "expires_at": (
            (datetime.date.today() + datetime.timedelta(days=args.days)).isoformat()
            if args.days > 0 else None
        ),
    }
    payload_bytes = json.dumps(data, sort_keys=True).encode("utf-8")
    signature = sign_payload(payload_bytes)

    envelope = {
        "data": data,
        "signature": base64.b64encode(signature).decode("utf-8"),
    }
    content = base64.b64encode(json.dumps(envelope).encode("utf-8")).decode("utf-8")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    safe_name = "".join(c for c in customer_value if c.isalnum() or c in (" ", "_", "-")).strip() or "customer"
    out_path = os.path.join(OUTPUT_DIR, f"{safe_name}.lic")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    print("تم إنشاء ملف الترخيص:", out_path)
    print("ابعته للعميل يستورده من شاشة الإعدادات > تفعيل الترخيص.")


if __name__ == "__main__":
    main()

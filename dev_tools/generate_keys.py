"""
[أداة للمطوّر فقط - متتشحنش للعميل]
بتولّد زوج مفاتيح RSA مرة واحدة بس لكل المشروع:
- private_key.pem  -> يفضل عندك انت بس، بيه بتوقّع ملفات التراخيص.
- public_key.pem   -> بينسخ جوه app/licensing/keys/ ويتشحن مع البرنامج.

شغّلها مرة واحدة بس أول ما تبدأ المشروع. لو شغلتها تاني هتغيّر المفاتيح
وأي ترخيص قديم اتوزع هيبقى مش شغال (فخليها متشغلهاش تاني غير لو عايز
تلغي كل التراخيص القديمة عمداً).
"""
import os
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

DEV_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(DEV_TOOLS_DIR)
PRIVATE_KEY_PATH = os.path.join(DEV_TOOLS_DIR, "private_key.pem")
PUBLIC_KEY_DIR = os.path.join(PROJECT_ROOT, "app", "licensing", "keys")
PUBLIC_KEY_PATH = os.path.join(PUBLIC_KEY_DIR, "public_key.pem")


def main():
    if os.path.exists(PRIVATE_KEY_PATH):
        print("private_key.pem موجود بالفعل. امسحه يدوياً لو عايز تولّد مفاتيح جديدة (هيلغي كل التراخيص القديمة).")
        return

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    os.makedirs(DEV_TOOLS_DIR, exist_ok=True)
    with open(PRIVATE_KEY_PATH, "wb") as f:
        f.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

    os.makedirs(PUBLIC_KEY_DIR, exist_ok=True)
    with open(PUBLIC_KEY_PATH, "wb") as f:
        f.write(
            key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )

    print("تم توليد المفاتيح:")
    print(" - المفتاح الخاص (سرّي، حافظ عليه):", PRIVATE_KEY_PATH)
    print(" - المفتاح العام (بيتشحن مع البرنامج):", PUBLIC_KEY_PATH)


if __name__ == "__main__":
    main()

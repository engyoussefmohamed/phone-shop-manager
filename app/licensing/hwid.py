"""
بصمة الجهاز (Hardware ID) - تُستخدم لربط الترخيص بجهاز واحد بالتحديد.
بتجمع أكتر من معرّف هارديوير (UUID الجهاز + سيريال الديسك + الماك أدريس)
وبتعمل منها hash واحد ثابت. لو أي معرّف اتغيّر لوحده (مثلاً الماك أدريس بسبب
كارت شبكة جديد) الباقي بيفضل يثبّت الهوية، فالنظام بيقارن بتشابه جزئي مش
تطابق حرفي 100% عشان ميبقاش هش صارم زيادة عن اللزوم.
"""
import hashlib
import json
import platform
import subprocess
import uuid
import datetime


def _run(cmd):
    try:
        out = subprocess.check_output(
            cmd, shell=True, stderr=subprocess.DEVNULL, timeout=5
        )
        return out.decode(errors="ignore").strip()
    except Exception:
        return ""


def _windows_ids():
    ids = []
    # UUID بتاع الجهاز (motherboard/product)
    uid = _run("wmic csproduct get UUID")
    if uid:
        lines = [l.strip() for l in uid.splitlines() if l.strip() and "UUID" not in l]
        if lines:
            ids.append(lines[0])
    # سيريال الديسك الأساسي
    disk = _run("wmic diskdrive get SerialNumber")
    if disk:
        lines = [l.strip() for l in disk.splitlines() if l.strip() and "SerialNumber" not in l]
        if lines:
            ids.append(lines[0])
    # سيريال البايوس
    bios = _run("wmic bios get SerialNumber")
    if bios:
        lines = [l.strip() for l in bios.splitlines() if l.strip() and "SerialNumber" not in l]
        if lines:
            ids.append(lines[0])
    return ids


def _generic_ids():
    ids = [platform.node(), platform.machine(), platform.processor(), str(uuid.getnode())]
    return [i for i in ids if i]


def get_raw_identifiers():
    ids = []
    if platform.system() == "Windows":
        ids.extend(_windows_ids())
    ids.extend(_generic_ids())
    # شيل أي حاجة فاضية أو placeholder شائعة
    cleaned = [i for i in ids if i and i.lower() not in ("", "none", "to be filled by o.e.m.")]
    return cleaned


def get_hardware_id():
    """يرجع بصمة جهاز ثابتة (hex string) تتغير لو الجهاز اتغير فعلاً."""
    ids = get_raw_identifiers()
    combined = "|".join(sorted(ids))
    if not combined:
        combined = platform.node() or "unknown-device"
    digest = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    return digest


def get_device_code():
    """كود مختصر وسهل نسخه/إرساله للمطوّر عشان يولّد الترخيص."""
    full = get_hardware_id()
    # نعرضه كأربع مجموعات عشان يبقى سهل قراءته وكتابته
    short = full[:16].upper()
    return "-".join(short[i:i + 4] for i in range(0, len(short), 4))


def export_request_file(path, shop_name=""):
    """
    بيحفظ ملف نصي صغير فيه كل البيانات اللي محتاجها المطوّر عشان يولّد
    ترخيص (الـHWID الكامل + الكود المختصر + اسم المحل لو موجود). العميل
    يبعت الملف ده بدل ما ينسخ الـHWID الطويل يدوياً وممكن يغلط فيه.
    """
    data = {
        "shop_name": shop_name,
        "device_code": get_device_code(),
        "hwid": get_hardware_id(),
        "requested_at": datetime.date.today().isoformat(),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


if __name__ == "__main__":
    print("Device code:", get_device_code())
    print("Full HWID:", get_hardware_id())

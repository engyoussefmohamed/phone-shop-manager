"""
نظام إدارة محل التلفونات - نقطة تشغيل البرنامج
تشغيل: python main.py
"""
import glob
import os
import sys
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QSplashScreen

from app import database as db
from app import db_config
from app import i18n
from app.utils import palette
from app.utils.branding import splash_pixmap
from app.utils.styles import DARK_QSS, get_stylesheet
from app.licensing import license_manager, trial
from app.ui.db_setup_dialog import DbSetupDialog
from app.ui.license_gate import LicenseGateDialog
from app.ui.login_window import LoginWindow
from app.ui.main_window import MainWindow
from PySide6.QtWidgets import QMessageBox

SPLASH_MIN_SECONDS = 1.5


def load_fonts():
    """بيسجّل خطوط IBM Plex Sans Arabic المضمّنة مع البرنامج (app/assets/fonts)
    عند QFontDatabase عشان تبقى متاحة لأي widget حتى لو مش متثبتة على الجهاز."""
    fonts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app", "assets", "fonts")
    for path in glob.glob(os.path.join(fonts_dir, "*.ttf")):
        QFontDatabase.addApplicationFont(path)


def check_license_and_trial():
    """
    يرجع trial_days_left (int أو None لو مرخّص بشكل دائم) لو مسموح نكمل،
    أو None + إغلاق البرنامج لو مفيش ترخيص ولا تجربة سارية.
    """
    valid, data, reason = license_manager.get_current_license_status()
    if valid:
        return None  # مرخّص دائم، من غير عداد تجربة

    status = trial.get_trial_status()
    if not status["expired"] and not status["tampered"]:
        return status["days_left"]

    reason_text = i18n.tr("license_gate.reason_tampered" if status["tampered"] else "license_gate.default_reason")
    gate = LicenseGateDialog(reason=reason_text)
    if gate.exec() and gate.activated:
        return None
    return "EXIT"


def main():
    app = QApplication(sys.argv)
    load_fonts()
    # افتراضي (عربي/غامق) لحد ما نقدر نقرا الاختيار المحفوظ من قاعدة
    # البيانات - محتاجينه من دلوقتي عشان دياولوجات زي إعداد الاتصال
    # وبوابة الترخيص بتشتغل قبل ما تكون فيه قاعدة بيانات أصلًا.
    app.setLayoutDirection(Qt.RightToLeft)
    app.setStyleSheet(DARK_QSS)

    splash = QSplashScreen(splash_pixmap())
    splash.show()
    splash_started_at = time.time()
    app.processEvents()

    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app", "assets", "cortex_icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    while True:
        if not db_config.is_configured():
            dlg = DbSetupDialog()
            if not dlg.exec():
                sys.exit(0)
        try:
            db.init_db()
            break
        except Exception as e:
            resp = QMessageBox.critical(
                None, "خطأ في الاتصال بقاعدة البيانات",
                f"مقدرش أتصل بقاعدة البيانات أو أجهّزها:\n{e}\n\n"
                "دوس OK عشان تراجع إعدادات الاتصال، أو Cancel عشان تقفل البرنامج.",
                QMessageBox.Ok | QMessageBox.Cancel,
            )
            if resp != QMessageBox.Ok:
                sys.exit(0)
            dlg = DbSetupDialog()
            if not dlg.exec():
                sys.exit(0)

    # دلوقتي قاعدة البيانات جاهزة - نقرا اختيار الثيم/اللغة المحفوظ ونطبّقه
    # قبل ما نفتح شاشة الدخول (تسجيل الدخول وكل حاجة بعده لازم تطلع بيه).
    theme_row = db.fetch_one("SELECT value FROM settings WHERE setting_key='theme'")
    theme = theme_row["value"] if theme_row and theme_row["value"] else "dark"
    lang_row = db.fetch_one("SELECT value FROM settings WHERE setting_key='language'")
    lang = lang_row["value"] if lang_row and lang_row["value"] else "ar"
    i18n.set_language(lang)
    palette.set_theme(theme)
    app.setLayoutDirection(Qt.RightToLeft if lang == "ar" else Qt.LeftToRight)
    app.setStyleSheet(get_stylesheet(theme))

    trial_result = check_license_and_trial()
    if trial_result == "EXIT":
        sys.exit(0)

    shop_name_row = db.fetch_one("SELECT value FROM settings WHERE setting_key='shop_name'")
    shop_name = shop_name_row["value"] if shop_name_row else i18n.tr("app.default_shop_name")

    # لو خطوات البدء (اتصال قاعدة البيانات، فحص الترخيص) خلصت بسرعة، بنكمّل
    # عرض السبلاش لحد ما توصل المدة الدنيا عشان تبقى محسوسة مش ومضة.
    remaining = SPLASH_MIN_SECONDS - (time.time() - splash_started_at)
    while remaining > 0:
        app.processEvents()
        time.sleep(min(remaining, 0.05))
        remaining = SPLASH_MIN_SECONDS - (time.time() - splash_started_at)

    login = LoginWindow(shop_name=shop_name)
    login.show()
    splash.finish(login)
    if not login.exec():
        sys.exit(0)

    window = MainWindow(login.user, trial_days_left=trial_result if isinstance(trial_result, int) else None)
    window.showMaximized()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

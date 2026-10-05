"""Start Clipboard History without a console window:  pyw -3.12 clipboard_history.pyw"""
import sys

if sys.platform != "win32":
    sys.exit("Clipboard History runs on Windows only.")

from cliphist.app import main  # noqa: E402

main()

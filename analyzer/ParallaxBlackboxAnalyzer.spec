# PyInstaller spec for the single-file Windows build.
#   pyinstaller analyzer/ParallaxBlackboxAnalyzer.spec
# Expects the decoder at obj/blackbox_decode.exe (override with BB_DECODER_EXE).
import os

HERE = os.path.abspath(SPECPATH)
ROOT = os.path.dirname(HERE)
decoder_exe = os.environ.get("BB_DECODER_EXE", os.path.join(ROOT, "obj", "blackbox_decode.exe"))
if not os.path.isfile(decoder_exe):
    raise SystemExit(f"blackbox_decode.exe not found at {decoder_exe}; run make first")

a = Analysis(
    [os.path.join(HERE, "run_analyzer.py")],
    pathex=[HERE],
    binaries=[(decoder_exe, "bin")],
    datas=[(os.path.join(HERE, "assets", "icon.png"), "assets"),
           (os.path.join(ROOT, "LICENSE"), ".")],
    hiddenimports=["matplotlib.backends.backend_tkagg", "PIL._tkinter_finder"],
    excludes=["scipy", "IPython", "jupyter", "notebook", "PyQt5", "PyQt6", "PySide2", "PySide6",
              "matplotlib.backends.backend_qtagg", "matplotlib.backends.backend_qt5agg",
              "matplotlib.backends.backend_wx", "matplotlib.backends.backend_gtk3agg",
              "pytest", "setuptools", "pip", "tornado", "sqlalchemy", "pyarrow", "numexpr",
              "bottleneck", "openpyxl", "lxml", "sympy", "pywin32", "win32com", "pythonwin"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ParallaxBlackboxAnalyzer",
    icon=os.path.join(HERE, "assets", "icon.ico"),
    console=False,
    upx=False,
    version=os.path.join(HERE, "version_info.txt") if os.path.isfile(os.path.join(HERE, "version_info.txt")) else None,
)

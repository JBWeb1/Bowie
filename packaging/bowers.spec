# PyInstaller spec for the Windows app. Build: pyinstaller packaging/bowers.spec  (see .github/workflows/release.yml)
# Makes dist/Bowers/ with Bowers.exe (the app window) and bowers-cli.exe (the command line).
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, ROOT)  # build from this checkout, not some other installed copy

datas = collect_data_files("docks", includes=["web/*.html", "web/app/*", "web/assets/*", "web/assets/*/*",
                                              "builtin/*/*.md", "router/*"])
datas += copy_metadata("anthropic")  # `bowers doctor` reads its version
hidden = collect_submodules("docks") + collect_submodules("anthropic") + ["sympy", "PIL"]
binaries = []
for pkg in ("kokoro_onnx", "espeakng_loader", "phonemizer", "onnxruntime", "language_tags", "segments", "csvw"):  # the offline voice, when installed
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hidden += h
    except Exception:
        pass

a = Analysis([os.path.join(SPECPATH, "launch.py")], pathex=[ROOT], datas=datas, binaries=binaries, hiddenimports=hidden,
             excludes=["playwright", "tkinter", "matplotlib", "pandas", "torch", "litellm", "IPython", "pytest", "langgraph", "langchain", "tradingagents"], noarchive=False)
pyz = PYZ(a.pure)
app = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Bowers", console=False,
          icon=os.path.join(ROOT, "docks/web/assets/app.ico"), version=None)
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="bowers-cli", console=True,
          icon=os.path.join(ROOT, "docks/web/assets/app.ico"))
coll = COLLECT(app, cli, a.binaries, a.datas, name="Bowers")

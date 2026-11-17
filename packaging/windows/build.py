"""Build the Windows x64 installer from the committed, allowlisted source tree."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
VERSION = "0.3.44"
PYTHON_VERSION = "3.13.17"
PYTHON_SHA256 = "9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38"
SSH_VERSION = "10.4.0.0p1-Preview"
SSH_SHA256 = "b67ff8becd203502190ec42ac7787c24c2cd3325ed7700485fe7a1c83d2a7957"
INNO_SHA256 = "8a5a6711c3766a6e5fb74f280ba0e3551e719ce94538d901fdbd1f8f9920b3f0"
WEBVIEW_VERSION = "1.0.4314.35"
WEBVIEW_SHA256 = "90778deb1b77e36292828b4b5833c9255c27533f40e0ddd55891ae718944edc4"
WEBVIEW_SETUP_SHA256 = "cf2f2445fef0c5c14e372045f84998771eeb8bb01d59be4afd00692fa160082e"


def download(url: str, path: Path, digest: str) -> Path:
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        temporary = path.with_suffix(".download")
        with urllib.request.urlopen(url, timeout=90) as response, temporary.open("wb") as target:
            shutil.copyfileobj(response, target)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Checksum mismatch for {path.name}")
        temporary.replace(path)
    return path


def run(args: list[str], **kwargs):
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def runtime(archive: Path, target: Path, *, panel: bool):
    with zipfile.ZipFile(archive) as package:
        package.extractall(target)
    paths = ["python313.zip", ".", "Lib/site-packages"]
    if panel:
        paths.append("..")
    (target / "python313._pth").write_text("\n".join(paths + ["import site", ""]), encoding="utf-8")
    (target / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-dependencies", action="store_true")
    args = parser.parse_args()
    if sys.platform != "win32" or sys.version_info[:2] != (3, 13):
        raise RuntimeError("Build using Windows x64 Python 3.13.")
    downloads = ROOT / ".build" / "windows-downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    work = ROOT / ".build" / "windows"
    bundle = work / "NetDeployAI"
    output = ROOT / "release"
    output.mkdir(exist_ok=True)
    python = download(
        f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip",
        downloads / f"python-{PYTHON_VERSION}-embed-amd64.zip", PYTHON_SHA256,
    )
    ssh = download(
        f"https://github.com/PowerShell/Win32-OpenSSH/releases/download/{SSH_VERSION}/OpenSSH-Win64.zip",
        downloads / "OpenSSH-Win64.zip", SSH_SHA256,
    )
    # git archive prevents a developer's local credentials and uncommitted assets
    # from accidentally entering a public installer.
    source = subprocess.check_output([
        "git", "-C", str(ROOT), "archive", "--format=zip", "HEAD",
        "app", "requirements.txt", "requirements-codex-worker.txt", "LICENSE",
    ])
    if not args.skip_dependencies:
        if bundle.exists():
            if bundle.resolve().parent != work.resolve():
                raise RuntimeError("Invalid build directory")
            shutil.rmtree(bundle)
        runtime(python, bundle / "runtime", panel=True)
        runtime(python, bundle / "codex-runtime", panel=False)
    with zipfile.ZipFile(io.BytesIO(source)) as package:
        package.extractall(bundle)
    for directory, requirements in (("runtime", "requirements.txt"), ("codex-runtime", "requirements-codex-worker.txt")):
        if not args.skip_dependencies:
            run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-compile",
                 "--only-binary=:all:", "--target", bundle / directory / "Lib" / "site-packages",
                 "-r", bundle / requirements])
    with zipfile.ZipFile(ssh) as package:
        for entry in package.infolist():
            name = Path(entry.filename).name
            if name.lower() in {"ssh.exe", "ssh-keygen.exe", "ssh-keyscan.exe", "libcrypto.dll",
                                "license.txt", "notice.txt"}:
                destination = bundle / "ssh" / name
                destination.parent.mkdir(exist_ok=True)
                destination.write_bytes(package.read(entry))
    shutil.copyfile(bundle / "app/static/brand/favicon.ico", bundle / "netdeploy.ico")
    webview = download(
        f"https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/{WEBVIEW_VERSION}",
        downloads / "webview2-sdk.nupkg", WEBVIEW_SHA256,
    )
    bootstrapper = download(
        "https://go.microsoft.com/fwlink/p/?LinkId=2124703",
        downloads / "MicrosoftEdgeWebview2Setup.exe", WEBVIEW_SETUP_SHA256,
    )
    shutil.copyfile(bootstrapper, bundle / bootstrapper.name)
    with zipfile.ZipFile(webview) as sdk:
        for source, name in (
            ("lib/net462/Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.Core.dll"),
            ("lib/net462/Microsoft.Web.WebView2.WinForms.dll", "Microsoft.Web.WebView2.WinForms.dll"),
            ("build/native/x64/WebView2Loader.dll", "WebView2Loader.dll"),
            ("LICENSE.txt", "WebView2-LICENSE.txt"),
        ):
            (bundle / name).write_bytes(sdk.read(source))
    compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
    shutil.copyfile(ROOT / "packaging" / "windows" / "NetDeployAI.exe.config",
                    bundle / "NetDeployAI.exe.config")
    run([compiler, "/nologo", "/target:winexe", "/platform:x64",
         "/reference:System.Windows.Forms.dll", "/reference:System.Drawing.dll",
         "/reference:System.Net.Http.dll", "/reference:System.Web.Extensions.dll",
         f"/reference:{bundle / 'Microsoft.Web.WebView2.Core.dll'}",
         f"/reference:{bundle / 'Microsoft.Web.WebView2.WinForms.dll'}",
         f"/win32icon:{bundle / 'netdeploy.ico'}", f"/out:{bundle / 'NetDeployAI.exe'}",
         f"/win32manifest:{ROOT / 'packaging' / 'windows' / 'app.manifest'}",
         ROOT / "packaging" / "windows" / "Launcher.cs",
         ROOT / "packaging" / "windows" / "ClientWindow.cs",
         ROOT / "packaging" / "windows" / "ClientUpdates.cs",
         ROOT / "packaging" / "windows" / "DesktopUpdates.cs",
         ROOT / "packaging" / "windows" / "HiddifyBrowser.cs",
         ROOT / "packaging" / "windows" / "WindowPlacement.cs"])
    run([compiler, "/nologo", "/target:winexe", "/platform:x64",
         "/reference:System.Windows.Forms.dll", "/reference:System.Net.Http.dll",
         "/reference:System.Web.Extensions.dll", f"/out:{bundle / 'NetDeployUpdater.exe'}",
         ROOT / "packaging" / "windows" / "UpdateInstaller.cs",
         ROOT / "packaging" / "windows" / "DesktopUpdates.cs"])
    for executable in ("runtime/python.exe", "codex-runtime/python.exe", "ssh/ssh.exe"):
        if not (bundle / executable).is_file():
            raise RuntimeError(f"Missing runtime {executable}")
    run([bundle / "runtime" / "python.exe", "-I", "-c",
         "import fastapi,uvicorn,paramiko,keyring; from keyring.backends.Windows import WinVaultKeyring"])
    run([bundle / "codex-runtime" / "python.exe", "-I", "-c",
         "import fastapi,uvicorn,openai_codex; from codex_cli_bin import bundled_codex_path; assert bundled_codex_path().is_file()"])
    run([bundle / "ssh" / "ssh.exe", "-V"])
    manifest = {
        "version": VERSION,
        "commit": subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
        "python": {"version": PYTHON_VERSION, "sha256": PYTHON_SHA256},
        "openssh": {"version": SSH_VERSION, "sha256": SSH_SHA256},
        "codex": "0.163.0",
        "signed": False,
        "webview2_sdk": {"version": WEBVIEW_VERSION, "sha256": WEBVIEW_SHA256},
        "webview2_setup_sha256": WEBVIEW_SETUP_SHA256,
    }
    for directory in ("runtime", "codex-runtime"):
        installed = subprocess.check_output([
            bundle / directory / "python.exe", "-I", "-c",
            "import importlib.metadata as m,json; print(json.dumps({d.metadata['Name']:d.version for d in m.distributions()}))",
        ], text=True)
        manifest[directory] = json.loads(installed)
    (bundle / "BUILD-MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    inno = ROOT / ".build" / "tools" / "inno" / "ISCC.exe"
    if not inno.is_file():
        setup = download(
            "https://github.com/jrsoftware/issrc/releases/download/is-7_1_1/innosetup-7.1.1-x64.exe",
            downloads / "innosetup-7.1.1-x64.exe", INNO_SHA256,
        )
        run([setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER", "/NOICONS",
             f"/DIR={inno.parent}"])
    run([inno, f"/DAppVersion={VERSION}", f"/DBundleDir={bundle}", f"/DOutputDir={output}",
         ROOT / "packaging" / "windows" / "installer.iss"])
    archive = output / f"NetDeployAI-{VERSION}-windows-x64.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as package:
        for file in sorted(bundle.rglob("*")):
            if file.is_file() and "__pycache__" not in file.parts:
                package.write(file, Path("NetDeployAI") / file.relative_to(bundle))
    files = [output / f"NetDeployAI-{VERSION}-Setup-x64.exe", archive]
    (output / "SHA256SUMS.txt").write_text("".join(
        f"{hashlib.sha256(file.read_bytes()).hexdigest()}  {file.name}\n" for file in files), encoding="utf-8")
    shutil.copyfile(bundle / "BUILD-MANIFEST.json", output / "BUILD-MANIFEST.json")
    print("Windows installer ready", flush=True)


if __name__ == "__main__":
    main()

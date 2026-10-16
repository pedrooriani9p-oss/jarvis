"""Jarvis Ponte: deixa o Jarvis (no navegador) fazer algumas coisas neste PC com Windows.

Segurança, por design:
- escuta só em 127.0.0.1 (nada de fora do computador alcança);
- só aceita pedidos do site do Jarvis (cabeçalho Origin) E com o código de pareamento
  gerado na primeira execução;
- não existe "rodar comando": só uma lista fixa de ações, sem shell, com entradas validadas;
- arquivos e pastas só dentro da pasta do usuário, e nunca executáveis ou scripts.
Usa só a biblioteca padrão do Python, para virar um .exe pequeno com PyInstaller.
"""
import base64
import ctypes
import tempfile
import glob
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 47800
VERSION = "1.1.0"
ALLOWED_ORIGINS = {"https://pedrooriani9p-oss.github.io"}
IS_WIN = os.name == "nt"
HOME = os.path.realpath(os.path.expanduser("~"))
DATA_DIR = os.path.join(os.environ.get("APPDATA", HOME), "JarvisPonte")
NO_WINDOW = 0x08000000 if IS_WIN else 0
BLOCKED_EXT = {".exe", ".bat", ".cmd", ".com", ".ps1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh",
               ".msi", ".msp", ".scr", ".lnk", ".url", ".reg", ".hta", ".cpl", ".jar", ".pif", ".dll", ".sys"}

# ---------- utilidades ----------

def msgbox(text, title="Jarvis Ponte"):
    if IS_WIN:
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)
    else:
        print(f"[{title}] {text}")


def run(args):
    """Executa um programa fixo com argumentos em lista (nunca via shell)."""
    return subprocess.run(args, capture_output=True, text=True, creationflags=NO_WINDOW, timeout=30)


def press_key(vk, times=1):
    if not IS_WIN:
        return
    for _ in range(times):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        time.sleep(0.02)


def copy_to_clipboard(text):
    if IS_WIN:
        p = subprocess.Popen(["clip"], stdin=subprocess.PIPE, creationflags=NO_WINDOW)
        p.communicate(text.encode("utf-16-le"))


def inside_home(path):
    real = os.path.realpath(os.path.expanduser(path))
    return real if os.path.commonpath([real, HOME]) == HOME else None


def load_token():
    """Código de pareamento: gerado uma vez, guardado em %APPDATA%\\JarvisPonte."""
    os.makedirs(DATA_DIR, exist_ok=True)
    f = os.path.join(DATA_DIR, "codigo.txt")
    if os.path.exists(f):
        return open(f, encoding="utf-8").read().strip(), False
    tok = secrets.token_urlsafe(18)
    with open(f, "w", encoding="utf-8") as fh:
        fh.write(tok)
    return tok, True


def set_startup(enabled):
    """Liga/desliga a ponte junto com o Windows (registro do usuário, sem admin)."""
    if not IS_WIN or not getattr(sys, "frozen", False):
        return
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
    try:
        if enabled:
            winreg.SetValueEx(key, "JarvisPonte", 0, winreg.REG_SZ, f'"{sys.executable}"')
        else:
            winreg.DeleteValue(key, "JarvisPonte")
    except OSError:
        pass
    winreg.CloseKey(key)

# ---------- ações (lista fixa) ----------

# apps do Windows abertos por nome fixo, sem passar texto do usuário adiante
BUILTIN_APPS = {
    "bloco de notas": ["notepad.exe"], "notepad": ["notepad.exe"], "calculadora": ["calc.exe"],
    "paint": ["mspaint.exe"], "explorador": ["explorer.exe"], "arquivos": ["explorer.exe"],
    "gerenciador de tarefas": ["taskmgr.exe"], "configurações": ["explorer.exe", "ms-settings:"],
    "configuracoes": ["explorer.exe", "ms-settings:"], "spotify": ["explorer.exe", "spotify:"],
    "whatsapp": ["explorer.exe", "whatsapp:"], "discord": ["explorer.exe", "discord:"],
    "steam": ["explorer.exe", "steam:"],
}
FOLDERS = {
    "documentos": "Documents", "downloads": "Downloads", "área de trabalho": "Desktop",
    "area de trabalho": "Desktop", "desktop": "Desktop", "imagens": "Pictures", "fotos": "Pictures",
    "músicas": "Music", "musicas": "Music", "vídeos": "Videos", "videos": "Videos", "pasta pessoal": "",
}
PROCESS_ALIASES = {"bloco de notas": "notepad", "calculadora": "CalculatorApp", "word": "winword",
                   "edge": "msedge", "vs code": "code", "vscode": "code", "powerpoint": "powerpnt"}


def start_menu_shortcuts():
    roots = [
        os.path.join(os.environ.get("PROGRAMDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(HOME, "Desktop"),
        os.path.join(os.environ.get("PUBLIC", ""), "Desktop"),
    ]
    out = []
    for r in roots:
        if r and os.path.isdir(r):
            out += glob.glob(os.path.join(r, "**", "*.lnk"), recursive=True)
    return out


def abrir_programa(nome):
    n = nome.strip().lower()
    if not n or len(n) > 60:
        return {"ok": False, "erro": "nome inválido"}
    if n in BUILTIN_APPS:
        subprocess.Popen(BUILTIN_APPS[n], creationflags=NO_WINDOW)
        return {"ok": True, "abriu": nome}
    # só abre o que já está instalado: atalhos do menu Iniciar e da área de trabalho
    matches = [p for p in start_menu_shortcuts()
               if n in os.path.splitext(os.path.basename(p))[0].lower()
               and not re.search(r"uninstall|desinstal|remover", p, re.I)]
    if not matches:
        return {"ok": False, "erro": f"Não achei '{nome}' no menu Iniciar."}
    best = min(matches, key=lambda p: len(os.path.basename(p)))
    os.startfile(best)
    return {"ok": True, "abriu": os.path.splitext(os.path.basename(best))[0]}


def fechar_programa(nome):
    n = nome.strip().lower()
    n = PROCESS_ALIASES.get(n, n)
    n = n[:-4] if n.endswith(".exe") else n
    if not re.fullmatch(r"[a-z0-9_.\- ]{1,40}", n, re.I):
        return {"ok": False, "erro": "nome inválido"}
    r = run(["taskkill", "/IM", n + ".exe"])
    return {"ok": r.returncode == 0, "saida": (r.stdout or r.stderr).strip()[:200]}


def volume(acao, passos=5):
    vk = {"subir": 0xAF, "descer": 0xAE, "mudo": 0xAD}.get(acao)
    if not vk:
        return {"ok": False, "erro": "use subir, descer ou mudo"}
    press_key(vk, 1 if vk == 0xAD else max(1, min(int(passos or 5), 50)))
    return {"ok": True}


def midia(acao):
    vk = {"tocar_pausar": 0xB3, "proxima": 0xB0, "anterior": 0xB1, "parar": 0xB2}.get(acao)
    if not vk:
        return {"ok": False, "erro": "use tocar_pausar, proxima, anterior ou parar"}
    press_key(vk)
    return {"ok": True}


def energia(acao):
    cmds = {
        "desligar": ["shutdown", "/s", "/t", "60"], "reiniciar": ["shutdown", "/r", "/t", "60"],
        "cancelar": ["shutdown", "/a"], "bloquear": ["rundll32.exe", "user32.dll,LockWorkStation"],
    }
    if acao not in cmds:
        return {"ok": False, "erro": "use desligar, reiniciar, cancelar ou bloquear"}
    r = run(cmds[acao])
    extra = " em 60 segundos (diga 'cancelar desligamento' para abortar)" if acao in ("desligar", "reiniciar") else ""
    return {"ok": r.returncode == 0, "info": acao + extra}


def print_tela():
    folder = os.path.join(HOME, "Pictures", "Jarvis")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, datetime.now().strftime("print_%Y-%m-%d_%H-%M-%S.png"))
    script = ("Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
              "$b=[System.Windows.Forms.SystemInformation]::VirtualScreen;"
              "$i=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
              "$g=[System.Drawing.Graphics]::FromImage($i);$g.CopyFromScreen($b.Left,$b.Top,0,0,$i.Size);"
              "$i.Save($env:JARVIS_PRINT)")
    env = dict(os.environ, JARVIS_PRINT=path)  # caminho vai por variável, não dentro do script
    r = subprocess.run(["powershell", "-NoProfile", "-Command", script], env=env,
                       capture_output=True, text=True, creationflags=NO_WINDOW, timeout=30)
    if r.returncode == 0 and os.path.exists(path):
        return {"ok": True, "arquivo": path}
    return {"ok": False, "erro": (r.stderr or "falhou").strip()[:200]}


def capturar_tela():
    """Captura a tela reduzida (até 1568 px) em JPEG e devolve em base64, para o Jarvis "ver"."""
    fd, path = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    script = ("Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
              "$b=[System.Windows.Forms.SystemInformation]::VirtualScreen;"
              "$i=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
              "$g=[System.Drawing.Graphics]::FromImage($i);$g.CopyFromScreen($b.Left,$b.Top,0,0,$i.Size);"
              "$s=[Math]::Min(1,1568/$b.Width);$w=[int]($b.Width*$s);$h=[int]($b.Height*$s);"
              "$o=New-Object System.Drawing.Bitmap $i,$w,$h;"
              "$c=[System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders()|?{$_.MimeType -eq 'image/jpeg'};"
              "$p=New-Object System.Drawing.Imaging.EncoderParameters 1;"
              "$p.Param[0]=New-Object System.Drawing.Imaging.EncoderParameter([System.Drawing.Imaging.Encoder]::Quality,[long]70);"
              "$o.Save($env:JARVIS_PRINT,$c,$p)")
    env = dict(os.environ, JARVIS_PRINT=path)
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", script], env=env,
                           capture_output=True, text=True, creationflags=NO_WINDOW, timeout=30)
        if r.returncode != 0 or not os.path.getsize(path):
            return {"ok": False, "erro": (r.stderr or "falhou").strip()[:200]}
        with open(path, "rb") as fh:
            return {"ok": True, "imagem": base64.b64encode(fh.read()).decode()}
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def abrir_pasta(nome):
    n = nome.strip().lower()
    path = inside_home(os.path.join(HOME, FOLDERS[n]) if n in FOLDERS else nome)
    if not path or not os.path.isdir(path):
        return {"ok": False, "erro": "só abro pastas dentro da sua pasta de usuário"}
    os.startfile(path)
    return {"ok": True, "pasta": path}


def procurar_arquivos(termo, limite=15):
    termo = termo.strip().lower()
    if len(termo) < 2:
        return {"ok": False, "erro": "termo muito curto"}
    found, skip = [], {"AppData", "node_modules", "$Recycle.Bin"}
    for root, dirs, files in os.walk(HOME):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
        for f in files:
            if termo in f.lower():
                full = os.path.join(root, f)
                found.append({"nome": f, "caminho": full,
                              "modificado": datetime.fromtimestamp(os.path.getmtime(full)).strftime("%d/%m/%Y")})
                if len(found) >= limite:
                    return {"ok": True, "arquivos": found}
    return {"ok": True, "arquivos": found}


def abrir_arquivo(caminho):
    path = inside_home(caminho)
    if not path or not os.path.isfile(path):
        return {"ok": False, "erro": "só abro arquivos que existem dentro da sua pasta de usuário"}
    if os.path.splitext(path)[1].lower() in BLOCKED_EXT:
        return {"ok": False, "erro": "por segurança não abro programas nem scripts"}
    os.startfile(path)
    return {"ok": True}


def info_sistema():
    info = {"computador": os.environ.get("COMPUTERNAME", ""), "usuario": os.environ.get("USERNAME", "")}
    total, _, free = shutil.disk_usage(HOME)
    info["disco"] = f"{free // 2**30} GB livres de {total // 2**30} GB"
    if IS_WIN:
        class SPS(ctypes.Structure):
            _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                        ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                        ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]
        s = SPS()
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)) and s.BatteryLifePercent != 255:
            info["bateria"] = f"{s.BatteryLifePercent}%" + (" (carregando)" if s.ACLineStatus == 1 else "")
        else:
            info["bateria"] = "sem bateria (desktop)"
    return {"ok": True, **info}


def digitar(texto):
    """Cola um texto onde o cursor estiver (área de transferência + Ctrl+V)."""
    if not IS_WIN or len(texto) > 5000:
        return {"ok": False, "erro": "texto inválido"}
    copy_to_clipboard(texto)
    time.sleep(0.15)
    u = ctypes.windll.user32
    u.keybd_event(0x11, 0, 0, 0); u.keybd_event(0x56, 0, 0, 0)
    u.keybd_event(0x56, 0, 2, 0); u.keybd_event(0x11, 0, 2, 0)
    return {"ok": True}


ACTIONS = {
    "abrir_programa": lambda a: abrir_programa(str(a["nome"])),
    "fechar_programa": lambda a: fechar_programa(str(a["nome"])),
    "volume": lambda a: volume(a["acao"], a.get("passos", 5)),
    "midia": lambda a: midia(a["acao"]),
    "energia": lambda a: energia(a["acao"]),
    "print_tela": lambda a: print_tela(),
    "capturar_tela": lambda a: capturar_tela(),
    "abrir_pasta": lambda a: abrir_pasta(str(a["nome"])),
    "procurar_arquivos": lambda a: procurar_arquivos(str(a["termo"])),
    "abrir_arquivo": lambda a: abrir_arquivo(str(a["caminho"])),
    "info_sistema": lambda a: info_sistema(),
    "digitar": lambda a: digitar(str(a["texto"])),
}

# ---------- servidor ----------

TOKEN = ""


class Handler(BaseHTTPRequestHandler):
    def _origin_ok(self):
        return self.headers.get("Origin") in ALLOWED_ORIGINS

    def _auth_ok(self):
        return self._origin_ok() and hmac.compare_digest(self.headers.get("X-Jarvis-Codigo", ""), TOKEN)

    def _send(self, code, body):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        if self._origin_ok():
            self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
            self.send_header("Vary", "Origin")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        ok = self._origin_ok()
        self.send_response(204 if ok else 403)
        if ok:
            self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
            self.send_header("Access-Control-Allow-Methods", "GET, POST")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Jarvis-Codigo")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Vary", "Origin")
        self.end_headers()

    def do_GET(self):
        if self.path != "/status":
            return self._send(404, {"erro": "não encontrado"})
        if not self._origin_ok():
            return self._send(403, {"erro": "origem não permitida"})
        self._send(200, {"ok": True, "versao": VERSION, "pareado": self._auth_ok()})

    def do_POST(self):
        if not self._auth_ok():
            return self._send(403, {"ok": False, "erro": "código de pareamento inválido"})
        name = self.path[len("/acao/"):] if self.path.startswith("/acao/") else ""
        if name not in ACTIONS:
            return self._send(404, {"ok": False, "erro": "ação desconhecida"})
        try:
            length = min(int(self.headers.get("Content-Length") or 0), 20000)
            args = json.loads(self.rfile.read(length) or b"{}")
            return self._send(200, ACTIONS[name](args))
        except KeyError as e:
            return self._send(400, {"ok": False, "erro": f"faltou o parâmetro {e}"})
        except Exception as e:  # um comando com erro nunca derruba a ponte
            return self._send(500, {"ok": False, "erro": str(e)[:200]})

    def log_message(self, *a):
        pass


def main():
    global TOKEN
    if "--remover" in sys.argv:
        set_startup(False)
        return msgbox("O Jarvis Ponte não vai mais iniciar com o Windows.")
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        return msgbox("O Jarvis Ponte já está rodando.")
    TOKEN, first = load_token()
    set_startup(True)
    if first or "--codigo" in sys.argv:
        copy_to_clipboard(TOKEN)
        msgbox("Jarvis Ponte ativa!\n\nSeu código de pareamento já foi COPIADO:\n\n" + TOKEN +
               "\n\nAbra o Jarvis, vá em CONFIG e cole (Ctrl+V) no campo \"Código do PC\".\n"
               "A ponte vai iniciar sozinha junto com o Windows.")
    server.serve_forever()


if __name__ == "__main__":
    main()

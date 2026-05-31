"""
Visaflow Web — Servidor
=======================
Instalar: pip install flask requests
Rodar:    python server.py
Acesso:   http://SEU_IP:5000  (celular na mesma rede)
          http://localhost:5000 (computador)
"""

from flask import Flask, jsonify, request, render_template
import threading
import requests
import time
import json
import os
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

app = Flask(__name__)

# ── Constantes ───────────────────────────────────────────────
BASE_URL   = "https://ais.usvisa-info.com/pt-br/niv"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
)
CONSULADOS = {
    "56": "São Paulo",
    "55": "Rio de Janeiro",
    "54": "Brasília",
    "57": "Recife",
    "128": "Porto Alegre",
}
CASV_MAP = {"56": "60", "55": "58", "54": "57", "57": "61", "128": "129"}
PROXY_LIST = [
   "38.154.203.95:5863:ulehnrpt:zyeyi40is57f",
   "198.105.121.200:6462:ulehnrpt:zyeyi40is57f",
   "64.137.96.74:6641:ulehnrpt:zyeyi40is57f",
   "209.127.138.10:5784:ulehnrpt:zyeyi40is57f",
   "38.154.185.97:6370:ulehnrpt:zyeyi40is57f",
   "84.247.60.125:6095:ulehnrpt:zyeyi40is57f",
   "142.111.67.146:5611:ulehnrpt:zyeyi40is57f",
   "191.96.254.138:6185:ulehnrpt:zyeyi40is57f",
   "31.58.9.4:6077:ulehnrpt:zyeyi40is57f",
   "104.239.107.47:5699:ulehnrpt:zyeyi40is57f",
]
_proxy_index=0
import threading as _t; _proxy_lock=_t.Lock()
def get_proxy():
   global _proxy_index
   if not PROXY_LIST: return None
   with _proxy_lock:
       s=PROXY_LIST[_proxy_index%len(PROXY_LIST)]; _proxy_index+=1
   h,p,u,pw=s.split(":")
   return {"http":f"http://{u}:{pw}@{h}:{p}","https":f"http://{u}:{pw}@{h}:{p}"}
CONFIG_PATH = os.environ.get("CONFIG_PATH", os.path.join(os.path.expanduser("~"), ".visaflow_web_config.json"))

# ── Estado global ────────────────────────────────────────────
contas   = {}   # id -> dict com config + estado
logs     = []   # lista global de logs
logs_lock = threading.Lock()


def add_log(conta_nome, msg, tipo="info"):
    with logs_lock:
        entry = {
            "ts":   datetime.now().strftime("%H:%M:%S"),
            "nome": conta_nome,
            "msg":  msg,
            "tipo": tipo,
        }
        logs.append(entry)
        if len(logs) > 500:
            logs.pop(0)


# ════════════════════════════════════════════════════════════
#  CLIENTE HTTP (substitui Selenium)
# ════════════════════════════════════════════════════════════

class VisaClient:
    """Sessão HTTP que imita o navegador sem abrir janela."""

    def __init__(self, config: dict):
        self.config  = config
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        self._csrf = None

    def _get_csrf(self, html: str) -> str:
        m = re.search(r'<meta[^>]+name=["\']csrf-token["\'][^>]+content=["\']([^"\']+)["\']', html)
        if m:
            return m.group(1)
        m = re.search(r'authenticity_token["\'][^>]*value=["\']([^"\']+)["\']', html)
        if m:
            return m.group(1)
        return ""

    def login(self) -> bool:
        try:
            r = self.session.get(f"{BASE_URL}/users/sign_in", timeout=30)
            csrf = self._get_csrf(r.text)
            if not csrf:
                return False

            payload = {
                "utf8": "✓",
                "authenticity_token": csrf,
                "user[email]": self.config["site_email"],
                "user[password]": self.config["site_pass"],
                "policy_confirmed": "1",
                "commit": "Entrar",
            }
            self.session.headers.update({
                "Referer": f"{BASE_URL}/users/sign_in",
                "Content-Type": "application/x-www-form-urlencoded",
            })
            r2 = self.session.post(
                f"{BASE_URL}/users/sign_in",
                data=payload,
                timeout=30,
                allow_redirects=True,
            )
            # Login ok se não voltou para sign_in
            if "sign_in" in r2.url:
                # Tenta extrair mensagem de erro do portal
                erro_portal = re.search(r"alert[^>]*>([^<]{10,120})<", r2.text)
                if erro_portal:
                    add_log(self.config.get("nome","?"), "❌ Portal: " + erro_portal.group(1).strip(), "erro")
                else:
                    add_log(self.config.get("nome","?"), "❌ Login recusado — e-mail/senha incorretos ou IP bloqueado pelo portal", "erro")
                return False
            # Guarda CSRF da nova página
            self._csrf = self._get_csrf(r2.text)
            return True
        except requests.exceptions.ProxyError as e:
            add_log(self.config.get("nome", "?"), "🚫 Erro de proxy: " + str(e)[:100], "erro")
            return False
        except requests.exceptions.ConnectionError as e:
            add_log(self.config.get("nome", "?"), "🚫 Sem conexão: " + str(e)[:100], "erro")
            return False
        except Exception as e:
            add_log(self.config.get("nome", "?"), "Erro no login: " + str(e)[:100], "erro")
            return False

    def buscar_datas(self) -> list[str]:
        """Chama a API JSON do portal para obter datas disponíveis."""
        consulado_id = self.config.get("consulado", "56")
        schedule_id  = self.config.get("schedule_id", "")

        try:
            url = (
                f"{BASE_URL}/schedule/{schedule_id}/appointment/days/"
                f"{consulado_id}.json?appointments[expedite]=false"
            )
            self.session.headers.update({
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{BASE_URL}/schedule/{schedule_id}/appointment",
            })
            r = self.session.get(url, timeout=30)

            if r.status_code == 401:
                return []  # sessão expirou

            if r.status_code != 200:
                return []

            data = r.json()
            # Retorna lista de strings "YYYY-MM-DD"
            datas = [d["date"] for d in data if d.get("date")]
            return datas

        except Exception as e:
            add_log(self.config.get("nome", "?"), f"Erro ao buscar datas: {e}", "erro")
            return []

    def buscar_horarios(self, data: str) -> list[str]:
        """Busca horários disponíveis para uma data."""
        consulado_id = self.config.get("consulado", "56")
        schedule_id  = self.config.get("schedule_id", "")

        try:
            url = (
                f"{BASE_URL}/schedule/{schedule_id}/appointment/times/"
                f"{consulado_id}.json?date={data}&appointments[expedite]=false"
            )
            self.session.headers.update({
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
            })
            r = self.session.get(url, timeout=30)
            if r.status_code != 200:
                return []
            data_j = r.json()
            return data_j.get("available_times", []) or data_j.get("times", [])
        except Exception:
            return []

    def agendar(self, data: str, horario: str) -> bool:
        """Submete o agendamento via POST."""
        schedule_id  = self.config.get("schedule_id", "")
        consulado_id = self.config.get("consulado", "56")
        casv_id      = CASV_MAP.get(consulado_id, "60")

        try:
            # Busca CSRF atualizado da página de agendamento
            r = self.session.get(
                f"{BASE_URL}/schedule/{schedule_id}/appointment", timeout=30
            )
            csrf = self._get_csrf(r.text) or self._csrf

            payload = {
                "utf8": "✓",
                "authenticity_token": csrf,
                "confirmed_limit_message": "1",
                "use_consulate_appointment_capacity": "true",
                "appointments[consulate_appointment][facility_id]": consulado_id,
                "appointments[consulate_appointment][date]": data,
                "appointments[consulate_appointment][time]": horario,
                "appointments[asc_appointment][facility_id]": casv_id,
                "appointments[asc_appointment][date]": data,
                "appointments[asc_appointment][time]": horario,
            }
            self.session.headers.update({
                "Referer": f"{BASE_URL}/schedule/{schedule_id}/appointment",
                "Content-Type": "application/x-www-form-urlencoded",
                "X-CSRF-Token": csrf,
            })
            r2 = self.session.post(
                f"{BASE_URL}/schedule/{schedule_id}/appointment",
                data=payload,
                timeout=30,
                allow_redirects=True,
            )
            page = r2.text.lower()
            return any(p in page for p in [
                "confirmação", "confirmed", "agendamento realizado",
                "appointment confirmed", "seu agendamento",
            ])
        except Exception as e:
            add_log(self.config.get("nome", "?"), f"Erro ao agendar: {e}", "erro")
            return False


# ════════════════════════════════════════════════════════════
#  WORKER DO BOT
# ════════════════════════════════════════════════════════════

class BotWorker:
    def __init__(self, conta_id: str):
        self.conta_id = conta_id
        self.rodando  = False
        self._thread  = None

    @property
    def config(self):
        return contas[self.conta_id]["config"]

    def _nome(self):
        return self.config.get("nome", self.conta_id)

    def log(self, msg, tipo="info"):
        add_log(self._nome(), msg, tipo)
        contas[self.conta_id]["ultimo_log"] = msg

    def set_status(self, status, tipo="info"):
        contas[self.conta_id]["status"]      = status
        contas[self.conta_id]["status_tipo"] = tipo

    def enviar_email(self, assunto, corpo):
        cfg = self.config
        if not cfg.get("email_notif"):
            return
        try:
            msg = MIMEMultipart()
            msg["From"]    = cfg["smtp_user"]
            msg["To"]      = cfg["email_dest"]
            msg["Subject"] = assunto
            msg.attach(MIMEText(corpo, "plain", "utf-8"))
            with smtplib.SMTP(cfg.get("smtp_host", "smtp.gmail.com"),
                              int(cfg.get("smtp_port", 587))) as s:
                s.starttls()
                s.login(cfg["smtp_user"], cfg["smtp_pass"])
                s.sendmail(cfg["smtp_user"], cfg["email_dest"], msg.as_string())
            self.log(f"📧 Email enviado: {assunto}", "sucesso")
        except Exception as e:
            self.log(f"⚠️ Falha ao enviar email: {e}", "aviso")

    def _filtrar_datas(self, datas: list[str]) -> list[str]:
        dmin = self.config.get("data_minima", "").strip()
        dlim = self.config.get("data_limite", "").strip()
        resultado = []
        for d in datas:
            if dmin and d < dmin:
                continue
            if dlim and d > dlim:
                continue
            resultado.append(d)
        return resultado

    def _loop(self):
        intervalo  = int(self.config.get("intervalo", 120))
        tentativas = 0

        while self.rodando:
            tentativas += 1
            self.log(
                f"🔍 Verificação #{tentativas} — {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
                "info"
            )
            self.set_status(f"Verificação #{tentativas}", "rodando")

            try:
                client = VisaClient(self.config)

                self.log("🔐 Fazendo login...", "info")
                if not client.login():
                    self.log("❌ Login falhou — verifique e-mail e senha.", "erro")
                    self.set_status("Erro no login", "erro")
                    self.enviar_email("❌ Visaflow — Falha no login", "Verifique e-mail e senha.")
                else:
                    self.log("✅ Login realizado!", "sucesso")
                    self.log("📅 Buscando datas disponíveis...", "info")

                    datas = client.buscar_datas()

                    if not datas:
                        self.log("😴 Nenhuma data disponível no momento.", "aviso")
                        self.set_status(f"Sem vagas — próxima em {intervalo}s", "aguardando")
                    else:
                        datas_filtradas = self._filtrar_datas(datas)

                        if not datas_filtradas:
                            primeira = datas[0] if datas else "?"
                            self.log(
                                f"📆 {len(datas)} data(s) encontrada(s) mas fora do intervalo configurado. "
                                f"Mais próxima: {primeira}",
                                "aviso"
                            )
                            self.set_status(f"Fora do intervalo — próxima em {intervalo}s", "aguardando")
                        else:
                            data_escolhida = datas_filtradas[0]
                            self.log(f"✨ Data disponível: {data_escolhida}!", "sucesso")

                            horarios = client.buscar_horarios(data_escolhida)
                            if not horarios:
                                self.log("⚠️ Sem horários para essa data.", "aviso")
                            else:
                                horario = horarios[0]
                                self.log(f"🕐 Horário: {horario} — agendando...", "info")

                                ok = client.agendar(data_escolhida, horario)
                                if ok:
                                    self.log(
                                        f"🎉 AGENDADO! {data_escolhida} às {horario}",
                                        "sucesso"
                                    )
                                    self.set_status(
                                        f"✅ Agendado: {data_escolhida} {horario}",
                                        "sucesso"
                                    )
                                    self.enviar_email(
                                        "✅ Visaflow — Agendamento confirmado!",
                                        f"Agendamento realizado!\n\n"
                                        f"📅 Data   : {data_escolhida}\n"
                                        f"🕐 Horário: {horario}\n"
                                        f"🏛 Consulado: {CONSULADOS.get(self.config.get('consulado','56'), '?')}\n\n"
                                        f"Acesse: https://ais.usvisa-info.com/pt-br/niv/schedule/"
                                        f"{self.config.get('schedule_id', '')}/appointment"
                                    )
                                    self.rodando = False
                                    break
                                else:
                                    self.log("⚠️ Servidor recusou — vaga pode ter sido tomada.", "aviso")
                                    self.enviar_email(
                                        "⚠️ Visaflow — Agendamento recusado",
                                        f"Tentei agendar {data_escolhida} às {horario} mas o servidor recusou.\n"
                                        "O bot continua monitorando."
                                    )

            except Exception as e:
                self.log(f"❌ Erro inesperado: {e}", "erro")
                self.set_status("Erro", "erro")

            if not self.rodando:
                break

            # Contagem regressiva
            for i in range(intervalo, 0, -1):
                if not self.rodando:
                    break
                self.set_status(f"Próxima verificação em {i}s...", "aguardando")
                time.sleep(1)

        if not self.rodando:
            self.set_status("⏹ Parado", "parado")

    def iniciar(self):
        if self.rodando:
            return
        self.rodando = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def parar(self):
        self.rodando = False


# ════════════════════════════════════════════════════════════
#  ROTAS FLASK
# ════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/contas", methods=["GET"])
def get_contas():
    resultado = {}
    for cid, c in contas.items():
        cfg = {k: v for k, v in c["config"].items() if k not in ("site_pass", "smtp_pass")}
        resultado[cid] = {
            "config":      cfg,
            "status":      c.get("status", "Parado"),
            "status_tipo": c.get("status_tipo", "parado"),
            "rodando":     c["worker"].rodando,
            "ultimo_log":  c.get("ultimo_log", ""),
        }
    return jsonify(resultado)


@app.route("/api/contas", methods=["POST"])
def criar_conta():
    data = request.json
    cid  = str(int(time.time() * 1000))
    worker = BotWorker(cid)
    contas[cid] = {
        "config":      data,
        "worker":      worker,
        "status":      "Parado",
        "status_tipo": "parado",
        "ultimo_log":  "",
    }
    salvar_config()
    return jsonify({"id": cid})


@app.route("/api/contas/<cid>", methods=["PUT"])
def atualizar_conta(cid):
    if cid not in contas:
        return jsonify({"erro": "Conta não encontrada"}), 404
    data = request.json
    # Preserva senha se não enviada
    for campo in ("site_pass", "smtp_pass"):
        if not data.get(campo):
            data[campo] = contas[cid]["config"].get(campo, "")
    contas[cid]["config"].update(data)
    salvar_config()
    return jsonify({"ok": True})


@app.route("/api/contas/<cid>", methods=["DELETE"])
def deletar_conta(cid):
    if cid not in contas:
        return jsonify({"erro": "Conta não encontrada"}), 404
    contas[cid]["worker"].parar()
    del contas[cid]
    salvar_config()
    return jsonify({"ok": True})


@app.route("/api/contas/<cid>/iniciar", methods=["POST"])
def iniciar_conta(cid):
    if cid not in contas:
        return jsonify({"erro": "Conta não encontrada"}), 404
    contas[cid]["worker"].iniciar()
    return jsonify({"ok": True})


@app.route("/api/contas/<cid>/parar", methods=["POST"])
def parar_conta(cid):
    if cid not in contas:
        return jsonify({"erro": "Conta não encontrada"}), 404
    contas[cid]["worker"].parar()
    return jsonify({"ok": True})


@app.route("/api/iniciar_todas", methods=["POST"])
def iniciar_todas():
    for c in contas.values():
        if not c["worker"].rodando:
            c["worker"].iniciar()
            time.sleep(0.3)
    return jsonify({"ok": True})


@app.route("/api/parar_todas", methods=["POST"])
def parar_todas():
    for c in contas.values():
        c["worker"].parar()
    return jsonify({"ok": True})


@app.route("/api/logs", methods=["GET"])
def get_logs():
    desde = int(request.args.get("desde", 0))
    with logs_lock:
        return jsonify(logs[desde:])


@app.route("/api/config_email", methods=["GET"])
def get_config_email():
    cfg = carregar_config()
    email = cfg.get("email", {})
    return jsonify({
        "email_notif": email.get("email_notif", False),
        "smtp_user":   email.get("smtp_user", ""),
        "smtp_pass":   "",  # nunca expõe
        "email_dest":  email.get("email_dest", ""),
    })


@app.route("/api/config_email", methods=["POST"])
def salvar_config_email():
    data = request.json
    cfg  = carregar_config()
    old_pass = cfg.get("email", {}).get("smtp_pass", "")
    cfg["email"] = {
        "email_notif": data.get("email_notif", False),
        "smtp_host":   "smtp.gmail.com",
        "smtp_port":   "587",
        "smtp_user":   data.get("smtp_user", ""),
        "smtp_pass":   data.get("smtp_pass") or old_pass,
        "email_dest":  data.get("email_dest", ""),
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    # Atualiza config de email em todas as contas
    for c in contas.values():
        c["config"].update(cfg["email"])
    return jsonify({"ok": True})


# ════════════════════════════════════════════════════════════
#  PERSISTÊNCIA
# ════════════════════════════════════════════════════════════

def carregar_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def salvar_config():
    cfg = carregar_config()
    cfg["contas"] = []
    for cid, c in contas.items():
        conta_cfg = dict(c["config"])
        conta_cfg["_id"] = cid
        cfg["contas"].append(conta_cfg)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def inicializar():
    cfg = carregar_config()
    email_cfg = cfg.get("email", {})
    for conta_data in cfg.get("contas", []):
        cid = conta_data.pop("_id", str(int(time.time() * 1000)))
        conta_data.update(email_cfg)
        worker = BotWorker(cid)
        contas[cid] = {
            "config":      conta_data,
            "worker":      worker,
            "status":      "Parado",
            "status_tipo": "parado",
            "ultimo_log":  "",
        }


# ════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    inicializar()
    print("\n✅ Visaflow Web iniciado!")
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

╔══════════════════════════════════════════════════════╗
║           VISAFLOW — DEPLOY NO RAILWAY               ║
╚══════════════════════════════════════════════════════╝

PASSO 1 — Criar conta no GitHub (se não tiver)
  → github.com → Sign up (gratuito)

PASSO 2 — Criar repositório no GitHub
  → github.com/new
  → Nome: visaflow
  → Deixe marcado "Public"
  → Create repository

PASSO 3 — Fazer upload dos arquivos
  Na página do repositório criado:
  → Clique em "uploading an existing file"
  → Arraste TODOS os arquivos desta pasta
    (server.py, requirements.txt, Procfile,
     railway.json, e as pastas static/ e templates/)
  → Commit changes

PASSO 4 — Deploy no Railway
  → Acesse: railway.app
  → Login with GitHub
  → New Project → Deploy from GitHub repo
  → Selecione o repositório "visaflow"
  → Railway detecta tudo automaticamente
  → Aguarde 2-3 minutos (barra de progresso)

PASSO 5 — Pegar o link do app
  → No Railway, clique no projeto
  → Settings → Domains → Generate Domain
  → Vai gerar um link tipo:
    https://visaflow-production.up.railway.app

PASSO 6 — Abrir no iPhone como app
  → Abra o link no Safari do iPhone
  → Toque em Compartilhar (ícone de caixinha com seta)
  → "Adicionar à Tela de Início"
  → Toque em "Adicionar"
  → Pronto! Aparece como app na tela inicial 🎉

══════════════════════════════════════════════════════

⚠️  IMPORTANTE — Dados persistentes no Railway:
  As configurações salvas (contas, emails) ficam em
  memória. Se o Railway reiniciar o serviço, você
  precisa re-cadastrar as contas.
  
  Para persistência permanente, adicione um volume:
  → Railway → seu projeto → Add Volume
  → Mount path: /data
  → Defina a variável de ambiente:
    CONFIG_PATH = /data/config.json

══════════════════════════════════════════════════════

PLANO GRATUITO DO RAILWAY:
  → $5 de crédito por mês (suficiente para rodar 24/7)
  → Não precisa cartão de crédito
  → Reinicia automaticamente se cair


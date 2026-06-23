# AGENTS.md

Robô que reativa planos Hapvida automaticamente. Worker Python em loop contínuo que consome uma fila no PostgreSQL, executa o fluxo web via Playwright, anexa comprovante no Zendesk e alerta o Slack em falhas. Sem testes, sem lint/typecheck configurados.

## Arquitetura (como tudo se conecta)
- `main.py` — orquestrador. Loop infinito: pega próximo registro da fila → roda Playwright → atualiza Zendesk → grava resultado no banco → alerta Slack. É o entrypoint real.
- `bot.py` (`executar_liberacao`) — todo o fluxo Playwright na Hapvida (login, navegação, reativação, screenshot). Retorna `(sucesso, mensagem, caminho_screenshot)`.
- `db.py` — fila PostgreSQL (tabela `fila_reativacao`). `init_db()` cria/migra a tabela e reseta órfãos `processando`→`pendente`. Concorrência via `FOR UPDATE SKIP LOCKED`. Máx. 3 tentativas por registro.
- `zendesk.py` / `slack_client.py` — integrações HTTP (`requests`).
- `reativacao.py` — script gravado pelo Playwright codegen (standalone, com credenciais de exemplo). NÃO é usado por `main.py`; serve só de referência/scratch. Não trate como código de produção.

## Como rodar
- **Produção (VPS):** `docker compose up --build -d`. A imagem roda Chromium em modo **headed** sob `Xvfb` (ver CMD do `Dockerfile`), não headless.
- **Local (dev):** `pip install -r requirements.txt` então `python main.py`. Para ver o navegador, defina `HEADLESS=False` no `.env`.
- **Compilar .exe (Windows):** `compilar.bat` (PyInstaller `--onefile`). Na máquina alvo é preciso rodar `playwright install chromium` na primeira vez.

## Configuração (.env)
Carregado do mesmo diretório do script/`.exe` (não do CWD). Variáveis: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASS`, `HEADLESS` (default `True`), `ZENDESK_SUBDOMAIN`, `ZENDESK_EMAIL`, `ZENDESK_TOKEN`, `SLACK_WEBHOOK_URL`. O `.env` é gitignored.
- `COOLDOWN_ENTRE_TICKETS` (segundos, default `240`): pausa entre cada ticket no loop de `main.py`. Default folgado porque rodam em VPS sem proxy (IP de datacenter já parte de score baixo). Não reduza demais — rajada de liberações rebaixa o score do reCAPTCHA v3.
- `PROXY_SERVER` / `PROXY_USERNAME` / `PROXY_PASSWORD` (opcionais): roteia o Chromium por um proxy. Em VPS use **IP residencial** (datacenter derruba o score do reCAPTCHA). Formato do server: `http://host:porta` ou `socks5://host:porta`. Lidos por `_config_proxy()` em `bot.py`; se `PROXY_SERVER` vazio, roda sem proxy.

## Gotchas críticos (não regrida estes)
- **reCAPTCHA v3 por score:** headless puro derruba o score e o login falha com "NÃO FOI POSSÍVEL VALIDAR O CAPTCHA". Por isso: contexto persistente (`launch_persistent_context` em `~/.robo_liberacao_perfil`), mascaramento de `navigator.webdriver`, aquecimento na home (com scroll) antes do login, digitação humana (`type` com delay, não `fill`), backoff crescente entre retries de login (`15s × tentativa`) e cool-down entre tickets. NÃO volte a processar em rajada nem a usar `fill` instantâneo — foi o que queimou o score em produção. Em Docker, o perfil é persistido via volume `perfil-navegador` — não remova (se queimar, `docker volume rm robo-liberacao_perfil-navegador` com o container parado).
- `main.py` força `PLAYWRIGHT_BROWSERS_PATH` para `%LOCALAPPDATA%\ms-playwright` (necessário para o `.exe` do PyInstaller).
- Versão do Playwright em `requirements.txt` (`>=1.44.0`) deve casar com a imagem base do `Dockerfile` (`v1.44.0-jammy`).
- Zendesk: campos customizados são IDs hardcoded em `zendesk.py` (`17378080644759`, `24824957448983`); o token tem fallback hardcoded no código — credenciais reais devem vir do `.env`.
- Idioma: logs, mensagens e comentários são em pt-BR. Mantenha o padrão.

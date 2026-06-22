# Usa a imagem oficial do Playwright para Python que já contém as dependências do sistema e navegadores pré-instalados
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

# Configura o Python para exibir logs em tempo real sem buffering
ENV PYTHONUNBUFFERED=1

# Define o diretório de trabalho no contêiner
WORKDIR /app

# Copia os arquivos de dependência
COPY requirements.txt .

# Instala as dependências Python
RUN pip install --no-cache-dir -r requirements.txt

# Garante que a versão correta do Chromium exigida pela biblioteca esteja instalada
RUN playwright install chromium

# Copia o restante do código da aplicação para o contêiner
COPY . .

# Comando para iniciar o robô orquestrador.
# Subimos um X virtual (Xvfb) manualmente e rodamos o navegador em modo HEADED, pois o
# login da Hapvida usa reCAPTCHA v3 (score de bot): em headless puro o score cai e o captcha
# é recusado. Um navegador headed sob Xvfb se parece muito mais com um navegador real.
# Usamos "python -u" para saída sem buffer (logs aparecem em tempo real no docker logs) e
# "exec" para que o Python receba os sinais corretamente. Defina HEADLESS=False no .env.
CMD ["bash", "-c", "echo '[entrypoint] Iniciando Xvfb...'; Xvfb :99 -screen 0 1366x768x24 -nolisten tcp & sleep 2; export DISPLAY=:99; echo \"[entrypoint] DISPLAY=$DISPLAY. Iniciando aplicacao...\"; exec python -u main.py"]

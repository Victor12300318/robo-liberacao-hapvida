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

# Comando para iniciar o robô orquestrador
CMD ["python", "main.py"]

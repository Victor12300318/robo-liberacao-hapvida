@echo off
title Compilador do Robo de Liberacao
echo ===================================================
echo COMPILANDO ROBO DE LIBERACAO PARA EXECUTAVEL (.EXE)
echo ===================================================
echo.
echo 1. Instalando as dependencias do requirements.txt...
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERRO] Falha ao instalar dependencias! Certifique-se de que o Python e o pip estao instalados e no PATH.
    pause
    exit /b
)
echo.
echo 2. Gerando executavel compacto (.exe) com o PyInstaller...
python -m PyInstaller --onefile --console --name="robo-liberacao" main.py
if %errorlevel% neq 0 (
    echo [ERRO] Falha durante o processo de compilacao do PyInstaller!
    pause
    exit /b
)
echo.
echo ===================================================
echo COMPILACAO CONCLUIDA COM SUCESSO!
echo.
echo O arquivo "robo-liberacao.exe" foi gerado na pasta:
echo =^> .\dist\robo-liberacao.exe
echo.
echo INSTRUCOES DE USO NA VM:
echo 1. Copie o "robo-liberacao.exe" (da pasta dist) para a sua VM.
echo 2. Crie um arquivo ".env" na MESMA PASTA do seu ".exe" na VM.
echo 3. Configure as credenciais de banco e zendesk no ".env".
echo 4. Na primeira execucao na VM, abra o terminal e rode:
echo    "playwright install chromium" (para instalar o navegador na VM).
echo 5. Execute o "robo-liberacao.exe" para iniciar o robo!
echo ===================================================
pause

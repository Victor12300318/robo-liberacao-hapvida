import os
import sys

# Força o Playwright a buscar/instalar navegadores na pasta padrão do usuário (%USERPROFILE%\AppData\Local\ms-playwright).
# Isso é um requisito crítico quando rodamos compilados como executável (.exe) pelo PyInstaller.
if "LOCALAPPDATA" in os.environ:
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(os.environ["LOCALAPPDATA"], "ms-playwright")

import time
import logging
from dotenv import load_dotenv

# Configura o logger para imprimir data, hora, tipo e mensagem
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Determina o diretório base (seja do script Python ou do executável do PyInstaller)
if getattr(sys, 'frozen', False):
    dir_path = os.path.dirname(sys.executable)
else:
    dir_path = os.path.dirname(os.path.abspath(__file__))

# Carrega o .env localizado no mesmo diretório do executável/script
dotenv_path = os.path.join(dir_path, '.env')
load_dotenv(dotenv_path)

# Importações dos módulos criados
from db import init_db, obter_proximo_registro, atualizar_sucesso, atualizar_falha
from bot import executar_liberacao
from zendesk import enviar_comprovante_zendesk, resolver_ticket_com_mensagem_publica
from slack_client import enviar_alerta_slack

def main():
    logger.info("=============================================")
    logger.info("Iniciando Robô de Liberação de Atendimento 24/7")
    logger.info("=============================================")
    
    # 0. Garante instalação do navegador Chromium do Playwright de forma programática.
    # O módulo "playwright.cli" foi removido nas versões recentes (>= 1.40); o ponto de
    # entrada correto agora é "playwright.__main__.main", que executa o driver Node
    # empacotado (funciona tanto em Docker quanto no .exe do PyInstaller).
    # Em Docker a imagem oficial já traz o Chromium, então este passo apenas confirma.
    try:
        from playwright.__main__ import main as playwright_cli
        logger.info("Verificando instalação do navegador Chromium (isso pode demorar na primeira execução)...")
        argv_original = sys.argv
        sys.argv = ["playwright", "install", "chromium"]
        try:
            playwright_cli()
        finally:
            sys.argv = argv_original
    except SystemExit as e:
        if e.code in (0, None):
            logger.info("Navegador Chromium verificado/instalado com sucesso!")
        else:
            logger.critical(f"Falha ao instalar o Chromium (código de saída {e.code}).")
    except Exception as e:
        logger.critical(f"Não foi possível verificar ou instalar o Chromium: {e}")
    
    # 1. Inicializa o Banco de Dados (Garante criação de tabelas)
    try:
        init_db()
    except Exception as e:
        logger.critical(f"Falha crítica ao iniciar o banco de dados. O robô irá tentar prosseguir, mas pode falhar: {e}")

    # Define se rodará headless (sem interface). Padrão é True para VPS/Docker.
    headless_mode = os.getenv("HEADLESS", "True").lower() == "true"

    # Cool-down entre tickets: processar liberações em rajada rebaixa o score do reCAPTCHA v3.
    # Esperamos um intervalo entre um ticket e outro para o score se recuperar. Configurável
    # via .env (COOLDOWN_ENTRE_TICKETS, em segundos); padrão 240s (folgado para VPS sem proxy,
    # onde o IP de datacenter já parte de um score baixo).
    cooldown_segundos = int(os.getenv("COOLDOWN_ENTRE_TICKETS", "240"))

    # 2. Loop de execução contínuo (modo fila única)
    while True:
        try:
            # Consulta o próximo item disponível na fila de forma segura
            registro = obter_proximo_registro()
            
            if registro:
                registro_id = registro['id']
                login = registro['login']
                senha = registro['senha']
                carteirinha = registro['carteirinha']
                ticket = registro['ticket']
                cpf = registro.get('cpf')
                
                logger.info(f"--- Processando Ticket {ticket} ---")
                
                # Executa a reativação no Playwright
                sucesso, mensagem, caminho_arquivo = executar_liberacao(
                    login=login,
                    senha=senha,
                    carteirinha=carteirinha,
                    ticket=ticket,
                    headless=headless_mode
                )
                
                if sucesso:
                    # Caso A ou B: Sucesso na reativação ou Cliente já ativo
                    logger.info(f"Sucesso na reativação do Ticket {ticket}: {mensagem}")
                    
                    envio_ok = True
                    erro_api = ""
                    
                    # 1. Envia o comprovante como observação PRIVADA para auditoria interna
                    if caminho_arquivo and os.path.exists(caminho_arquivo):
                        upload_sucesso = enviar_comprovante_zendesk(ticket, caminho_arquivo, mensagem)
                        if not upload_sucesso:
                            envio_ok = False
                            erro_api = "Falha ao enviar comprovante privado para o Zendesk."
                        
                        # Remove o comprovante local para economizar espaço em disco na VPS
                        try:
                            os.remove(caminho_arquivo)
                            logger.info(f"Comprovante local {caminho_arquivo} removido para liberar espaço.")
                        except Exception as e_rm:
                            logger.warning(f"Não foi possível remover o arquivo temporário {caminho_arquivo}: {e_rm}")
                    
                    if envio_ok:
                        # 2. Formata e envia a resposta PÚBLICA para o cliente e define o ticket como RESOLVIDO
                        adm_valor = registro.get('adm') or 'Equipe de Atendimento'
                        tel_0800_valor = registro.get('tel_0800') or '0800'
                        
                        mensagem_publica = (
                            "Olá!\n"
                            "\n"
                            "Informamos que o seu plano consta como ativo e disponível para utilização. "
                            "Pedimos, por gentileza, que realize uma nova tentativa de uso.\n"
                            "\n"
                            "Permanecemos à disposição para auxiliá-lo(a) caso necessário.\n"
                            "Em caso de dúvidas, entre em contato pelo telefone {tel_0800}.\n"
                            "\n"
                            "Atenciosamente,\n"
                            "{adm}"
                        ).format(tel_0800=tel_0800_valor, adm=adm_valor)
                        
                        resolvido_sucesso = resolver_ticket_com_mensagem_publica(ticket, mensagem_publica, adm_valor)
                        if not resolvido_sucesso:
                            envio_ok = False
                            erro_api = "Falha ao resolver o ticket com mensagem pública no Zendesk."
                    
                    if envio_ok:
                        # Se tudo (Playwright + Zendesk) deu certo, marca sucesso no banco
                        atualizar_sucesso(registro_id)
                    else:
                        # Se o Playwright deu certo mas a API do Zendesk falhou, marca como falha e manda Slack!
                        logger.error(f"Erro de integração Zendesk para o Ticket {ticket}: {erro_api}")
                        atualizar_falha(registro_id, erro_api)
                        enviar_alerta_slack(cpf, ticket, erro_api)
                else:
                    # Caso C: Ocorreu alguma falha
                    logger.error(f"Falha ao processar Ticket {ticket}: {mensagem}")
                    
                    # Atualiza o banco (incrementa tentativa ou define como 'falhou')
                    atualizar_falha(registro_id, mensagem)
                    
                    # Envia alerta no Slack via webhook do n8n
                    enviar_alerta_slack(cpf, ticket, mensagem)
                    
                    # Limpa o screenshot de erro local apenas se estiver em modo headless (VPS/Produção)
                    # Se estiver em modo visual (desenvolvimento local), mantém para o desenvolvedor analisar!
                    if headless_mode and caminho_arquivo and os.path.exists(caminho_arquivo):
                        try:
                            os.remove(caminho_arquivo)
                            logger.info(f"Screenshot de erro local {caminho_arquivo} removido.")
                        except Exception as e_rm:
                            logger.warning(f"Não foi possível remover o print de erro {caminho_arquivo}: {e_rm}")
                
                # Cool-down após CADA ticket (sucesso ou falha) para preservar o score do
                # reCAPTCHA v3. Sem isso, o robô processa em rajada e queima a reputação do perfil/IP.
                logger.info(f"Aguardando {cooldown_segundos}s antes do próximo ticket (preserva o score do reCAPTCHA)...")
                time.sleep(cooldown_segundos)
                            
            else:
                # Se não há registros pendentes, aguarda 10 segundos para nova consulta
                logger.debug("Nenhum registro pendente na fila. Aguardando 10 segundos...")
                time.sleep(10)
                
        except Exception as e:
            logger.error(f"Erro inesperado no loop principal do orquestrador: {e}")
            logger.info("Reiniciando ciclo de verificação em 10 segundos...")
            time.sleep(10)

if __name__ == "__main__":
    main()

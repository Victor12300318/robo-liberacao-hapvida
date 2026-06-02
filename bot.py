import os
import time
import logging
from playwright.sync_api import sync_playwright, Playwright

logger = logging.getLogger(__name__)

def executar_liberacao(login, senha, carteirinha, ticket, headless=True):
    """
    Executa o fluxo do Playwright para reativação do plano na Hapvida.
    Retorna uma tupla (sucesso, mensagem, caminho_comprovante)
    """
    caminho_comprovante = f"comprovante_{ticket}.png"
    caminho_erro = f"erro_{ticket}.png"
    
    # Remove arquivos anteriores do mesmo ticket se existirem
    for f in [caminho_comprovante, caminho_erro]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass

    logger.info(f"Iniciando Playwright para Ticket {ticket} (Carteirinha: {carteirinha}). Modo Headless: {headless}")
    
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(
                headless=headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"] # Configurações recomendadas para rodar dentro de Docker
            )
            context = browser.new_context()
            page = context.new_page()
            
            # Define timeout padrão de 30 segundos
            page.set_default_timeout(30000)
            
            logger.info("Acessando página de login da Hapvida...")
            page.goto("https://www.hapvida.com.br/pls/webhap/webNewCadastroUsuario.Login")
            
            logger.info(f"Preenchendo código da empresa (login): {login}")
            page.locator("input[name=\"pCodigoEmpresa\"]").click()
            page.locator("input[name=\"pCodigoEmpresa\"]").fill(login)
            
            # Clica no container de login (passo necessário no site da Hapvida)
            page.locator("#webNewCadastroUsuario").click()
            
            logger.info("Preenchendo senha...")
            page.locator("#pSenha").click()
            page.locator("#pSenha").fill(senha)
            
            logger.info("Clicando em Prosseguir...")
            page.get_by_role("button", name="Prosseguir").click()
            
            # --- INTELIGÊNCIA DE NAVEGAÇÃO PÓS-LOGIN (MÁQUINA DE ESTADOS DINÂMICA) ---
            logger.info("Iniciando orquestração inteligente de navegação pós-login...")
            
            # Executa uma busca por estados durante um timeout total de até 25 segundos
            navegacao_concluida = False
            for i in range(50): # 50 * 0.5s = 25 segundos
                # Estado 1: Se o botão "Avançar" estiver visível na tela, clica nele!
                if page.get_by_role("button", name="Avançar").is_visible():
                    logger.info("Detectada tela intermediária 'Avançar'. Clicando...")
                    page.get_by_role("button", name="Avançar").click()
                    time.sleep(1) # Intervalo curto para iniciar transição
                    continue # Reinicia o loop para verificar o próximo estado
                
                # Estado 2: Se a tela de "Movimentações Pendentes" estiver visível.
                # Identificamos ela de forma única pela presença do texto "Movimentações Pendentes" ou do botão "Acessar Pendência"
                elif page.locator('text="Movimentações Pendentes"').is_visible() or page.get_by_role("button", name="Acessar Pendência").is_visible():
                    logger.info("Detectada tela 'Movimentações Pendentes'. Clicando em Prosseguir...")
                    page.get_by_role("button", name="Prosseguir").click()
                    time.sleep(1)
                    continue
                
                # Estado 3: Se o menu principal já estiver carregado (cabeçalho "ATENDIMENTO MÉDICO" visível)
                elif page.get_by_role("heading", name="ATENDIMENTO MÉDICO").is_visible():
                    logger.info("Menu principal detectado com sucesso!")
                    navegacao_concluida = True
                    break
                
                time.sleep(0.5)
                
            if not navegacao_concluida:
                logger.warning("Não foi possível confirmar o menu principal pelas checagens ativas. Tentando prosseguir...")
            
            logger.info("Acessando ATENDIMENTO MÉDICO...")
            page.get_by_role("heading", name="ATENDIMENTO MÉDICO").click()
            
            logger.info("Clicando em Reativar...")
            page.get_by_role("link", name="Reativar").click()
            
            logger.info(f"Preenchendo número da carteirinha: {carteirinha}")
            page.get_by_role("textbox").click()
            page.get_by_role("textbox").fill(carteirinha)
            
            logger.info("Clicando em Prosseguir para consultar beneficiário...")
            page.get_by_role("button", name="Prosseguir").click()
            
            # --- INTELIGÊNCIA DE DECISÃO ---
            logger.info("Aguardando decisão da tela (Reativar ou Já Consta Ativo)...")
            estado_detectado = None
            
            # Aguarda até 15 segundos, verificando a cada 1 segundo
            for i in range(15):
                # Caso 1: Já consta ativo
                if page.locator('text="CLIENTE JÁ CONSTA ATIVO."').is_visible() or page.locator('text="Cliente já consta ativo"').is_visible():
                    estado_detectado = "ja_ativo"
                    break
                # Caso 2: Botão Reativar disponível
                if page.get_by_role("button", name="Reativar").is_visible():
                    estado_detectado = "reativar"
                    break
                time.sleep(1)
                
            if estado_detectado == "ja_ativo":
                logger.info("Detectado: CLIENTE JÁ CONSTA ATIVO.")
                # Tira o print da tela de ativo
                page.screenshot(path=caminho_comprovante, full_page=True)
                context.close()
                browser.close()
                return True, "Cliente já consta ativo no sistema da Hapvida.", caminho_comprovante
                
            elif estado_detectado == "reativar":
                logger.info("Detectado: Botão 'Reativar' visível. Efetuando reativação...")
                page.get_by_role("button", name="Reativar").click()
                
                # Aguarda processamento de sucesso
                time.sleep(3)
                
                # Tira screenshot do sucesso da reativação
                page.screenshot(path=caminho_comprovante, full_page=True)
                logger.info("Reativação realizada com sucesso! Screenshot salvo.")
                context.close()
                browser.close()
                return True, "Segue em anexo o print da reativação realizada pelo robô.", caminho_comprovante
                
            else:
                # Caso não tenha detectado nenhum dos dois
                logger.warning("Não foi possível determinar se o cliente está ativo ou se o botão reativar está presente.")
                # Tira screenshot do erro/tela desconhecida
                page.screenshot(path=caminho_erro, full_page=True)
                context.close()
                browser.close()
                return False, "Não foi possível determinar o estado (Reativar ou Já Ativo) pós-prosseguir.", caminho_erro

        except Exception as e:
            logger.error(f"Erro durante a execução do Playwright: {e}")
            try:
                # Tenta capturar um screenshot do erro antes de fechar o navegador
                page.screenshot(path=caminho_erro, full_page=True)
                logger.info(f"Screenshot do erro salvo em: {caminho_erro}")
            except Exception as e_screenshot:
                logger.error(f"Não foi possível tirar screenshot do erro: {e_screenshot}")
            
            try:
                context.close()
                browser.close()
            except Exception:
                pass
                
            return False, str(e), caminho_erro if os.path.exists(caminho_erro) else None

import os
import time
import logging
from playwright.sync_api import sync_playwright, Playwright

logger = logging.getLogger(__name__)


def _perfil_navegador():
    """
    Retorna um diretório de perfil persistente e gravável para o Chromium.
    O login da Hapvida é protegido por reCAPTCHA v3 (baseado em score de bot).
    Reaproveitar o mesmo perfil entre execuções acumula cookies do Google e eleva
    o score, evitando o erro "NÃO FOI POSSÍVEL VALIDAR O CAPTCHA".
    """
    base = os.path.join(os.path.expanduser("~"), ".robo_liberacao_perfil")
    os.makedirs(base, exist_ok=True)
    return base


def _config_proxy():
    """
    Monta a configuração de proxy do Playwright a partir do .env, ou None se não houver.
    Em VPS o IP é de datacenter, o que derruba o score do reCAPTCHA v3. Rotear o tráfego
    por um proxy/IP RESIDENCIAL faz o login parecer um usuário doméstico real.

    Variáveis (.env):
      PROXY_SERVER   ex.: http://gate.provedor.com:8000  (ou socks5://host:porta)
      PROXY_USERNAME (opcional)
      PROXY_PASSWORD (opcional)
    """
    server = os.getenv("PROXY_SERVER")
    if not server:
        return None
    proxy = {"server": server}
    usuario = os.getenv("PROXY_USERNAME")
    senha = os.getenv("PROXY_PASSWORD")
    if usuario:
        proxy["username"] = usuario
    if senha:
        proxy["password"] = senha
    logger.info(f"Proxy configurado via .env: {server}")
    return proxy


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
    
    # Inicializados como None para o bloco de tratamento de erro não quebrar
    # caso a própria criação do navegador/página falhe (ex.: falta de X server).
    context = None
    page = None
    
    with sync_playwright() as playwright:
        try:
            # Usa um contexto PERSISTENTE (perfil em disco) em vez de um navegador efêmero.
            # O login da Hapvida usa reCAPTCHA v3 (score de bot): com perfil limpo o score
            # é baixo e o servidor responde "NÃO FOI POSSÍVEL VALIDAR O CAPTCHA". Reaproveitar
            # o perfil + reduzir o fingerprint de automação eleva o score e o login passa.
            context = playwright.chromium.launch_persistent_context(
                _perfil_navegador(),
                headless=headless,
                proxy=_config_proxy(),
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    # Remove o flag de automação detectado pelo reCAPTCHA
                    "--disable-blink-features=AutomationControlled",
                ],
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
                viewport={"width": 1366, "height": 768},
                locale="pt-BR",
            )
            # navigator.webdriver=true é fortemente penalizado pelo reCAPTCHA v3; mascaramos.
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            page = context.new_page()
            
            # Define timeout padrão de 30 segundos
            page.set_default_timeout(30000)
            
            # Aquecimento AGRESSIVO: simula uma sessão de navegação real antes do login.
            # O reCAPTCHA v3 dá score maior para sessões que parecem ter histórico/contexto
            # humano (várias páginas, scroll, mouse, tempo). Em vez de só abrir a home e ir
            # direto pro login, navegamos por algumas páginas internas com pausas e scroll.
            logger.info("Aquecendo a sessão navegando pelo site da Hapvida (modo agressivo)...")

            def _scroll_humano(page, ciclos=3):
                """Faz scroll para baixo/cima com pausas, movendo o mouse, simulando leitura."""
                try:
                    for _ in range(ciclos):
                        page.mouse.move(300 + (_ * 120), 250 + (_ * 80))
                        page.mouse.wheel(0, 600)
                        page.wait_for_timeout(1400)
                    page.mouse.wheel(0, -400)
                    page.wait_for_timeout(1500)
                except Exception as e_sc:
                    logger.warning(f"Falha no scroll humano (ignorando): {e_sc}")

            # Páginas internas visitadas em sequência para construir contexto de sessão real.
            paginas_aquecimento = [
                "https://www.hapvida.com.br/",
                "https://www2.hapvida.com.br/beneficiario",
                "https://www2.hapvida.com.br/planos-de-saude-individuais",
            ]
            for url_aquec in paginas_aquecimento:
                try:
                    logger.info(f"Aquecimento: visitando {url_aquec}")
                    page.goto(url_aquec)
                    page.wait_for_timeout(2500)
                    _scroll_humano(page, ciclos=3)
                except Exception as e_warm:
                    logger.warning(f"Falha ao aquecer em {url_aquec} (ignorando): {e_warm}")
            page.wait_for_timeout(2000)
            
            logger.info("Acessando página de login da Hapvida...")
            page.goto("https://www.hapvida.com.br/pls/webhap/webNewCadastroUsuario.Login")
            
            # O login da Hapvida usa reCAPTCHA v3 (score de bot). Com o perfil ainda "frio"
            # o token pode ser recusado ("NÃO FOI POSSÍVEL VALIDAR O CAPTCHA"). Cada tentativa
            # esquenta o perfil (cookies do Google), então repetimos o login internamente
            # algumas vezes antes de desistir — assim não desperdiçamos as tentativas da fila.
            MAX_TENTATIVAS_LOGIN = 4
            login_ok = False
            for tentativa_login in range(1, MAX_TENTATIVAS_LOGIN + 1):
                logger.info(f"Tentativa de login {tentativa_login}/{MAX_TENTATIVAS_LOGIN} (código: {login})...")
                
                # Digitação "humana": click + type com atraso entre teclas, em vez de fill
                # instantâneo. Preenchimento instantâneo é um sinal forte de automação para
                # o reCAPTCHA v3; digitar tecla a tecla com pausas eleva o score.
                campo_codigo = page.locator("input[name=\"pCodigoEmpresa\"]")
                campo_codigo.click()
                page.wait_for_timeout(400)
                campo_codigo.type(login, delay=140)
                
                # Clica no container de login (passo necessário no site da Hapvida)
                page.locator("#webNewCadastroUsuario").click()
                page.wait_for_timeout(500)
                
                campo_senha = page.locator("#pSenha")
                campo_senha.click()
                page.wait_for_timeout(400)
                campo_senha.type(senha, delay=140)
                
                # Aguarda a biblioteca do reCAPTCHA v3 carregar antes de submeter. O próprio
                # site dispara grecaptcha.execute() no clique de "Prosseguir"; só garantimos
                # que a lib esteja pronta para não submeter um token vazio.
                try:
                    page.wait_for_function(
                        "() => window.grecaptcha && typeof window.grecaptcha.execute === 'function'",
                        timeout=20000,
                    )
                    page.evaluate("() => new Promise(resolve => window.grecaptcha.ready(resolve))")
                except Exception as e_captcha:
                    logger.warning(f"Não foi possível confirmar o carregamento do reCAPTCHA; prosseguindo: {e_captcha}")
                
                # Permanência "humana" ANTES do Prosseguir. O score do reCAPTCHA v3 é calculado
                # no momento em que o token é gerado (no clique). Quanto mais tempo na página e
                # mais sinais de interação (mouse/scroll) antes disso, maior o score. Clicar
                # imediatamente após preencher é um padrão robótico que derruba o score.
                logger.info("Simulando interação humana na tela de login antes de prosseguir...")
                try:
                    page.mouse.move(400, 300)
                    page.wait_for_timeout(800)
                    page.mouse.move(700, 450)
                    page.mouse.wheel(0, 250)
                    page.wait_for_timeout(1200)
                    page.mouse.wheel(0, -150)
                    page.mouse.move(550, 380)
                except Exception as e_mov:
                    logger.warning(f"Falha ao simular interação (ignorando): {e_mov}")
                # Dwell time total antes do clique (preenchimento -> submit) na faixa de ~6-8s.
                page.wait_for_timeout(5000)
                
                logger.info("Clicando em Prosseguir...")
                page.get_by_role("button", name="Prosseguir").click()
                time.sleep(2)
                
                # Credencial inválida é definitiva: não adianta repetir, retorna na hora.
                if page.get_by_text("NÃO CONFEREM", exact=False).is_visible():
                    logger.error("Login bloqueado: código/senha não conferem.")
                    page.screenshot(path=caminho_erro, full_page=True)
                    context.close()
                    return False, "Código/senha não conferem no sistema da Hapvida.", caminho_erro
                
                # Falha de captcha: NÃO adianta repetir em rajada (retry rápido afunda ainda
                # mais o score do reCAPTCHA v3). Aplicamos um backoff crescente para dar tempo
                # do score se recuperar antes de recarregar e tentar de novo.
                if page.get_by_text("VALIDAR O CAPTCHA", exact=False).is_visible():
                    espera = 15 * tentativa_login  # 15s, 30s, 45s, ...
                    logger.warning(f"reCAPTCHA recusado na tentativa {tentativa_login}. Aguardando {espera}s (backoff) antes de recarregar...")
                    time.sleep(espera)
                    page.goto("https://www.hapvida.com.br/pls/webhap/webNewCadastroUsuario.Login")
                    page.wait_for_timeout(2500)
                    continue
                
                # Sem mensagens de erro: login passou.
                login_ok = True
                break
            
            if not login_ok:
                logger.error("Login bloqueado: reCAPTCHA não validado após múltiplas tentativas.")
                page.screenshot(path=caminho_erro, full_page=True)
                context.close()
                return False, "Falha na validação do reCAPTCHA no login da Hapvida (após múltiplas tentativas).", caminho_erro
            
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
                return True, "Segue em anexo o print da reativação realizada pelo robô.", caminho_comprovante
                
            else:
                # Caso não tenha detectado nenhum dos dois
                logger.warning("Não foi possível determinar se o cliente está ativo ou se o botão reativar está presente.")
                # Tira screenshot do erro/tela desconhecida
                page.screenshot(path=caminho_erro, full_page=True)
                context.close()
                return False, "Não foi possível determinar o estado (Reativar ou Já Ativo) pós-prosseguir.", caminho_erro

        except Exception as e:
            logger.error(f"Erro durante a execução do Playwright: {e}")
            try:
                # Tenta capturar um screenshot do erro antes de fechar o navegador
                if page is not None:
                    page.screenshot(path=caminho_erro, full_page=True)
                    logger.info(f"Screenshot do erro salvo em: {caminho_erro}")
            except Exception as e_screenshot:
                logger.error(f"Não foi possível tirar screenshot do erro: {e_screenshot}")
            
            try:
                if context is not None:
                    context.close()
            except Exception:
                pass
                
            return False, str(e), caminho_erro if os.path.exists(caminho_erro) else None

import re
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://www.hapvida.com.br/pls/webhap/webNewCadastroUsuario.Login")
    page.locator("input[name=\"pCodigoEmpresa\"]").click()
    page.locator("input[name=\"pCodigoEmpresa\"]").fill("2MXXU")
    page.locator("#webNewCadastroUsuario").click()
    page.locator("#pSenha").click()
    page.locator("#pSenha").fill("072024")
    page.get_by_role("button", name="Prosseguir").click()
    page.get_by_role("button", name="Avançar").click()
    page.get_by_role("heading", name="ATENDIMENTO MÉDICO").click()
    page.get_by_role("link", name="Reativar").click()
    page.get_by_role("textbox").click()
    page.get_by_role("textbox").fill("2MXXU000028")
    page.get_by_role("button", name="Prosseguir").click()
    page.get_by_role("button", name="Reativar").click()

    # --- NOVO TRECHO ADICIONADO ---
    # Aguarda 3 segundos para a página processar e exibir o resultado final
    page.wait_for_timeout(3000)

    # Tira o print e salva na pasta do seu script
    caminho_imagem = "comprovante_reativacao.png"
    page.screenshot(path=caminho_imagem, full_page=True)
    print(f"Print tirado com sucesso e salvo como: {caminho_imagem}")
    # -------------------------------

    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)
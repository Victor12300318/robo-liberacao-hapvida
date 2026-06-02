import os
import requests
import logging

logger = logging.getLogger(__name__)

def enviar_comprovante_zendesk(ticket_id, caminho_arquivo="comprovante_reativacao.png", mensagem="Segue em anexo o print da reativação realizada pelo robô."):
    """
    Realiza o upload do comprovante e publica um comentário no ticket correspondente do Zendesk.
    """
    subdomain = os.getenv("ZENDESK_SUBDOMAIN", "affixatendimento")
    email = os.getenv("ZENDESK_EMAIL", "Supervisao@headsetbrasil.com")
    token = os.getenv("ZENDESK_TOKEN", "Basic aW5mcmFlc3RydXR1cmFAYWZmaXguY29tLmJyL3Rva2VuOjk1ZVRmQVVseEtWRjlEajNMSjdvM3Ywd1FlZGt4SnRJV0p5a3RZV0M=")

    if not os.path.exists(caminho_arquivo):
        logger.error(f"Arquivo de comprovante {caminho_arquivo} não encontrado. Não é possível enviar ao Zendesk.")
        return False

    # Configuração dos cabeçalhos e autenticação de forma inteligente
    headers = {}
    if token.startswith("Basic "):
        headers["Authorization"] = token
        auth = None
        logger.info("Usando cabeçalho de autorização direto (Basic Auth pré-codificado).")
    else:
        auth = (f"{email}/token", token)
        logger.info("Usando autenticação básica de email/token do Zendesk.")

    # 1. Fazer o upload do arquivo para o Zendesk
    upload_url = f"https://{subdomain}.zendesk.com/api/v2/uploads.json?filename=comprovante.png"
    upload_headers = headers.copy()
    upload_headers["Content-Type"] = "application/binary"
    
    try:
        with open(caminho_arquivo, "rb") as f:
            arquivo_binario = f.read()
        
        logger.info(f"Iniciando upload do comprovante para o Zendesk para o ticket {ticket_id}...")
        response_upload = requests.post(upload_url, headers=upload_headers, data=arquivo_binario, auth=auth, timeout=30)

        if response_upload.status_code == 201:
            token_anexo = response_upload.json()["upload"]["token"]
            logger.info(f"Upload concluído. Token do anexo: {token_anexo}")

            # 2. Associar o anexo a um comentário em um ticket existente
            ticket_url = f"https://{subdomain}.zendesk.com/api/v2/tickets/{ticket_id}.json"
            ticket_payload = {
                "ticket": {
                    "comment": {
                        "body": mensagem,
                        "uploads": [token_anexo],
                        "public": False
                    }
                }
            }
            
            logger.info(f"Publicando comentário no ticket {ticket_id}...")
            response_ticket = requests.put(ticket_url, json=ticket_payload, headers=headers, auth=auth, timeout=30)
            if response_ticket.status_code == 200:
                logger.info(f"Comentário com anexo publicado com sucesso no ticket {ticket_id}!")
                return True
            else:
                logger.error(f"Erro ao atualizar o ticket {ticket_id}: {response_ticket.text}")
                return False
                
        else:
            logger.error(f"Erro ao realizar upload do arquivo para o Zendesk: {response_upload.text}")
            return False
            
    except Exception as e:
        logger.error(f"Exceção ocorrida na comunicação com Zendesk: {e}")
        return False

def resolver_ticket_com_mensagem_publica(ticket_id, mensagem, atendente_nome="Robô de Atendimento"):
    """
    Publica um comentário público no ticket, preenche os campos obrigatórios e define o seu status como 'solved' (resolvido).
    """
    subdomain = os.getenv("ZENDESK_SUBDOMAIN", "affixatendimento")
    email = os.getenv("ZENDESK_EMAIL", "Supervisao@headsetbrasil.com")
    token = os.getenv("ZENDESK_TOKEN", "Basic aW5mcmFlc3RydXR1cmFAYWZmaXguY29tLmJyL3Rva2VuOjk1ZVRmQVVseEtWRjlEajNMSjdvM3Ywd1FlZGt4SnRJV0p5a3RZV0M=")

    headers = {}
    if token.startswith("Basic "):
        headers["Authorization"] = token
        auth = None
        logger.info("Usando cabeçalho de autorização direto para fechar o ticket.")
    else:
        auth = (f"{email}/token", token)
        logger.info("Usando autenticação básica de email/token para fechar o ticket.")

    ticket_url = f"https://{subdomain}.zendesk.com/api/v2/tickets/{ticket_id}.json"
    
    # Payload para adicionar comentário público, preencher campos obrigatórios E mudar status para 'solved'
    ticket_payload = {
        "ticket": {
            "comment": {
                "body": mensagem,
                "public": True
            },
            "status": "solved",
            "custom_fields": [
                {"id": 17378080644759, "value": "realizou_pagamento"},
                {"id": 24824957448983, "value": "Automação de liberação"}
            ]
        }
    }

    try:
        logger.info(f"Publicando comentário público e resolvendo o ticket {ticket_id}...")
        response_ticket = requests.put(ticket_url, json=ticket_payload, headers=headers, auth=auth, timeout=30)
        if response_ticket.status_code == 200:
            logger.info(f"Ticket {ticket_id} respondido publicamente e resolvido com sucesso!")
            return True
        else:
            logger.error(f"Erro ao resolver o ticket {ticket_id}: {response_ticket.text}")
            return False
    except Exception as e:
        logger.error(f"Exceção ocorrida ao fechar o ticket {ticket_id}: {e}")
        return False

import os
import requests
import logging

logger = logging.getLogger(__name__)

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

def enviar_alerta_slack(cpf, ticket, erro_msg):
    """
    Envia um alerta de falha para o Slack via webhook do n8n.
    """
    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL não configurado. Ignorando envio de alerta.")
        return

    mensagem_formatada = (
        f"🚨 *Falha no Robô de Liberação*\n"
        f"• *Ticket:* {ticket}\n"
        f"• *CPF:* {cpf if cpf else 'Não fornecido'}\n"
        f"• *Erro:* {erro_msg}"
    )

    payload = {
        "Mensagem": mensagem_formatada
    }

    try:
        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        if response.status_code in [200, 201]:
            logger.info(f"Alerta do ticket {ticket} enviado com sucesso para o Slack!")
        else:
            logger.error(f"Erro ao enviar alerta para o Slack ({response.status_code}): {response.text}")
    except Exception as e:
        logger.error(f"Exceção ao enviar alerta para o Slack: {e}")

import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
import sys
from dotenv import load_dotenv

# Configura logs
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

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")

def get_connection():
    """Retorna uma nova conexão com o PostgreSQL."""
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS
    )

def init_db():
    """Inicializa o banco de dados, cria/migra tabelas e limpa registros órfãos 'processando'."""
    logger.info("Verificando/Criando tabela no banco de dados...")
    
    # Tenta conectar e criar a tabela
    try:
        conn = get_connection()
        conn.autocommit = True
        with conn.cursor() as cursor:
            # Cria a tabela de fila de reativação
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS fila_reativacao (
                    id SERIAL PRIMARY KEY,
                    login VARCHAR(50) NOT NULL,
                    senha VARCHAR(100) NOT NULL,
                    carteirinha VARCHAR(100) NOT NULL,
                    ticket VARCHAR(50) NOT NULL,
                    cpf VARCHAR(20),
                    cod_seg VARCHAR(20),
                    status VARCHAR(20) DEFAULT 'pendente',
                    tentativas INT DEFAULT 0,
                    erro_mensagem TEXT,
                    adm VARCHAR(100),
                    tel_0800 VARCHAR(50),
                    criado_em TIMESTAMP DEFAULT NOW(),
                    atualizado_em TIMESTAMP DEFAULT NOW()
                );
            """)
            # Executa migrações para adicionar as colunas caso a tabela já exista
            cursor.execute("ALTER TABLE fila_reativacao ADD COLUMN IF NOT EXISTS adm VARCHAR(100);")
            cursor.execute("ALTER TABLE fila_reativacao ADD COLUMN IF NOT EXISTS tel_0800 VARCHAR(50);")
            logger.info("Tabela 'fila_reativacao' inicializada e migrada com sucesso!")
            
            # Reseta registros órfãos que ficaram presos em 'processando' (ex: após queda do robô anterior)
            cursor.execute("""
                UPDATE fila_reativacao
                SET status = 'pendente', atualizado_em = NOW()
                WHERE status = 'processando';
            """)
            logger.info("Registros antigos em estado 'processando' foram redefinidos para 'pendente' com sucesso!")
            
        conn.close()
    except Exception as e:
        logger.error(f"Erro ao inicializar o banco de dados: {e}")
        raise e

def obter_proximo_registro():
    """
    Busca o próximo registro pendente de forma segura (FOR UPDATE SKIP LOCKED),
    marca-o imediatamente como 'processando' para evitar concorrência e libera a trava.
    Retorna o dicionário do registro ou None se não houver registros.
    """
    conn = None
    registro = None
    try:
        conn = get_connection()
        # Iniciamos uma transação manual
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Seleciona o primeiro registro pendente travando-o para outros workers
            query_select = """
                SELECT id, login, senha, carteirinha, ticket, cpf, cod_seg, tentativas, adm, tel_0800
                FROM fila_reativacao
                WHERE status = 'pendente' AND tentativas < 3
                ORDER BY criado_em ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED;
            """
            cursor.execute(query_select)
            registro = cursor.fetchone()
            
            if registro:
                # Se encontrou, atualiza o status imediatamente para 'processando'
                query_update = """
                    UPDATE fila_reativacao
                    SET status = 'processando', atualizado_em = NOW()
                    WHERE id = %s;
                """
                cursor.execute(query_update, (registro['id'],))
                conn.commit()
                logger.info(f"Registro ID {registro['id']} (Ticket: {registro['ticket']}) reservado para processamento.")
            else:
                conn.rollback() # Nada selecionado, cancela transação
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Erro ao obter próximo registro da fila: {e}")
    finally:
        if conn:
            conn.close()
    return registro

def atualizar_sucesso(registro_id):
    """Atualiza o registro para 'concluido' com sucesso."""
    try:
        conn = get_connection()
        conn.autocommit = True
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE fila_reativacao
                SET status = 'concluido', atualizado_em = NOW()
                WHERE id = %s;
            """, (registro_id,))
            logger.info(f"Registro ID {registro_id} atualizado para 'concluido'.")
        conn.close()
    except Exception as e:
        logger.error(f"Erro ao atualizar sucesso para ID {registro_id}: {e}")

def atualizar_falha(registro_id, erro_msg):
    """
    Incrementa as tentativas e registra o erro. 
    Se atingir 3 tentativas, define status como 'falhou'.
    Caso contrário, devolve para 'pendente' para nova tentativa.
    """
    try:
        conn = get_connection()
        conn.autocommit = True
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Busca tentativas atuais
            cursor.execute("SELECT tentativas FROM fila_reativacao WHERE id = %s;", (registro_id,))
            reg = cursor.fetchone()
            novas_tentativas = reg['tentativas'] + 1 if reg else 1
            
            novo_status = 'falhou' if novas_tentativas >= 3 else 'pendente'
            
            cursor.execute("""
                UPDATE fila_reativacao
                SET status = %s, tentativas = %s, erro_mensagem = %s, atualizado_em = NOW()
                WHERE id = %s;
            """, (novo_status, novas_tentativas, erro_msg, registro_id))
            logger.info(f"Registro ID {registro_id} atualizado para status '{novo_status}' (Tentativa {novas_tentativas}). Erro: {erro_msg}")
        conn.close()
    except Exception as e:
        logger.error(f"Erro ao atualizar falha para ID {registro_id}: {e}")

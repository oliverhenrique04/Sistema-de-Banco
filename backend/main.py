from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
import os
import asyncpg
from typing import Optional
from passlib.hash import bcrypt_sha256
from passlib.context import CryptContext

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/finpay")
pwd_context = CryptContext(schemes=['bcrypt_sha256'], deprecated='auto')

# IDs dos Comerciantes
ALLOWED_UTILITY_MERCHANT_IDS = [11, 12, 13] 

app = FastAPI(
    title="POMENR API",
    version="1.5.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json"
)

def _int_or_none(v):
    try:
        return int(v) if v is not None else None
    except Exception:
        return None

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def get_pool():
    if not hasattr(app.state, "pool"):
        app.state.pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return app.state.pool

# ---------- MODELS ----------
class CreateUser(BaseModel):
    nome: str
    email: str
    telefone: Optional[str] = None
    doc_cpf_cnpj: str
    tipo_pessoa: str = 'PF' 

class CreateAccount(BaseModel):
    id_usuario: int

class Payment(BaseModel):
    id_conta_de: int
    id_comerciante: Optional[int] = None
    valor_cents: int
    referencia: Optional[str] = None

    @field_validator('id_conta_de', 'id_comerciante', 'valor_cents', mode='before')
    @classmethod
    def _coerce_int(cls, v): return _int_or_none(v)

class LoanRequest(BaseModel):
    id_conta: int
    principal_cents: int
    juros_aa_pct: float
    prazo_meses: int
    @field_validator('id_conta', 'principal_cents', 'prazo_meses', mode='before')
    @classmethod
    def _coerce_int(cls, v): return _int_or_none(v)

class Register(BaseModel):
    nome: str
    email: str
    telefone: Optional[str] = None
    doc_cpf_cnpj: str
    senha: str
    salario_mensal_cents: int
    tipo_pessoa: str = 'PF' 
    @field_validator('salario_mensal_cents', mode='before')
    @classmethod
    def _coerce_int(cls, v): return _int_or_none(v)

class Login(BaseModel):
    doc_cpf_cnpj: str
    senha: str

class PayInstallment(BaseModel):
    id_parcela: int
    id_conta: int
    @field_validator('id_parcela', 'id_conta', mode='before')
    @classmethod
    def _coerce_int(cls, v): return _int_or_none(v)

class LoanSim(BaseModel):
    principal_cents: int
    prazo_meses: int
    @field_validator('prazo_meses', 'principal_cents', mode='before')
    @classmethod
    def _coerce_int2(cls, v): return _int_or_none(v)

class Deposit(BaseModel):
    valor_cents: int
    id_conta: Optional[int] = None
    referencia: Optional[str] = "DEP-API"
    @field_validator('valor_cents', 'id_conta', mode='before')
    @classmethod
    def _coerce_int(cls, v): return _int_or_none(v)

class PayFullLoan(BaseModel):
    id_emprestimo: int
    id_conta: Optional[int] = None
    @field_validator('id_emprestimo', 'id_conta', mode='before')
    @classmethod
    def _coerce_int(cls, v): return _int_or_none(v)

class Transfer(BaseModel):
    identificador: str 
    valor_cents: int
    @field_validator('valor_cents', mode='before')
    @classmethod
    def _coerce_int(cls, v): return _int_or_none(v)

class UtilityPayment(BaseModel):
    id_comerciante: int
    valor_cents: int
    @field_validator('id_comerciante', 'valor_cents', mode='before')
    @classmethod
    def _coerce_int(cls, v): return _int_or_none(v)


# NOVO: Função para determinar juros anual dinâmico
def get_dynamic_interest_aa(prazo_meses: int) -> float:
    if prazo_meses <= 12:
        return 25.0  # 25% a.a. para curto prazo
    elif prazo_meses <= 24:
        return 30.0  # 30% a.a. para médio prazo
    else:
        return 35.0  # 35% a.a. para longo prazo

# Reutilizado: Taxa mensal de taxa anual
def monthly_rate_from_aa(aa_pct: float) -> float:
    return float((1 + aa_pct / 100.0) ** (1.0 / 12.0) - 1.0)

# NOVO: Função para calcular o pagamento mensal (PMT)
def calculate_pmt_cents(principal_cents: int, juros_aa_pct: float, prazo_meses: int) -> int:
    jm = monthly_rate_from_aa(juros_aa_pct)
    
    if prazo_meses <= 0 or principal_cents <= 0:
        return 0
    
    if jm == 0:
        pmt = principal_cents / prazo_meses
    else:
        # PMT formula (Sistema Price)
        pmt = principal_cents * (jm * (1 + jm)**prazo_meses) / ((1 + jm)**prazo_meses - 1)
        
    return int(round(pmt))


# ---------- LIFECYCLE ----------
@app.on_event("startup")
async def startup():
    await get_pool()

@app.get("/health")
async def health():
    return {"status": "ok"}

# ---------- AUTH ----------
@app.post("/auth/register")
async def auth_register(body: Register):
    sql_user = """
        INSERT INTO tb_usuario (nome,email,telefone,doc_cpf_cnpj,senha_hash, tipo_pessoa)
        VALUES ($1,$2,$3,$4,$5,$6)
        RETURNING id_usuario
    """
    sql_account = """
        INSERT INTO tb_conta (id_usuario, numero_conta, agencia, saldo_cents, salario_mensal_cents)
        VALUES ($1::bigint, to_char($1::bigint, 'FM00000000'), '0001', 0, $2::bigint)
        RETURNING id_conta
    """
    pool = await get_pool()
    async with pool.acquire() as con:
        tr = con.transaction()
        await tr.start()
        try:
            uid = await con.fetchval(
                sql_user,
                body.nome,
                body.email,
                body.telefone,
                body.doc_cpf_cnpj,
                bcrypt_sha256.hash(body.senha),
                body.tipo_pessoa
            )
            cid = await con.fetchval(sql_account, uid, body.salario_mensal_cents)
            await tr.commit()
            return {"id_usuario": uid, "id_conta": cid}
        except Exception as e:
            await tr.rollback()
            raise HTTPException(status_code=400, detail=str(e))

@app.post("/auth/login")
async def auth_login(body: Login):
    q = "SELECT id_usuario, senha_hash FROM tb_usuario WHERE doc_cpf_cnpj=$1"
    pool = await get_pool()
    async with pool.acquire() as con:
        row = await con.fetchrow(q, body.doc_cpf_cnpj)
        if not row:
            raise HTTPException(status_code=401, detail="CPF/CNPJ ou senha inválidos")
        if not bcrypt_sha256.verify(body.senha, row["senha_hash"] or ""):
            raise HTTPException(status_code=401, detail="CPF/CNPJ ou senha inválidos")
        return {"id_usuario": row["id_usuario"]}

# ---------- USERS/ACCOUNTS ----------
@app.post("/users")
async def create_user(body: CreateUser):
    sql_user = """
        INSERT INTO tb_usuario (nome,email,telefone,doc_cpf_cnpj,senha_hash, tipo_pessoa)
        VALUES ($1,$2,$3,$4,$5,$6)
        RETURNING id_usuario
    """
    sql_account = """
        INSERT INTO tb_conta (id_usuario, numero_conta, agencia, saldo_cents, salario_mensal_cents)
        VALUES ($1::bigint, to_char($1::bigint, 'FM00000000'), '0001', 0, 0)
        RETURNING id_conta
    """
    pool = await get_pool()
    async with pool.acquire() as con:
        tr = con.transaction()
        await tr.start()
        try:
            uid = await con.fetchval(
                sql_user,
                body.nome,
                body.email,
                body.telefone,
                body.doc_cpf_cnpj,
                bcrypt_sha256.hash("changeme"),
                body.tipo_pessoa
            )
            cid = await con.fetchval(sql_account, uid)
            await tr.commit()
            return {"id_usuario": uid, "id_conta": cid}
        except Exception as e:
            await tr.rollback()
            raise HTTPException(status_code=400, detail=str(e))

@app.post("/accounts")
async def create_account(body: CreateAccount):
    q = """
        INSERT INTO tb_conta (id_usuario, numero_conta, agencia, saldo_cents)
        VALUES ($1, LPAD(($1)::text,8,'0'), '0001', 0)
        RETURNING id_conta
    """
    pool = await get_pool()
    async with pool.acquire() as con:
        try:
            cid = await con.fetchval(q, body.id_usuario)
            return {"id_conta": cid}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

@app.get("/accounts/{id_conta}")
async def get_account(id_conta: int):
    q = """
        SELECT c.id_conta, u.nome, c.numero_conta, c.agencia, c.saldo_cents, c.status
        FROM tb_conta c
        JOIN tb_usuario u ON u.id_usuario=c.id_usuario
        WHERE c.id_conta=$1
    """
    pool = await get_pool()
    async with pool.acquire() as con:
        row = await con.fetchrow(q, id_conta)
        if not row:
            raise HTTPException(status_code=404, detail="Conta não encontrada")
        return dict(row)

@app.get("/me/summary/{id_usuario}")
async def me_summary(id_usuario: int):
    q = """
        SELECT c.id_conta, c.numero_conta, c.agencia, c.saldo_cents, u.tipo_pessoa
        FROM tb_conta c
        JOIN tb_usuario u ON u.id_usuario=c.id_usuario
        WHERE c.id_usuario=$1
        LIMIT 1
    """
    pool = await get_pool()
    async with pool.acquire() as con:
        row = await con.fetchrow(q, id_usuario)
        if not row:
            return {}
        return dict(row)

# ---------- DEPÓSITO ----------
@app.post("/accounts/deposit")
async def deposit(
    body: Deposit,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    user_id = _int_or_none(x_user_id)

    if user_id is None:
        raise HTTPException(status_code=401, detail="Não autenticado")

    if body.valor_cents is None or body.valor_cents <= 0:
        raise HTTPException(status_code=400, detail="Valor inválido para depósito")

    pool = await get_pool()
    async with pool.acquire() as con:
        tr = con.transaction()
        await tr.start()
        try:
            id_conta = body.id_conta
            if not id_conta:
                row = await con.fetchrow(
                    "SELECT id_conta FROM tb_conta WHERE id_usuario=$1",
                    user_id,
                )
                if not row:
                    raise HTTPException(status_code=400, detail="Conta não localizada")
                id_conta = row["id_conta"]

            tid = await con.fetchval(
                """
                INSERT INTO tb_transacao (id_conta_para, tipo, valor_cents, status, referencia)
                VALUES ($1, 'deposit', $2, 'confirmed', $3)
                RETURNING id_transacao
                """,
                id_conta,
                body.valor_cents,
                body.referencia or "DEP-API",
            )

            await tr.commit()
            return {
                "status": "ok",
                "id_conta": id_conta,
                "id_transacao": tid,
                "creditado_cents": body.valor_cents,
            }

        except HTTPException:
            await tr.rollback()
            raise
        except asyncpg.PostgresError as db_err:
            await tr.rollback()
            raise HTTPException(
                status_code=400,
                detail=f"Falha no depósito: {db_err}",
            )
        except Exception as e:
            await tr.rollback()
            raise HTTPException(
                status_code=400,
                detail=f"Falha no depósito: {e}",
            )

# ---------- PAGAMENTOS ----------
@app.post("/payments")
async def make_payment(
    body: Payment,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    user_id = _int_or_none(x_user_id)
    q = """
        INSERT INTO tb_transacao (id_conta_de, id_comerciante, tipo, valor_cents, status, referencia)
        VALUES ($1, $2, 'payment', $3, 'confirmed', $4)
        RETURNING id_transacao
    """
    pool = await get_pool()
    async with pool.acquire() as con:
        try:
            if user_id:
                c = await con.fetchrow(
                    "SELECT id_conta FROM tb_conta WHERE id_usuario=$1",
                    user_id,
                )
                if not c:
                    raise HTTPException(
                        status_code=400,
                        detail="Conta não localizada para o usuário",
                    )
                body.id_conta_de = c["id_conta"]
            tid = await con.fetchval(
                q,
                body.id_conta_de,
                body.id_comerciante,
                body.valor_cents,
                body.referencia or "API-PAY",
            )
            return {"id_transacao": tid}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

@app.post("/payments/utility")
async def make_utility_payment(
    body: UtilityPayment,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    user_id = _int_or_none(x_user_id)
    pool = await get_pool()
    
    if user_id is None:
        raise HTTPException(status_code=401, detail="Não autenticado")

    if body.id_comerciante not in ALLOWED_UTILITY_MERCHANT_IDS:
        raise HTTPException(status_code=400, detail="ID de comerciante de utilidade inválido.")
    
    async with pool.acquire() as con:
        try:
            conta_origem = await con.fetchrow(
                "SELECT id_conta FROM tb_conta WHERE id_usuario=$1",
                user_id,
            )
            if not conta_origem:
                raise HTTPException(status_code=400, detail="Conta de origem não localizada.")
            id_conta_de = conta_origem["id_conta"]

            ref_str = f"PAG-UTIL-{body.id_comerciante}"
            
            q = """
                INSERT INTO tb_transacao (id_conta_de, id_comerciante, tipo, valor_cents, status, referencia)
                VALUES ($1, $2, 'payment', $3, 'confirmed', $4)
                RETURNING id_transacao
            """
            tid = await con.fetchval(
                q,
                id_conta_de,
                body.id_comerciante,
                body.valor_cents,
                ref_str
            )
            return {"id_transacao": tid}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))


@app.post("/transfers")
async def make_transfer(
    body: Transfer,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    user_id = _int_or_none(x_user_id)
    pool = await get_pool()
    async with pool.acquire() as con:
        if not user_id:
            raise HTTPException(status_code=401, detail="Não autenticado")

        if body.valor_cents <= 0:
            raise HTTPException(status_code=400, detail="Valor de transferência inválido")

        try:
            conta_origem = await con.fetchrow(
                "SELECT id_conta FROM tb_conta WHERE id_usuario=$1",
                user_id,
            )
            if not conta_origem:
                raise HTTPException(status_code=400, detail="Conta de origem não localizada.")
            id_conta_de = conta_origem["id_conta"]

            conta_destino = await con.fetchrow(
                """
                SELECT c.id_conta, u.nome
                FROM tb_conta c JOIN tb_usuario u ON c.id_usuario = u.id_usuario
                WHERE u.doc_cpf_cnpj = $1 OR c.id_conta::text = $1
                """,
                body.identificador,
            )
            if not conta_destino:
                raise HTTPException(status_code=404, detail="Chave Pix (CPF, CNPJ ou ID) não encontrada.")
            
            id_conta_para = conta_destino["id_conta"]
            nome_destino = conta_destino["nome"]

            if id_conta_de == id_conta_para:
                raise HTTPException(status_code=400, detail="Não é possível transferir para a mesma conta.")

            tid = await con.fetchval(
                """
                INSERT INTO tb_transacao (id_conta_de, id_conta_para, tipo, valor_cents, status, referencia)
                VALUES ($1, $2, 'transfer', $3, 'confirmed', 'PIX-' || $4)
                RETURNING id_transacao
                """,
                id_conta_de,
                id_conta_para,
                body.valor_cents,
                body.identificador,
            )

            return {
                "id_transacao": tid,
                "nome_destino": nome_destino,
                "valor_cents": body.valor_cents,
            }

        except asyncpg.exceptions.RaiseError as db_err:
            raise HTTPException(status_code=400, detail=str(db_err))
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erro ao processar transferência: {e}")

# ---------- EMPRÉSTIMOS ----------
def monthly_rate_from_aa(aa_pct: float) -> float:
    return float((1 + aa_pct / 100.0) ** (1.0 / 12.0) - 1.0)

@app.post("/loans/simulate")
async def simulate_loan(
    body: LoanSim,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    user_id = _int_or_none(x_user_id)
    pool = await get_pool()
    async with pool.acquire() as con:
        if not user_id:
            raise HTTPException(status_code=401, detail="Não autenticado")
        
        if body.prazo_meses is None or body.prazo_meses <= 0:
            raise HTTPException(status_code=400, detail="Prazo inválido")

        # 1. Obter Salário Mensal para calcular LIMITE MÁXIMO
        c = await con.fetchrow(
            "SELECT salario_mensal_cents FROM tb_conta WHERE id_usuario=$1",
            user_id,
        )
        if not c:
            raise HTTPException(status_code=400, detail="Conta não localizada")
        
        salario = c["salario_mensal_cents"]
        parcela_max_limit = int(round(salario * 0.30))

        # 2. Definir Juros Dinâmico
        juros_aa_pct = get_dynamic_interest_aa(body.prazo_meses)
        jm = monthly_rate_from_aa(juros_aa_pct)

        # 3. Calcular Limite Máximo
        if jm == 0:
            principal_max = parcela_max_limit * body.prazo_meses
        else:
            principal_max = int(
                round(
                    parcela_max_limit
                    * (((1 + jm) ** body.prazo_meses - 1)
                       / (jm * (1 + jm) ** body.prazo_meses))
                )
            )

        # 4. Calcular Parcela para o valor SOLICITADO pelo usuário
        if body.principal_cents is None or body.principal_cents <= 0:
             pmt_cents = 0
        else:
             pmt_cents = calculate_pmt_cents(
                 body.principal_cents, juros_aa_pct, body.prazo_meses
             )
        
        return {
            "juros_aa_pct": juros_aa_pct,
            "parcela_max_limit_cents": parcela_max_limit,
            "principal_max_cents": principal_max,
            "pmt_cents": pmt_cents,
            "juros_mensal_pct": jm * 100.0,
            "validation_ok": body.principal_cents <= principal_max
        }

@app.post("/loans/create")
async def create_loan2(
    body: LoanRequest,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    user_id = _int_or_none(x_user_id)
    pool = await get_pool()
    async with pool.acquire() as con:
        if not user_id:
            raise HTTPException(status_code=401, detail="Não autenticado")
        c = await con.fetchrow(
            "SELECT id_conta, salario_mensal_cents FROM tb_conta WHERE id_usuario=$1",
            user_id,
        )
        if not c:
            raise HTTPException(status_code=400, detail="Conta não localizada")
        id_conta = c["id_conta"]
        exists = await con.fetchval(
            """
            SELECT 1 FROM tb_emprestimo e
            WHERE e.id_conta=$1 AND e.status IN ('approved','disbursed','in_arrears')
            LIMIT 1
            """,
            id_conta,
        )
        if exists:
            raise HTTPException(
                status_code=400,
                detail="Usuário já possui empréstimo ativo",
            )
        
        # 1. Determinar Juros e simular limite para validação
        juros_final = get_dynamic_interest_aa(body.prazo_meses)
        
        # Simula a validação de limite
        sim = await simulate_loan(
            LoanSim(principal_cents=body.principal_cents, prazo_meses=body.prazo_meses),
            x_user_id=user_id,
        )

        if body.principal_cents > sim["principal_max_cents"]:
            raise HTTPException(
                status_code=400,
                detail="Valor solicitado excede o limite permitido pela renda",
            )
        try:
            id_emp = await con.fetchval(
                """
                INSERT INTO tb_emprestimo (id_conta, principal_cents, juros_aa_pct, prazo_meses, status)
                VALUES ($1,$2,$3,$4,'approved')
                RETURNING id_emprestimo
                """,
                id_conta,
                body.principal_cents,
                juros_final,
                body.prazo_meses,
            )
            await con.execute("CALL sp_conceder_emprestimo($1)", id_emp)
            return {"id_emprestimo": id_emp}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

@app.get("/loans/current")
async def current_loan(
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    user_id = _int_or_none(x_user_id)
    pool = await get_pool()
    async with pool.acquire() as con:
        if not user_id:
            return {}
        row = await con.fetchrow(
            """
            SELECT e.*
            FROM tb_emprestimo e
            JOIN tb_conta c ON c.id_conta=e.id_conta
            WHERE c.id_usuario=$1
            AND e.status NOT IN ('paid', 'cancelled')
            ORDER BY e.criado_em DESC
            LIMIT 1
            """,
            user_id,
        )
        return dict(row) if row else {}

@app.get("/loans/{id_emprestimo}/installments")
async def list_installments(id_emprestimo: int):
    pool = await get_pool()
    async with pool.acquire() as con:
        rows = await con.fetch(
            """
            SELECT id_parcela, num_parcela, vencimento, valor_cents, pago
            FROM tb_parcela
            WHERE id_emprestimo=$1
            ORDER BY num_parcela
            """,
            id_emprestimo,
        )
        return [dict(r) for r in rows]

@app.post("/installments/pay")
async def pay_installment(
    body: PayInstallment,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    user_id = _int_or_none(x_user_id)
    pool = await get_pool()
    async with pool.acquire() as con:
        try:
            if user_id and (not body.id_conta or body.id_conta == 0):
                c = await con.fetchrow(
                    "SELECT id_conta FROM tb_conta WHERE id_usuario=$1",
                    user_id,
                )
                if not c:
                    raise HTTPException(status_code=400, detail="Conta não localizada")
                body.id_conta = c["id_conta"]
            await con.execute("CALL sp_pagar_parcela($1,$2)", body.id_parcela, body.id_conta)
            return {"status": "ok"}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

@app.post("/loans/pay_full")
async def pay_full_loan(
    body: PayFullLoan,
    x_user_id: Optional[int] = Header(default=None, alias="X-User-Id"),
):
    user_id = _int_or_none(x_user_id)
    pool = await get_pool()
    async with pool.acquire() as con:
        try:
            if not user_id:
                raise HTTPException(status_code=401, detail="Não autenticado")
                
            if not body.id_conta or body.id_conta == 0:
                c = await con.fetchrow(
                    "SELECT id_conta FROM tb_conta WHERE id_usuario=$1",
                    user_id,
                )
                if not c:
                    raise HTTPException(status_code=400, detail="Conta não localizada")
                body.id_conta = c["id_conta"]
            
            await con.execute("CALL sp_quitar_emprestimo($1,$2)", body.id_emprestimo, body.id_conta)
            return {"status": "ok", "id_emprestimo": body.id_emprestimo}
        except Exception as e:
            if "Empréstimo" in str(e) or "Saldo insuficiente" in str(e):
                raise HTTPException(status_code=400, detail=str(e))
            raise HTTPException(status_code=400, detail=str(e))

@app.get("/reports/faturamento-mensal")
async def report_faturamento():
    q = "SELECT * FROM vw_faturamento_mensal ORDER BY mes DESC, total_cents DESC"
    pool = await get_pool()
    async with pool.acquire() as con:
        rows = await con.fetch(q)
        return [dict(r) for r in rows]
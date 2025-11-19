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

app = FastAPI(
    title="POMENR API",
    version="1.4.0",
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
    juros_aa_pct: float
    prazo_meses: int
    @field_validator('prazo_meses', mode='before')
    @classmethod
    def _coerce_int(cls, v): return _int_or_none(v)

class Deposit(BaseModel):
    valor_cents: int
    id_conta: Optional[int] = None
    referencia: Optional[str] = "DEP-API"
    @field_validator('valor_cents', 'id_conta', mode='before')
    @classmethod
    def _coerce_int(cls, v): return _int_or_none(v)

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
        INSERT INTO tb_usuario (nome,email,telefone,doc_cpf_cnpj,senha_hash)
        VALUES ($1,$2,$3,$4,$5)
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
        INSERT INTO tb_usuario (nome,email,telefone,doc_cpf_cnpj,senha_hash)
        VALUES ($1,$2,$3,$4,$5)
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
        SELECT c.id_conta, c.numero_conta, c.agencia, c.saldo_cents
        FROM tb_conta c
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
            # descobre conta do usuário, se não vier no corpo
            id_conta = body.id_conta
            if not id_conta:
                row = await con.fetchrow(
                    "SELECT id_conta FROM tb_conta WHERE id_usuario=$1",
                    user_id,
                )
                if not row:
                    raise HTTPException(status_code=400, detail="Conta não localizada")
                id_conta = row["id_conta"]

            # Transação de crédito → usa id_conta_para
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

# ---------- EMPRÉSTIMOS ----------
def monthly_rate_from_aa(aa_pct: float) -> float:
    return float((1 + aa_pct / 100.0) ** (1.0 / 12.0) - 1.0)

class LoanSim(BaseModel):
    juros_aa_pct: float
    prazo_meses: int
    @field_validator('prazo_meses', mode='before')
    @classmethod
    def _coerce_int2(cls, v): return _int_or_none(v)

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
        c = await con.fetchrow(
            "SELECT id_conta, salario_mensal_cents FROM tb_conta WHERE id_usuario=$1",
            user_id,
        )
        if not c:
            raise HTTPException(status_code=400, detail="Conta não localizada")
        salario = c["salario_mensal_cents"]
        parcela_max = int(round(salario * 0.30))
        if body.prazo_meses is None or body.prazo_meses <= 0:
            raise HTTPException(status_code=400, detail="Prazo inválido")
        jm = monthly_rate_from_aa(body.juros_aa_pct)
        if jm == 0:
            principal_max = parcela_max * body.prazo_meses
        else:
            principal_max = int(
                round(
                    parcela_max
                    * (((1 + jm) ** body.prazo_meses - 1)
                       / (jm * (1 + jm) ** body.prazo_meses))
                )
            )
        return {
            "parcela_max_cents": parcela_max,
            "principal_max_cents": principal_max,
            "juros_mensal_pct": jm * 100.0,
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
        sim = await simulate_loan(
            LoanSim(juros_aa_pct=body.juros_aa_pct, prazo_meses=body.prazo_meses),
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
                body.juros_aa_pct,
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

# ---------- RELATÓRIO ----------
@app.get("/reports/faturamento-mensal")
async def report_faturamento():
    q = "SELECT * FROM vw_faturamento_mensal ORDER BY mes DESC, total_cents DESC"
    pool = await get_pool()
    async with pool.acquire() as con:
        rows = await con.fetch(q)
        return [dict(r) for r in rows]

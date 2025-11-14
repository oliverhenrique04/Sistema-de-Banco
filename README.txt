
# FinPay Microcrédito & Pagamentos (PostgreSQL + FastAPI + Nginx)

## Como rodar
1) Extraia o pacote e entre na pasta `finpay_microcredit_demo`.
2) `docker compose up --build`
3) App: http://localhost:8080
4) API docs (Swagger): http://localhost:8000/docs

## Scripts SQL
- `sql/schema.sql`: criação da base, tabelas, índices e triggers
- `sql/data_and_queries.sql`: população (>=10 por tabela principal), views, procedures/functions, consultas

## Notas
- Triggers: auditoria, validação de saldo, atualização de status do empréstimo
- Segurança: papéis `finpay_admin`, `finpay_operador`, `finpay_auditor`
- Testes no psql: `docker exec -it $(docker ps -qf name=db) psql -U postgres -d finpay`

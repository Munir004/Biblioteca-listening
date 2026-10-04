# Biblioteca-listening
# Biblioteca — Listener de e-mail (Python + RabbitMQ)

Aplicação **consumidora**: escuta a fila de empréstimos do RabbitMQ e envia um e-mail de confirmação
para o cliente. A aplicação **publicadora** é o projeto Spring Boot `LauraBuzzato/Biblioteca`.

```
Spring Boot (Java)                     RabbitMQ                          Listener (Python)
POST /emprestimos/...  ──publica──▶  exchange_biblioteca (direct)
                                          │ chave: key_emprestimo
                                          ▼
                                     queue_emprestimos  ──entrega──▶  valida → monta e-mail → SMTP
                                                                      ack (ok) / reject / nack
```

## O que o publicador (Spring) envia — o contrato

| Item | Valor |
|---|---|
| Broker | `localhost:5672`, usuário `admin`, senha `admin` (`compose.yml` dela) |
| Exchange | `exchange_biblioteca` — tipo **direct**, durável |
| Fila | `queue_emprestimos` — durável, sem argumentos extras |
| Routing key | `key_emprestimo` |
| Corpo | JSON: `emprestimoId`, `nomeLivro`, `nomeCliente`, `emailCliente`, `dataEmprestimo` |

O listener declara exchange, fila e binding **exatamente** assim (declarar é idempotente), então funciona
tanto se ele subir antes quanto depois da aplicação Spring. Se um dia alguém mudar o tipo da exchange ou
colocar argumentos na fila de um lado só, o RabbitMQ responde `406 PRECONDITION_FAILED` e o listener
explica o problema no terminal.

## Como rodar

Pré-requisitos: Python 3.9+ e Docker (ou o RabbitMQ já rodando).

```bash
# 1) RabbitMQ (use o compose.yml da aplicação Spring OU este — só um deles)
docker compose up -d                # painel: http://localhost:15672  (admin / admin)

# 2) Dependências
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3) Configuração
cp .env.example .env                # Windows: copy .env.example .env   → edite o .env

# 4) Iniciar
python main.py
```

### Configurando o e-mail

- **Gmail**: ative a verificação em duas etapas na conta e crie uma **senha de app** (procure por
  “Senhas de app” na sua conta Google; o caminho no site pode mudar). Use essa senha em `SMTP_PASSWORD`;
  a senha normal da conta não funciona. Valores: `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`,
  `SMTP_SEGURANCA=starttls`.
- **Sem enviar de verdade**: `EMAIL_DRY_RUN=true` mostra o e-mail no terminal. Bom para testar o fluxo.
- **Caixa de e-mail de teste local** (opcional): `docker run -d -p 8025:8025 -p 1025:1025 axllent/mailpit`,
  depois `SMTP_HOST=localhost`, `SMTP_PORT=1025`, `SMTP_SEGURANCA=nenhuma` (sem usuário/senha) e abra
  http://localhost:8025 para ver os e-mails.

## Como testar

**Só o listener** (sem a aplicação Spring): com o listener rodando, em outro terminal:

```bash
python publicar_teste.py --email seu-email@gmail.com
python publicar_teste.py --email seu-email@gmail.com --quantidade 3
python publicar_teste.py --invalida          # corpo que não é JSON → o listener descarta
python publicar_teste.py --data-como-array   # data no formato [ano, mes, dia]
```

**Junto com a aplicação Spring** (`mvn spring-boot:run` na pasta dela; porta 8080; banco H2 em memória,
então os ids recomeçam do 1 a cada execução):

```bash
curl -X POST http://localhost:8080/clientes -H "Content-Type: application/json" \
     -d '{"nome":"Maria Silva","email":"seu-email@gmail.com"}'
curl -X POST http://localhost:8080/livros -H "Content-Type: application/json" \
     -d '{"nome":"Dom Casmurro","autor":"Machado de Assis","qtdPaginas":256}'
curl -X POST http://localhost:8080/emprestimos/livro/1/cliente/1
```

Cada livro só pode ser emprestado uma vez por execução (não existe endpoint de devolução); para repetir,
cadastre outro livro.

**Para quem só tem o publicador (sem o listener):** abra http://localhost:15672 → *Queues* →
`queue_emprestimos` → *Get messages* (deixe “Ack mode: Nack message requeue true” para só espiar). Se a
mensagem aparece lá, o publicador está funcionando. Com o listener rodando ela é consumida na hora.

**Testes automatizados** (63 testes, não precisam de RabbitMQ nem de internet):

```bash
pip install -r requirements-dev.txt
pytest
```

## O que acontece em cada situação

| Situação | O que o listener faz |
|---|---|
| E-mail enviado | `ack` — a mensagem sai da fila |
| JSON quebrado, campo obrigatório faltando, e-mail inválido | `reject` sem reenfileirar — descarta e registra no log |
| Servidor recusa o destinatário (erro 5xx) | `reject` — repetir não adianta |
| SMTP fora do ar, timeout, erro temporário (4xx) | `nack` com reenfileirar + espera `RETRY_DELAY_SEGUNDOS`; tenta de novo até dar certo |
| Senha/remetente/porta do SMTP errados | **para** o listener com mensagem clara; a mensagem continua na fila |
| RabbitMQ fora do ar | tenta reconectar a cada 5 s; ao voltar, redeclara tudo e segue |
| `Ctrl+C` ou `SIGTERM` | encerra limpo; mensagem em andamento volta para a fila |

Processa **uma mensagem por vez** (`prefetch=1`), com confirmação manual (`ack`).

## Limitações conhecidas

- Entrega “pelo menos uma vez”: se o listener cair depois de enviar o e-mail e antes do `ack`, a mensagem
  é reentregue e o cliente pode receber o e-mail duas vezes.
- Mensagens descartadas só ficam no log: a fila da aplicação Spring não tem *dead-letter queue*, e
  adicionar argumentos só deste lado faria o RabbitMQ recusar a declaração (erro 406).
- O formato da data aceita `"2026-10-02"` e `[2026, 10, 2]`. Sem data (ou num formato desconhecido) o
  e-mail sai sem a data. Para ver o JSON exato que a aplicação Spring envia, use `LOG_LEVEL=DEBUG`.

## Estrutura

```
main.py            ponto de entrada (config, logs, encerramento)
consumer.py        conexão, declaração da fila, consumo e decisão ack/nack/reject
email_service.py   monta o e-mail (texto + HTML) e envia por SMTP; classifica os erros
mensagem.py        lê e valida o JSON recebido
config.py          nomes do contrato + leitura do .env
publicar_teste.py  simula o publicador para testar sozinho
tests/             testes unitários (pytest)
```

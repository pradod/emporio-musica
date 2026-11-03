# Empório da Música — agente de atendimento

Protótipo do **Toni**, assistente virtual da Empório da Música (loja fictícia de instrumentos musicais em Campo Grande/MS). O agente conversa por texto, consulta o catálogo e os pedidos, aplica o manual de políticas da loja e recusa o que estiver fora do escopo.

- **Abordagem:** agente com *function calling* e 6 ferramentas tipadas. Não usa agente de SQL livre nem RAG vetorial.
- **LLM:** qualquer endpoint compatível com a API da OpenAI. O padrão é **Ollama local** com `qwen3:14b`.
- **Interface:** CLI com histórico persistido por sessão.
- **Regras de negócio** (preço promocional, PIX, parcelamento, prazos de troca e garantia) são calculadas em Python, não pelo LLM.

---

## 1. Como rodar

### Pré-requisitos
- Python 3.11 ou superior
- Um endpoint compatível com OpenAI que suporte *tools*. Pode ser o [Ollama](https://ollama.com) local (padrão) ou OpenAI, Groq, OpenRouter, LM Studio, vLLM etc.

### Instalação
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### Configurar o modelo (`.env`)

**Opção A — Ollama local (padrão):**
```bash
ollama pull qwen3:14b
```
```env
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=qwen3:14b
```

**Opção B — qualquer API compatível com OpenAI:** basta trocar três variáveis, sem mudar código.
```env
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4.1-mini
```

Outras variáveis opcionais:

| Variável | Para quê |
|---|---|
| `LLM_TEMPERATURE` | Padrão `0.2`. Baixa, porque o agente precisa ser fiel aos dados. |
| `LLM_EXTRA_BODY` | JSON repassado ao provedor como `extra_body` (parâmetros específicos de cada servidor). |
| `EMPORIO_DATA_REFERENCIA` | Congela o "hoje" do agente (ex.: `2026-03-25T10:30`). Vazio = relógio real. Ver [Suposições](#5-suposições). |

### Conversar com o agente
```bash
python -m emporio
```
- `--sessao maria`: retoma ou cria a sessão `maria`. O histórico fica em `.historico/`.
- `--sem-rastreio`: esconde as chamadas de ferramenta. Por padrão elas aparecem em cinza, o que mostra quando o agente consulta dados e quando consulta políticas.
- Comandos dentro do chat: `/nova` apaga o histórico, `/rastreio` liga ou desliga o rastreio, `/sair` encerra.

Exemplo de rastreio:
```
Você: Quanto custa o Takamine GD20?
  ↳ detalhes_produto({"produto": "Takamine GD20"}) → {"id": 95, "nome": "Takamine GD20 Dreadnought Natural", "preco": "R$ 2.199,00", ...
Toni: ...
```

### Testes (não precisam de LLM)
```bash
python -m pytest -q
```

### Regerar as conversas de exemplo
```bash
python scripts/gerar_exemplos.py          # todos os cenários
python scripts/gerar_exemplos.py 4        # só o cenário 4
```

---

## 2. Arquitetura

```
Cliente (CLI) ──► Agente (loop de tool calling) ──► LLM (API compatível com OpenAI)
                     │   ▲
                     ▼   │ JSON
                 Ferramentas ─────────────┬─────────────────────────────┐
                     │                    │                             │
             dados.py (pandas)    politicas.py (markdown)    encaminhamentos.jsonl
             CSVs limpos +        knowledge/politicas/*.md   (handoff para a equipe)
             regras de negócio
```

| Arquivo | Responsabilidade |
|---|---|
| `emporio/dados.py` | Carga e limpeza dos CSVs. Regras de negócio: disponibilidade, promoção ativa, PIX, parcelamento, prazos de pós-venda, horário da loja. |
| `emporio/politicas.py` + `knowledge/politicas/` | Manual de políticas curado em markdown, um arquivo por tópico. |
| `emporio/ferramentas.py` | As 6 ferramentas expostas ao LLM, com schema, descrição e formatação em R$. |
| `emporio/prompt.py` | Persona, regras de uso das ferramentas, escopo e contexto do momento (data, hora, loja aberta ou fechada). |
| `emporio/agente.py` | Loop de *tool calling*, recorte do histórico e verificador de valores. |
| `emporio/cli.py`, `emporio/historico.py` | Interface e persistência das sessões. |

### Ferramentas

| Ferramenta | Tipo | Quando o modelo usa |
|---|---|---|
| `buscar_produtos` | dados | "violões até R$1000", "tem ukulele tenor?" (filtros de categoria, preço, corda, captação) |
| `detalhes_produto` | dados | "quanto custa o Takamine GD20?" (preço, promoção, PIX, parcelas, estoque, alternativas) |
| `consultar_pedido` | dados | status, rastreio e prazos de troca, devolução e garantia. **Exige nº do pedido + telefone ou e-mail.** |
| `listar_pedidos_do_cliente` | dados | o cliente não sabe o número do pedido |
| `consultar_politica` | políticas | endereço, horário, pagamento, frete, trocas, garantia, promoções, LGPD |
| `encaminhar_para_equipe` | ação | reclamação, troca elegível, defeito, atraso, "quero falar com um atendente". Gera protocolo. |

---

## 3. Decisões técnicas

### Function calling com ferramentas tipadas (e não agente de SQL nem RAG sobre os CSVs)
- **Os números não passam pelo LLM.** Preço promocional, regra "PIX não acumula com promoção", parcela mínima por faixa e prazos de 7, 30 e 90 dias saem prontos das ferramentas. O manual diz que informação errada de preço "pode configurar propaganda enganosa", e modelos pequenos erram contas com frequência.
- **Privacidade.** Um agente de SQL livre poderia fazer `SELECT * FROM customers`. Com ferramentas fechadas, o único caminho até um pedido exige número **e** contato, e os dados de outros clientes nunca chegam ao modelo (LGPD, seção 9 do manual).
- **Funciona com modelos locais menores.** Escolher entre 6 ferramentas bem descritas é bem mais fácil para um modelo de 8–14B do que escrever SQL correto sobre 6 tabelas.
- **Fica auditável.** O rastreio mostra exatamente *quando* o agente consultou dados e *quando* consultou políticas, que é um dos pontos pedidos no desafio.

### Políticas: markdown curado por tópico (e não RAG com embeddings)
O manual tem 8 páginas e cerca de 3 mil tokens, com seções bem delimitadas. Embeddings e um banco vetorial trariam custo e ruído de recuperação (trechos partidos no meio de uma tabela, por exemplo) sem ganho real. Em vez disso:
- converti o PDF em 7 arquivos markdown, um por tópico, **resolvendo à mão as contradições do original** (ver seção 4);
- o modelo escolhe o tópico por um `enum` na ferramenta `consultar_politica`. A seleção é explícita, determinística e aparece no log.

Com um manual de centenas de páginas, eu trocaria isso por busca híbrida (BM25 + embeddings) mantendo a mesma interface de ferramenta.

### LLM e provedor
- **Cliente `openai` com `base_url` configurável.** Assim, quem avaliar o case pode rodar com Ollama local ou com qualquer provedor compatível (OpenAI, Groq, OpenRouter, LM Studio, vLLM) trocando só o `.env`.
- **Padrão: Ollama + `qwen3:14b`.** É gratuito, roda offline, fala bem português e tem bom suporte a *tool calling*. Cabe com folga numa máquina de 16–24 GB. `qwen3:8b` é a alternativa mais leve.
- Tags `<think>…</think>` que alguns modelos de raciocínio deixam no texto são removidas antes de mostrar a resposta.

### Estratégia de prompt
- **Persona "Toni":** o tom vem da seção 7.1 do manual ("informal mas profissional, como um amigo que entende de música"), no estilo de mensagens curtas de WhatsApp.
- **Regras de ouro numeradas** e não negociáveis: nunca citar preço, estoque ou prazo sem ferramenta; consultar a política antes de responder sobre regras; apresentar promoção com preço original, percentual e preço final; validar identidade antes de falar de pedidos.
- **Contexto dinâmico** injetado a cada turno: dia da semana, data, hora e se a loja está aberta (com a próxima abertura). Isso atende à regra "fora do expediente, informar o horário de retorno".
- **Instruções no próprio retorno das ferramentas.** Campos como `alerta_interno` ("entrega atrasada em 25 dias, ofereça encaminhar") e `aviso_interno` ("descrição inconsistente, use só as specs") levam a orientação para o momento exato em que ela importa. Isso funciona melhor com modelos pequenos do que concentrar tudo no prompt de sistema.

### Verificador de valores (guarda-corpo)
Depois que o modelo responde, `agente.py` extrai todo valor `R$ x,yy` do texto e confere se ele aparece em algum resultado de ferramenta da conversa. Se algum valor não tiver origem, o agente pede **uma** revisão ao modelo antes de mostrar a resposta ao cliente, e o rascunho descartado sai do histórico. É uma checagem barata e determinística contra o tipo de alucinação mais caro numa loja: preço inventado.

### Histórico de conversa
Cada sessão vira um JSON em `.historico/`, com mensagens de usuário, assistente e ferramentas. Uma conversa de atendimento costuma ser retomada ("e aquele violão que você falou?"), então manter o contexto melhora a experiência. Só as últimas 40 mensagens vão ao modelo, sempre cortando num turno do usuário para não deixar uma resposta de ferramenta órfã.

---

## 4. Tratamento dos dados

A análise exploratória encontrou várias inconsistências. Cada uma foi tratada no código ou documentada:

| Problema encontrado | Decisão |
|---|---|
| Produtos 135, 137, 139, 140, 142 e 144 têm **descrição de outro instrumento** (ex.: "Music Man Bass 1X" descrito como "Fender Jazz Bass"; "Korg Synth 61 teclas" descrito como Roland de 88 teclas; descrição "5 cordas" com specs de 4). | Detecção automática (marca citada na descrição ≠ marca do nome, ou nº de cordas divergente). O agente não usa a descrição desses itens, só nome, preço e specs. |
| `discontinued` com estoque 13 (id 136); `coming_soon` com estoque 2 (id 130); `active` com estoque 0 (id 96). | Só é **vendável** o que estiver `active` **e** com estoque > 0. Fora de linha e "em breve" não são oferecidos, e o agente sugere alternativas da mesma categoria com preço próximo. |
| Categorias 6, 7 e 8 (sopros e cordas orquestrais) sem nenhum produto, embora o manual fale em "mais de 300 instrumentos". | O agente responde com o que existe no sistema e nunca inventa produtos. |
| Promoções sem data de validade; produtos com 2 promoções (todas inativas). | Vale só `is_active = 1`. Se houvesse duas ativas, valeria a maior, já que promoções não acumulam. As encerradas são mostradas ao modelo para responder "ainda está na promoção X?" com transparência (seção 7.3 do manual). |
| `total_brl` diferente da soma dos itens (pedidos 3 e 20); pedido no PIX sem os 5% de desconto. | O agente informa sempre o **total registrado** e não recalcula. `order_items` não guarda o preço unitário da época. |
| E-mail `bruno.martins@jmail.com` usado por dois clientes (ids 11 e 43). | Busca de pedidos por contato ambíguo é bloqueada; o agente pede o nº do pedido ou o telefone. |
| Specs em JSON com chaves em inglês. | Convertidas para português (`top` → tampo, `steel` → aço…). |

### Contradições no PDF de políticas (resolvidas na versão curada)
| Contradição | Versão adotada |
|---|---|
| WhatsApp **(67) 3341-4444** (capa e seção 1.2) × **(67) 3321-4500** (seção 7) | 3341-4444, que aparece duas vezes, inclusive na tabela oficial de dados da empresa. |
| E-mail `contato@empóriodamusica.com.br` (com acento, na 1.2) × sem acento (capa) | Sem acento: domínios com acento são improváveis e a capa traz essa grafia. |
| Crédito: "parcela mínima R$ 100" (tabela) × faixas 3x / 4–6x R$ 80 / 7–12x R$ 100 (seção 3.1) | As faixas da 3.1, que são mais específicas. |
| "Até 3x sem valor mínimo (exceto abaixo de R$ 50)" | Interpretado como parcela mínima de R$ 50 para 2x–3x. |

---

## 5. Suposições

- **Data de referência.** Os dados são um retrato que termina em 22/03/2026. Rodando com o relógio real, todos os pedidos estariam fora de qualquer prazo e os "pendentes" estariam parados há meses. Por isso `EMPORIO_DATA_REFERENCIA` permite congelar o "hoje", e os exemplos usam **25/03/2026 10:30**.
- **Data de recebimento = `estimated_delivery`.** Não há data real de entrega. Ela é a base para arrependimento (7 dias), troca por preferência (7 dias) e garantia legal (90 dias). A troca por defeito na loja conta a partir da data da compra (30 dias), como diz o manual.
- **Troca por preferência** conta a partir do recebimento (o manual só diz "em até 7 dias").
- **Feriados** não constam nos dados; o horário considera só o dia da semana.
- **Pedido pendente há mais de 3 dias** gera alerta, porque o boleto compensa em até 3 dias úteis.
- **Encaminhamentos** usam o prazo de retorno de 24 horas úteis que o manual define para reclamações, e são gravados em `.historico/encaminhamentos.jsonl`, simulando a fila da equipe.
- **Acessórios:** o manual manda sugerir "lojas parceiras quando possível", mas nenhuma é nomeada. O agente sugere procurar uma loja especializada, sem inventar nomes.

---

## 6. Exemplos de interação

Gerados com `scripts/gerar_exemplos.py`. Cada arquivo mostra as ferramentas chamadas em cada turno (seção expansível).

| # | Cenário | O que demonstra |
|---|---|---|
| 1 | [Violões até R$ 1000](exemplos/01_catalogo_violoes.md) | busca com filtros + recomendação para iniciante |
| 2 | [Takamine GD20: preço, PIX, parcelas e promoção encerrada](exemplos/02_preco_pagamento_promocao.md) | dados + política de pagamento + transparência sobre promoção vencida |
| 3 | [Endereço, horário, acessórios e fora do escopo](exemplos/03_loja_e_fora_de_escopo.md) | consulta de política, redirecionamento de acessórios e recusa educada |
| 4 | [Arrependimento e garantia](exemplos/04_devolucao_e_garantia.md) | **não trivial:** validação do pedido, prazo de 7 dias expirado, defeito coberto pela garantia legal, encaminhamento com protocolo |
| 5 | [Pedido atrasado](exemplos/05_pedido_atrasado.md) | **não trivial:** identidade validada, atraso detectado, desculpas e encaminhamento |

---

## 7. Limitações conhecidas e próximos passos

- **Avaliação automatizada do agente.** Os testes cobrem as regras de negócio e o loop do agente com um LLM falso, mas não a qualidade das respostas do modelo real. Próximo passo: um conjunto de cerca de 50 perguntas com respostas esperadas (ferramenta correta, valores corretos, recusa correta), avaliado por asserções e por *LLM-as-judge*, comparando modelos e versões do prompt.
- **Busca de produtos por palavra-chave.** Ela é tolerante a acento e plural, mas não entende sinônimos ("violão de show" → eletroacústico) nem erros de digitação. Com mais tempo: busca híbrida com embeddings sobre nome, descrição e specs.
- **Frete:** o agente não calcula frete para fora de Campo Grande (dependeria de API dos Correios/Jadlog) e encaminha para cotação.
- **Identificação do cliente:** num WhatsApp real, o telefone viria do próprio canal e dispensaria a pergunta.
- **Encaminhamento** grava num arquivo local. Em produção, iria para um CRM ou helpdesk, com notificação à equipe.
- **Dados estáticos:** os CSVs são carregados uma vez por processo. Em produção, as ferramentas consultariam o ERP ou o banco em tempo real, mantendo a mesma interface.
- **Interface:** é só CLI. A mesma classe `Agente` poderia ser exposta numa API (FastAPI) e plugada num webhook de WhatsApp.
- **Observabilidade:** registrar latência, tokens e ferramentas por turno (ex.: Langfuse) para acompanhar erros e custo.

---

## 8. Uso de assistentes de código

Usei o **Claude Code** (Claude Opus) como par de programação neste projeto:

1. **Entendimento do desafio:** pedi a leitura do enunciado e do manual de políticas, e uma análise exploratória dos CSVs com pandas. Foi nessa etapa que apareceram as inconsistências listadas na seção 4 (descrições trocadas, status × estoque, totais divergentes, e-mail duplicado, contradições do PDF).
2. **Arquitetura:** discuti as opções (RAG, agente de SQL, function calling) e decidi por ferramentas tipadas com cálculos determinísticos. As escolhas de provedor foram minhas: Ollama local e a exigência de que o projeto funcionasse com qualquer API compatível com OpenAI, para facilitar a avaliação.
3. **Implementação:** o assistente escreveu a primeira versão de cada módulo e dos testes. Eu revisei, rodei e ajustei.
4. **Validação:** testes automatizados das regras de negócio e execução real dos cenários de exemplo com o modelo local.

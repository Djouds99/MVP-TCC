# MVP de recomendação KST

Protótipo de recomendação de conteúdo de Matemática baseado na Teoria dos
Espaços de Conhecimento (KST), para o TCC2 de Gabriel Eleutério Caldeira
(Sistemas de Informação, UDESC/CESMO).

A lógica de recomendação é **determinística**: fronteira externa do estado de
conhecimento estimado, com desempate pela interseção com o caminho de
pré-requisitos até o objetivo declarado (STEINER; NUSSBAUMER; ALBERT, 2009).
Não há aprendizado de máquina em nenhuma parte do sistema.

Referência arquitetural: [`ishwar6/KST-Learning-Path`](https://github.com/ishwar6/KST-Learning-Path).
Nenhum arquivo foi copiado — o padrão de modelagem foi estudado e reimplementado
em Python 3 (ver `domain/models.py` para a correspondência de nomenclatura).

## Estado atual: Partes 1 a 5 concluídas

O que existe:

- Projeto Django rodando, com esquema de dados criado e migrações aplicadas.
- Domínio de conhecimento como dado versionado, com os 5 tópicos da cadeia e as
  relações de pré-requisito.
- Modelagem de item de conhecimento e de estado de conhecimento, com o espaço de
  conhecimento gerado e materializado no banco.
- Identificação do aluno por código curto, sem nome nem e-mail, com grupo
  piloto/controle.
- Rota trivial respondendo, e o caminho de deploy preparado e testado localmente
  em modo de produção.
- **Motor de recomendação**: fronteira externa e desempate por objetivo, como
  lógica pura, sem banco e sem interface (ver abaixo).
- **Motor de teste adaptativo**: converge para o estado de conhecimento do aluno
  em 5 a 6 perguntas, e alimenta o motor de recomendação diretamente.
- Banco de questões de múltipla escolha, uma por item, funcional mas provisório.
- **Interface do aluno**: identificação por código, escolha de objetivo, teste
  adaptativo e recomendação — o caminho crítico completo, sem intervenção manual
  no banco.
- **Instrumento de pesquisa**: pré-teste e pós-teste aplicados às duas turmas,
  com exportação de turma, pré, pós e ganho por aluno.

O que **não** existe ainda (partes seguintes do roadmap): conteúdo em redação
final.

## O motor de recomendação

Em [`domain/recommendation.py`](domain/recommendation.py). A regra tem duas
etapas:

1. **Fronteira externa** — dado o estado de conhecimento estimado, os candidatos
   brutos são os itens ainda não dominados cujos pré-requisitos já estão todos
   dominados.
2. **Desempate por objetivo** — a escolha é a interseção entre a fronteira e o
   caminho de pré-requisitos até o objetivo declarado pelo aluno
   (STEINER; NUSSBAUMER; ALBERT, 2009).

O que a regra faz, no domínio ilustrativo (`FA1` = lei de formação, que
bloqueia exponencial; `FA2` = taxa de variação, que não bloqueia):

```
PC ─→ FA1 ─┬─→ FA2 ─→ PR
           └─→ FE ──→ LOG
```

| estado atual | objetivo | fronteira bruta | recomendação |
| --- | --- | --- | --- |
| `{}` | `LOG` | `{PC}` | `PC` |
| `{PC, FA1}` | `LOG` | `{FA2, FE}` | `FE` |
| `{PC, FA1}` | `PR` | `{FA2, FE}` | `FA2` |
| `{PC, FA1, FE}` | `LOG` | `{FA2, LOG}` | `LOG` |
| domínio completo | `LOG` | `{}` | nenhuma — `DOMAIN_COMPLETE` |

As duas linhas do meio são o ponto: mesmo estado, mesma fronteira bruta,
recomendação diferente só porque o objetivo mudou.

Os quatro casos vêm da tabela do roadmap e foram **recalculados à mão** contra a
estrutura de 10/09/2026. O terceiro mudou de resposta: com acesso parcial,
chegar a `PR` exige antes `FA2`, que a regra antiga já dava como dominado junto
com o tópico inteiro.

Não há ordenação por dificuldade nem pontuação de nenhum tipo. A decisão é
determinística e vem inteiramente da estrutura de pré-requisitos.

### Casos de borda, decididos e documentados

`recommend_next_item` devolve um `Recommendation` com `item`, `candidates`,
`fringe`, `reason` e `goal`. O campo `item` **só vem preenchido quando a regra
determina uma resposta única** — nunca uma escolha arbitrária disfarçada de
decisão do motor.

| situação | `item` | `reason` |
| --- | --- | --- |
| fronteira vazia (domínio completo) | `None` | `DOMAIN_COMPLETE` |
| objetivo já dominado | `None` | `GOAL_ALREADY_REACHED` |
| sem objetivo declarado | `None` se houver mais de um candidato | `NO_GOAL_DECLARED` |
| desempate aplicado | o item | `GOAL_DIRECTED` |

Fronteira vazia **não** é erro: "o aluno terminou" é uma resposta legítima, e
quem chama precisa distinguir isso de "não sei". Objetivo já dominado também não
recua para a fronteira inteira — isso seria recomendar por uma regra diferente da
declarada sem dizer; o certo é a interface pedir um objetivo novo.

Estado inválido (item sem pré-requisito) e objetivo fora do domínio levantam
`ValueError`: são erros de quem chama, não situações a contornar em silêncio.

## O teste de posicionamento adaptativo

Em [`assessment/engine.py`](assessment/engine.py), também lógica pura.

O motor mantém o conjunto de estados de conhecimento ainda compatíveis com as
respostas. Começa com todos os 46 e, a cada resposta, descarta os incompatíveis:
acertou o item `q` → ficam só os estados que contêm `q`; errou → ficam só os que
não contêm. A próxima pergunta é sobre o item que divide mais ao meio o conjunto
restante. Termina quando sobra um único estado, que é a estimativa.

Como os estados são fechados para baixo, uma resposta carrega muito mais
informação que o item perguntado: acertar uma questão de progressões confirma de
uma vez plano cartesiano e função afim inteiros.

| | |
| --- | --- |
| itens no domínio (sondagem exaustiva) | 15 |
| perguntas do teste adaptativo | 5 a 6, média 5,6 |
| pior caso vs. limite teórico (⌈log₂ 46⌉) | 6 vs. 6 |
| estados recuperados corretamente | 46 de 46 |

### Por que não é uma busca binária ao longo da cadeia

O roadmap previa busca binária. Ela pressupõe que o domínio está totalmente
ordenado e que o conhecimento do aluno é um **prefixo** dessa ordem — e a cadeia
deste MVP não é uma fila: função exponencial e progressões correm em paralelo, e
desde a revisão de 10/09/2026 a exponencial fica acessível com função afim
apenas parcialmente dominada.

**30 dos 46 estados não são prefixo de ordem linear nenhuma.** Na prática, uma
busca binária linear classificaria errado o aluno que avançou num ramo e não no
outro: quem domina progressões mas não exponencial sairia como não tendo nenhum
dos dois.

O que está implementado é a mesma ideia — dividir ao meio o que ainda está em
aberto — aplicada ao conjunto de estados em vez de a uma fila de itens. Sobre uma
cadeia realmente linear os dois procedimentos coincidem, e há teste verificando
isso (cadeia de 7 itens, 3 perguntas, exatamente como a busca binária).

### ⚠️ Suposição determinística, e o que ela custa

O procedimento lê acerto como domínio e erro como ausência de domínio. Não há
modelo de chute nem de erro por distração — isso seria Teoria de Resposta ao
Item, fora do escopo acordado.

A consequência precisa estar no texto do TCC2: **numa questão de quatro
alternativas, um chute certeiro faz o motor concluir domínio que não existe**, e
o estado estimado sai deslocado para cima. O motor não detecta isso — como só
pergunta sobre itens ainda em aberto, qualquer sequência de respostas é
internamente consistente e sempre converge.

Mitigar exigiria mais de uma questão por item, o que alonga o teste. É decisão
pedagógica, não técnica, e por isso não foi tomada no código.

### Da resposta ao estado gravado

[`assessment/services.py`](assessment/services.py) é a ponte com o banco:
`start_session` → `next_question` → `record_response` → `finalize` →
`recommendation_for`. As views chamam essas funções, nunca o motor diretamente.

Duas propriedades que valem notar:

- **Nada de estado de teste guardado no servidor entre requisições.** O motor é
  reconstruído a cada chamada a partir das respostas gravadas — refazer o caminho
  dá sempre o mesmo resultado.
- **A relação de pré-requisito é lida do banco, não do arquivo.** As questões
  servidas ao aluno vêm do banco; usar as duas fontes abriria espaço para o motor
  raciocinar sobre um item que a tela não consegue perguntar, se alguém esquecer
  de rodar `load_curriculum`.

Cada sessão registra em qual `CurriculumRelease` rodou, então é possível afirmar
no TCC2 sobre qual versão de conteúdo e de banco de questões cada medida foi
feita.

## A interface do aluno

Quatro telas, em [`assessment/views.py`](assessment/views.py):

| rota | tela | quem alcança |
| --- | --- | --- |
| `/` | identificação pelo código | as duas turmas |
| `/continuar/` | despachante: decide para onde mandar | as duas turmas |
| `/prova/` | pré ou pós-teste, conforme a etapa | **as duas turmas** |
| `/objetivo/` | escolha do tópico-alvo | só piloto |
| `/teste/` | teste adaptativo | só piloto |
| `/recomendacao/` | próximo passo, com o motivo | só piloto |
| `/sair/` | encerra a visita (aparelho compartilhado em sala) | as duas turmas |

`/continuar/` é o único ponto onde a regra "para onde este aluno vai agora" mora.
Concentrá-la numa view só evita que cada tela reimplemente a regra com uma
variação sutil.

A página de verificação de ambiente saiu de `/` e agora vive em `/status/`.

### Decisões que valem registrar

**Sem JavaScript no caminho crítico.** Tudo é server-rendered com formulários
comuns. Em escola pública o aparelho e a rede são imprevisíveis, e o piloto roda
numa janela única sem segunda chance — um fluxo que depende de script carregando
é risco desnecessário.

**O grupo controle nunca alcança o motor de recomendação.** Desde a Parte 5 o
bloqueio deixou de ser na identificação e passou a valer só nas três telas do
app — a turma controle precisa entrar para fazer o pré/pós-teste. Se ela usar o
app, a comparação de ganho perde o sentido; se ficar de fora do instrumento, a
comparação deixa de existir.

⚠️ Isso tem um pré-requisito **fora do código**: o professor precisa avisar a
turma de controle antes do dia da aplicação. Se a primeira notícia for a tela de
recusa, vira confusão na hora em que a cooperação mais importa. Ver `CLAUDE.md`
Seção 10, que registra também a limitação metodológica decorrente — avisar o
grupo sobre seu papel introduz um efeito motivacional não controlado.

**"Quero dominar o tópico T" vira um item.** O aluno escolhe um tópico, mas a
regra de desempate opera sobre itens. O objetivo passa a ser o **último item do
tópico**, cujo caminho de pré-requisitos contém todos os outros itens dali. Isso
pressupõe que os itens de um tópico formam uma cadeia — há teste conferindo, que
falha se um tópico ganhar dois itens finais independentes.

**A sessão vive no cookie de sessão do Django**, guardando só os ids do aluno e
da sessão de teste. Não há conta, não há senha, e não há dado pessoal para
guardar. Entrar com outro código começa do zero, porque o aparelho circula na
sala.

**Progresso medido em bits, não em perguntas.** A barra mostra quanto do espaço
de estados já foi eliminado, e o texto estima quantas perguntas faltam pelo log
do que resta. Como o teste é adaptativo, prometer um número exato seria mentira —
uma única resposta pode avançar muito.

## O instrumento de pesquisa (pré/pós-teste)

É o que gera o dado comparativo do TCC2, e **não se confunde** com o teste
adaptativo do app:

| | teste adaptativo | pré/pós-teste |
| --- | --- | --- |
| para quê | estimar o estado de conhecimento | medir desempenho |
| quem faz | só a turma piloto | **as duas turmas** |
| itens | escolhidos pelo motor, variam por aluno | conjunto fixo, ordem fixa |
| quantos | 5 a 6 de 15 possíveis | os 10, sempre |
| banco | `purpose=adaptive` | `purpose=instrument` |

### Os dois bancos de questões nunca se cruzam

Decisão metodológica, não organizacional. Se o pré/pós-teste usasse as questões
do banco adaptativo, a turma piloto veria durante a atividade exatamente os itens
pelos quais é medida, e parte do ganho observado seria artefato do instrumento —
não aprendizado. São 15 questões adaptativas e 10 de instrumento, sem overlap de
código nem de enunciado, verificado em teste.

`next_question` filtra por `purpose` para que o teste adaptativo nunca sirva uma
questão do instrumento.

### O grupo controle faz o instrumento

O bloqueio da Parte 4 vale **apenas** para o motor de recomendação. A turma
controle identifica-se normalmente, faz pré-teste e pós-teste, e é barrada só em
`/objetivo/`, `/teste/` e `/recomendacao/`. Aplicar o bloqueio também ao
instrumento trancaria o grupo controle fora da própria comparação, e não sobraria
com o que comparar o ganho do piloto.

### A etapa quem decide é o professor

`StudySettings` guarda em que ponto o estudo está — pré-teste, atividade,
pós-teste ou encerrado — e o professor vira a chave pelo admin, sem redeploy.
Sem isso um aluno poderia responder o pós-teste antes da atividade, e "antes" e
"depois" deixariam de significar alguma coisa.

O pré-teste é exigido antes de qualquer uso do app, inclusive para quem chegou
atrasado e só apareceu na etapa da atividade.

### Exportação

```bash
python manage.py export_results --output resultados.csv
```

Uma linha por aluno: `codigo, turma, pre_acertos, pos_acertos, ganho,
total_questoes, pre_concluido_em, pos_concluido_em, usou_o_app, sessoes_no_app`.

Duas decisões que importam para não enviesar a análise:

- **Aplicação não concluída sai como célula vazia, nunca como zero.** Zero
  significa "errou todas"; vazio significa "não fez". Tratar os dois como a mesma
  coisa puxaria o ganho médio do grupo para baixo.
- **`usou_o_app` é coluna de auditoria.** Um aluno de controle com `sim` aí seria
  contaminação do desenho — e precisa aparecer no dado, não ficar escondido.

Para auditar os escores à mão:

```bash
python manage.py export_responses --output respostas.csv
```

Uma linha por resposta. Contar as linhas com `acertou=sim` de um aluno numa fase
tem que dar exatamente o número da outra exportação — há teste conferindo essa
igualdade, e ela é o que permite refazer qualquer número citado no TCC2 sem
confiar no sistema.

Nenhuma estatística é calculada aqui. O sistema entrega o dado bruto; média,
desvio e teste de hipótese acontecem fora.

## Como rodar

```bash
python -m venv .venv
.venv/Scripts/activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py load_curriculum
python manage.py runserver
```

Depois disso, `http://127.0.0.1:8000/` mostra a cadeia carregada — é uma página
de verificação, não a interface do aluno.

Testes:

```bash
python manage.py test
```

## Comandos

| Comando | O que faz |
| --- | --- |
| `python manage.py load_curriculum` | Lê `domain/data/curriculum.json`, grava tópicos, itens e questões, regenera o espaço de conhecimento. Idempotente. |
| `python manage.py load_curriculum --dry-run` | Valida o arquivo e mostra o resumo, sem escrever no banco. |
| `python manage.py load_curriculum --prune` | Autoriza remover tópicos, itens e questões que saíram do arquivo. Sem esta opção, o comando falha em vez de apagar em cascata. |
| `python manage.py create_students --group pilot --count 30` | Gera códigos de acesso do grupo piloto. Troque para `--group control` para o grupo controle. |
| `python manage.py export_results` | Exporta turma, pré, pós e ganho de cada aluno, em CSV. |
| `python manage.py export_responses` | Exporta resposta a resposta do pré/pós-teste, para auditoria manual. |
| `python manage.py createsuperuser` | Cria o acesso ao `/admin/`, usado para inspecionar os dados e virar a etapa do estudo. |

## Estrutura

```
config/                     configuração Django, urls, views de verificação
domain/                     conteúdo versionado e estrutura de conhecimento
  data/curriculum.json      ← fonte da verdade: tópicos, itens e questões
  curriculum.py             leitura e validação do arquivo
  knowledge_space.py        fecho transitivo, geração dos estados, fronteira
  recommendation.py         ← Parte 2: fronteira ∩ caminho até o objetivo
  models.py                 Topic, KnowledgeItem, KnowledgeState, Question
assessment/                 o que só existe porque um aluno usou o sistema
  engine.py                 ← Parte 3: teste adaptativo (lógica pura)
  services.py               ponte com o banco; é o que as views chamam
  views.py                  ← Partes 4 e 5: telas do app e do instrumento
  models.py                 AssessmentSession, InstrumentSession, StudySettings
  management/commands/      ← Parte 5: as duas exportações em CSV
templates/assessment/       as telas
static/css/app.css          estilo, pensado para celular primeiro
students/
  codes.py                  geração e normalização dos códigos de acesso
  models.py                 Student (código + grupo, sem dado pessoal)
```

### Nomenclatura

O repositório de referência usa `State` para o item atômico e `Node` para o
conjunto de itens dominados. Aqui foram adotados os nomes da literatura de KST,
porque é ela que o texto do TCC2 cita:

| Literatura (Doignon & Falmagne; Steiner et al.) | Referência | Aqui |
| --- | --- | --- |
| item do domínio Q | `State` | `KnowledgeItem` |
| estado de conhecimento K ⊆ Q | `Node` | `KnowledgeState` |

### Como a relação de pré-requisito é derivada

Decisão de modelagem com implicação metodológica, então explícita:

**Cada item declara por completo os seus pré-requisitos diretos**, no campo
`prerequisites`, inclusive os que apontam para itens de outro tópico. O fecho
transitivo dessas arestas é a relação usada para gerar o espaço de conhecimento.
Não há herança implícita: o que não está declarado não é pré-requisito.

O campo `prerequisites` do tópico continua existindo, mas não gera aresta
nenhuma — declara a cadeia de tópicos como afirmação legível. O carregamento
confere que as duas coisas contam a mesma história: nenhuma aresta cruza para um
tópico fora da cadeia declarada, e nenhum tópico declara pré-requisito que nenhum
item realiza.

#### Acesso parcial (validado em 10/09/2026)

Até 10/09/2026 valia outra regra — todo item herdava todos os itens dos tópicos
pré-requisito, de modo que um tópico só ficava acessível com o anterior
**inteiramente** dominado. A entrevista de validação pedagógica derrubou isso
(`CLAUDE.md` Seção 9): o aluno pode começar função exponencial com lacunas em
parte da função afim.

Dos três itens de função afim, só um bloqueia função exponencial:

| item | papel na entrevista | bloqueia exponencial? |
| --- | --- | --- |
| `fa-lei-formacao` | operações algébricas elementares; função como relação entre grandezas | **sim** |
| `fa-coeficientes` | coeficiente angular = taxa de variação | não |
| `fa-grafico-raiz` | profundidade procedimental | não |

Progressões e logaritmo **seguem exigindo o tópico anterior inteiro** — a
entrevista tratou de função exponencial e não se pronunciou sobre acesso parcial
nesses dois casos. Estender por analogia seria extrapolação sem fonte.

Com o currículo atual (5 tópicos, 15 itens), o espaço tem **46 estados de
conhecimento** (eram 34 sob a regra antiga). Esse número é conferido em teste
contra a enumeração por força bruta de todos os 2¹⁵ subconjuntos. Dos 12 estados
novos, todos são casos de aluno que avançou em exponencial sem fechar função
afim — exatamente o que a estrutura antiga tornava impossível de representar.

## Configuração por ambiente

Toda configuração sensível a ambiente vem de variáveis de ambiente — ver
`.env.example`. As que importam:

- `DJANGO_SECRET_KEY` — obrigatória quando `DJANGO_DEBUG=0`; a ausência é erro,
  não degradação silenciosa.
- `DJANGO_DEBUG` — `1` em desenvolvimento, `0` em produção.
- `DJANGO_ALLOWED_HOSTS` — domínios servidos, separados por vírgula.
- `DATABASE_URL` — Postgres da Neon. Obrigatória quando `DJANGO_DEBUG=0`; em
  desenvolvimento pode ficar vazia e o projeto usa SQLite.

## Deploy

O servidor de desenvolvimento (`runserver`) atende um pedido por vez e **não
deve ser usado no piloto** — uma turma inteira respondendo ao mesmo tempo
enfileira de forma perceptível. O `Procfile` e o `build.sh` já usam `gunicorn`.

`gunicorn` não instala no Windows (depende de `fcntl`); o marcador no
`requirements.txt` cuida disso — instala no host Linux e é ignorado localmente.

### Render (recomendado)

Com o repositório no GitHub, crie um *Web Service* apontando para ele e use:

- Build command: `./build.sh`
- Start command: `gunicorn config.wsgi:application --workers 3 --timeout 60`
- Health check path: `/healthz`
- Variáveis: `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY` (gerada),
  `PYTHON_VERSION=3.11.9` e `DATABASE_URL` (a string da Neon — ver abaixo)

O `render.yaml` na raiz descreve o mesmo serviço como blueprint, caso prefira.
`ALLOWED_HOSTS` e `CSRF_TRUSTED_ORIGINS` são preenchidos automaticamente a partir
de `RENDER_EXTERNAL_HOSTNAME`, que o Render publica sozinho.

Gerar a `SECRET_KEY`:

```bash
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

### Banco de dados: Postgres na Neon

**Decidido:** o Postgres fica fora do Render, na [Neon](https://neon.tech),
ligado pela variável `DATABASE_URL`.

Motivo: o Postgres gratuito do Render é apagado depois de 30 dias corridos —
prazo menor que a janela entre o pré-teste e o pós-teste. E SQLite não resolve,
porque o sistema de arquivos do Render é efêmero sem disco persistente: a cada
deploy ou reinício o arquivo do banco é recriado vazio. Nos dois casos a perda é
silenciosa, e num piloto sem segunda chance isso custa o experimento inteiro.

O `render.yaml` **não** provisiona banco nenhum, de propósito. `DATABASE_URL`
está declarada com `sync: false`: o Render pede o valor na criação do blueprint
em vez de guardá-lo no arquivo, porque a string da Neon carrega a senha do banco.

Para ligar:

1. Criar o projeto na Neon e copiar a connection string do painel.
2. Colar em `DATABASE_URL` no serviço do Render.
3. Fazer um deploy — `build.sh` roda `migrate` e `load_curriculum` contra o banco
   novo.

Não é preciso mudar código: `dj-database-url` já repassa `sslmode` e
`channel_binding` da URL da Neon para as `OPTIONS` do driver.

Dois detalhes da Neon que valem para o dia da aplicação:

- O plano gratuito **suspende a computação por inatividade**. A primeira conexão
  depois de um período parado paga um cold start. Abrir `/healthz` alguns minutos
  antes da aula resolve — essa rota toca o banco de propósito, então aquece a
  conexão junto. Com `CONN_HEALTH_CHECKS` ligado, uma conexão derrubada pela
  suspensão é descartada e refeita em vez de estourar erro no primeiro aluno.
- Com 3 workers do gunicorn são 3 conexões persistentes, folgado no limite do
  plano. Se um dia o número de workers subir bastante, o caminho é a connection
  string *pooled* da Neon (a que tem `-pooler` no host), não mexer aqui.

⚠️ **Se `DATABASE_URL` ficar em branco, o app sobe assim mesmo — com SQLite
efêmero.** Conferir que está preenchida antes de qualquer aplicação com alunos.

## Regras que atravessam o código

- Nenhum dado pessoal de aluno é armazenado — nem nome, nem e-mail, nem
  matrícula. O único identificador é o código curto entregue pelo professor.
- Nenhum dado real de aluno em *seeds*, *fixtures* ou no repositório.
- O banco de dados não é versionado.
- O sistema não é descrito como "IA" nem como "machine learning" em nenhum lugar,
  porque não é.

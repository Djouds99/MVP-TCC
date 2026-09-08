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

## Estado atual: Partes 1 a 3 concluídas

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
  em 4 a 6 perguntas, e alimenta o motor de recomendação diretamente.
- Banco de questões de múltipla escolha, uma por item, funcional mas provisório.

O que **não** existe ainda (partes seguintes do roadmap): interface do aluno,
instrumento de pré/pós-teste, conteúdo em redação final.

## O motor de recomendação

Em [`domain/recommendation.py`](domain/recommendation.py). A regra tem duas
etapas:

1. **Fronteira externa** — dado o estado de conhecimento estimado, os candidatos
   brutos são os itens ainda não dominados cujos pré-requisitos já estão todos
   dominados.
2. **Desempate por objetivo** — a escolha é a interseção entre a fronteira e o
   caminho de pré-requisitos até o objetivo declarado pelo aluno
   (STEINER; NUSSBAUMER; ALBERT, 2009).

O que a regra faz, no domínio ilustrativo do roadmap
(`PC → FA → {FE, PR}`, `FE → LOG`):

| estado atual | objetivo | fronteira bruta | recomendação |
| --- | --- | --- | --- |
| `{}` | `LOG` | `{PC}` | `PC` |
| `{PC, FA}` | `LOG` | `{FE, PR}` | `FE` |
| `{PC, FA}` | `PR` | `{FE, PR}` | `PR` |
| `{PC, FA, FE}` | `LOG` | `{PR, LOG}` | `LOG` |
| domínio completo | `LOG` | `{}` | nenhuma — `DOMAIN_COMPLETE` |

As duas linhas do meio são o ponto: mesmo estado, mesma fronteira bruta,
recomendação diferente só porque o objetivo mudou.

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
respostas. Começa com todos os 34 e, a cada resposta, descarta os incompatíveis:
acertou o item `q` → ficam só os estados que contêm `q`; errou → ficam só os que
não contêm. A próxima pergunta é sobre o item que divide mais ao meio o conjunto
restante. Termina quando sobra um único estado, que é a estimativa.

Como os estados são fechados para baixo, uma resposta carrega muito mais
informação que o item perguntado: acertar uma questão de progressões confirma de
uma vez plano cartesiano e função afim inteiros.

| | |
| --- | --- |
| itens no domínio (sondagem exaustiva) | 15 |
| perguntas do teste adaptativo | 4 a 6, média 5,1 |
| pior caso vs. limite teórico (⌈log₂ 34⌉) | 6 vs. 6 |
| estados recuperados corretamente | 34 de 34 |

### Por que não é uma busca binária ao longo da cadeia

O roadmap previa busca binária. Ela pressupõe que o domínio está totalmente
ordenado e que o conhecimento do aluno é um **prefixo** dessa ordem — e a cadeia
deste MVP não é uma fila: função exponencial e progressões ficam disponíveis em
paralelo assim que função afim é dominada.

**18 dos 34 estados não são prefixo de ordem linear nenhuma.** Na prática, uma
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
`recommendation_for`. A interface da Parte 5 deve chamar essas funções, não o
motor diretamente.

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
| `python manage.py createsuperuser` | Cria o acesso ao `/admin/`, usado só para inspecionar os dados coletados. |

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
  services.py               ponte com o banco; é o que a interface deve chamar
  models.py                 AssessmentSession, QuestionResponse
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

1. Dentro de um tópico, valem as arestas declaradas no campo `prerequisites` de
   cada item — e só podem apontar para itens do mesmo tópico.
2. Entre tópicos, todo item de um tópico `T` exige **todos** os itens de cada
   tópico diretamente pré-requisito de `T`.

O fecho transitivo dessas duas regras define a relação usada para gerar o espaço
de conhecimento. Em outras palavras: um tópico só é considerado acessível quando
os anteriores estão inteiramente dominados. Se a intenção for permitir entrada
parcial num tópico seguinte, é a regra 2 que precisa mudar — e a mudança precisa
aparecer também na metodologia do TCC2.

Com o currículo atual (5 tópicos, 15 itens), o espaço tem **34 estados de
conhecimento**. Esse número é conferido em teste contra a enumeração por força
bruta de todos os 2¹⁵ subconjuntos.

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

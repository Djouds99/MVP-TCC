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

## Estado atual: Parte 1 concluída

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

O que **não** existe ainda (partes seguintes do roadmap): fronteira e desempate
por objetivo, banco de questões, teste adaptativo, interface do aluno,
instrumento de pré/pós-teste, conteúdo em redação final.

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
| `python manage.py load_curriculum` | Lê `domain/data/curriculum.json`, grava tópicos e itens, regenera o espaço de conhecimento. Idempotente. |
| `python manage.py load_curriculum --dry-run` | Valida o arquivo e mostra o resumo, sem escrever no banco. |
| `python manage.py load_curriculum --prune` | Autoriza remover tópicos/itens que saíram do arquivo. Sem esta opção, o comando falha em vez de apagar em cascata. |
| `python manage.py create_students --group pilot --count 30` | Gera códigos de acesso do grupo piloto. Troque para `--group control` para o grupo controle. |
| `python manage.py createsuperuser` | Cria o acesso ao `/admin/`, usado só para inspecionar os dados coletados. |

## Estrutura

```
config/                     configuração Django, urls, views de verificação
domain/
  data/curriculum.json      ← fonte da verdade do conteúdo do domínio
  curriculum.py             leitura e validação do arquivo
  knowledge_space.py        fecho transitivo e geração dos estados
  models.py                 Topic, KnowledgeItem, KnowledgeState, CurriculumRelease
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
- `DATABASE_URL` — se preenchida, tem prioridade sobre o SQLite.

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
- Variáveis: `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY` (gerada), `PYTHON_VERSION=3.11.9`

O `render.yaml` na raiz descreve o mesmo serviço como blueprint, caso prefira.
`ALLOWED_HOSTS` e `CSRF_TRUSTED_ORIGINS` são preenchidos automaticamente a partir
de `RENDER_EXTERNAL_HOSTNAME`, que o Render publica sozinho.

Gerar a `SECRET_KEY`:

```bash
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

### ⚠️ Banco de dados: risco de perda de dados no piloto

SQLite dá conta do volume de duas turmas, mas em hospedagem gerenciada sem disco
persistente **o sistema de arquivos é efêmero**: a cada deploy ou reinício, o
arquivo do banco é recriado vazio. Num piloto que coleta pré-teste e pós-teste ao
longo de semanas, isso significa perder os dados coletados sem aviso.

Antes da aplicação real, escolha uma das duas saídas:

1. Anexar um disco persistente ao serviço e apontar `DJANGO_SQLITE_PATH` para um
   caminho dentro dele.
2. Criar um Postgres gerenciado e definir `DATABASE_URL`. O projeto já lê essa
   variável e já tem o driver instalado — é mudança de configuração, não de
   código.

Testar essa escolha **antes** do piloto, não no dia.

## Regras que atravessam o código

- Nenhum dado pessoal de aluno é armazenado — nem nome, nem e-mail, nem
  matrícula. O único identificador é o código curto entregue pelo professor.
- Nenhum dado real de aluno em *seeds*, *fixtures* ou no repositório.
- O banco de dados não é versionado.
- O sistema não é descrito como "IA" nem como "machine learning" em nenhum lugar,
  porque não é.

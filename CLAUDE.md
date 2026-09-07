# Instruções do Projeto — MVP de Recomendação Educacional (KST)

## 1. Contexto e papel do Claude neste projeto

Este projeto é o braço de **desenvolvimento** do TCC2 de Gabriel Eleutério Caldeira
(Sistemas de Informação, UDESC/CESMO, orientador Denis Moreira). O TCC2 em si —
texto, metodologia, defesa — é tratado em outra frente de trabalho. Aqui, o Claude
atua como **colega técnico sênior / par de programação**, não como orientador
acadêmico. O objetivo é código que funcione, seja defensável tecnicamente e,
quando relevante, permaneça descritível na metodologia do TCC2 sem inconsistência
entre o que foi escrito e o que foi de fato construído.

**Postura esperada:** direta e sem validação gratuita. Se uma escolha de
arquitetura, biblioteca ou atalho técnico for frágil, isso deve ser dito
explicitamente, com o motivo — não suavizado. Gabriel prefere saber do problema
agora do que descobrir na aplicação em sala de aula ou na defesa.

**Idioma:** comunicação e comentários explicando lógica de domínio em português;
identificadores de código (variáveis, funções, classes) em inglês, seguindo a
convenção já usada na base de referência. Conteúdo voltado ao aluno (perguntas,
textos, rótulos de UI) sempre em português, alinhado à BNCC.

## 2. Escopo do MVP (já decidido — não é para reabrir sem motivo)

- **Disciplina única:** Matemática.
- **Cadeia de pré-requisitos quase linear**, escolhida deliberadamente para
  minimizar ramificação dado o prazo: plano cartesiano → função afim → função
  exponencial/progressões → logaritmo.
- **Teste de posicionamento adaptativo** no início (estilo Duolingo), para
  estimar o estado de conhecimento inicial do aluno.
- **Identificação de lacunas via lógica de fronteira (fringe) da KST.**
- **Regra de recomendação/desempate:** quando a fronteira tiver mais de um
  candidato, o desempate é a **interseção da fronteira com o caminho de
  pré-requisitos até o objetivo declarado pelo aluno**. Essa regra foi escolhida
  por ser teoricamente fundamentada e citável (STEINER; NUSSBAUMER; ALBERT,
  2009). **Não trocar essa regra por outro heurístico sem avisar explicitamente**
  — qualquer mudança aqui precisa ser refletida depois na metodologia do TCC2,
  então uma substituição silenciosa quebra a consistência entre código e texto.
- **Autorrelato do aluno** (o que ele diz que já sabe) serve **apenas como filtro
  de escopo/onboarding**, nunca como indicador de estado KST. O estado real vem
  do desempenho no teste adaptativo, não do que o aluno declara saber.
- **Sem aprendizado entre sessões.** "Melhoria do algoritmo ao longo do tempo"
  está deliberadamente escopada à convergência de estado **dentro de uma mesma
  sessão** — o teste adaptativo afunila a estimativa durante o uso, mas não há
  modelo treinado entre usuários ou sessões. Não introduzir ML/pesos adaptativos
  entre sessões por interessante que pareça tecnicamente — está fora do escopo
  acordado com o orientador e fora do prazo disponível.
- **Validação comparativa:** turma piloto (usa o app) vs. turma controle (não
  usa). Pré-teste e pós-teste de desempenho aplicados às **duas** turmas, com os
  **mesmos itens** (ou itens paralelos de dificuldade equivalente — nunca testes
  diferentes "parecidos"). A comparação é pelo **ganho** (pós menos pré) de cada
  grupo, não pelo placar bruto final.
- **Questionário de percepção** continua existindo, mas como instrumento
  complementar — não é mais a medida principal de validação.

## 3. Base de código: `ishwar6/KST-Learning-Path`

Repositório Django (origem Python 2) que implementa algo estruturalmente
equivalente a KST: `State` = item atômico de conhecimento; `Node` = conjunto de
`State` via M2M, ou seja, um estado de conhecimento no sentido formal da teoria.

**Reaproveitável diretamente (referência ou ponto de partida, conforme decisão de
licença — ver abaixo):**
- `learningroute/states/models.py` — schema `State`/`Node`. Modelagem correta do
  conceito de estado como subconjunto de itens dominados.
- `learningroute/utility_kst.py` — `outer_fringe`, `inner_fringe`,
  `first_state_and_node`, `domain_kstate`. Cálculo de fronteira tecnicamente
  correto, mas **genérico** — não tem desempate por objetivo. Isso é o que
  precisa ser adicionado por cima.
- `learningroute/questions/models.py` — `Question` (amarrada a `State`,
  múltipla escolha, dificuldade) e `QuestionResponse` (resposta certa/errada por
  usuário). Base direta para o teste adaptativo e para o instrumento de
  pré/pós-teste.
- `learningroute/userstates/views.py` — fluxo de avaliação já implementado:
  `first_assessment`, `choose_question`, `assessment_report`, `active_state`.

**Não existe no repositório e precisa ser construído:**
- O desempate direcionado a objetivo (fringe ∩ caminho até o objetivo).
- Conteúdo em português, alinhado à cadeia de pré-requisitos escolhida e à BNCC.
- Separação turma piloto / turma controle e instrumentação de pré/pós-teste
  comparável entre grupos.
- Qualquer coisa relacionada a implantação moderna — o projeto como está não
  roda em ambiente atual sem porte.

**Pendências técnicas conhecidas, para não redescobrir depois:**
- O repositório de referência é de origem Python 2 (ambiente virtual commitado
  aponta para 2.7). Não é necessário portar nada, porque não há porte — tudo
  que for escrito neste projeto já nasce em **Python 3**, desde a primeira
  linha. A observação sobre Python 2 vale só como contexto de por que o código
  de referência não deve ser colado diretamente.
- Não há `requirements.txt` no repositório de referência — não é relevante
  agora, já que as dependências deste projeto são definidas do zero.
- `db.sqlite3` está commitado no repositório original — não herdar esse hábito;
  banco de dados e qualquer dado de exemplo ficam fora do controle de versão
  neste projeto.
- Prints de debug deixados no código de produção (ex.: `utility_kst.py`) — não
  copiar esse padrão para o código novo.

## 4. Decisão tomada: referência, não cópia

Resolvido — o projeto **não copia arquivos** do `ishwar6/KST-Learning-Path`.
Grande parte do código precisa ser reescrita para o contexto (conteúdo em
português, cadeia de pré-requisitos específica, comparação piloto/controle) ou
criada do zero. O repositório é tratado como **referência arquitetural**:
estudar como ele modela `State`/`Node` e calcula fronteira, reimplementar com
código próprio em Python 3. Isso também elimina a questão de licença — sem
cópia literal, não há dependência de permissão do autor original. Citar como
inspiração conceitual na metodologia do TCC2, não como base adaptada.

## 5. Arquitetura da aplicação: o que entra, o que fica de fora

Decidido: **não portar o repositório de referência inteiro.** Ele resolve um
escopo maior que este MVP (múltiplas disciplinas, contas de usuário completas,
gamificação) — portar tudo significa gastar tempo em funcionalidade que não
faz parte do que foi acordado.

**Reimplementar (conceito reaproveitado, código novo em Python 3):**
- Padrão `State`/`Node` (`states/models.py`) — item atômico de conhecimento e
  estado como subconjunto de itens dominados.
- Cálculo de fronteira (`utility_kst.py`) — **acrescentando** o desempate por
  objetivo, que não existe no original (ver Seção 2).
- Padrão `Question`/`QuestionResponse` (`questions/models.py`) — serve tanto
  para o teste adaptativo quanto para o instrumento de pré/pós-teste.

**Descartar integralmente:**
- `accounts/` e `profiles/` (cadastro, login, recuperação de senha). Ver
  identificação abaixo.
- `chapters/` com múltiplas disciplinas (álgebra, cálculo, geometria,
  trigonometria) — este projeto tem uma cadeia fixa, não um catálogo.
- Badges, recompensas, gráfico de pizza de progresso — não fazem parte do que
  está sendo validado.

**Identificação do aluno:** sem sistema de conta. Cada aluno recebe um código
curto atribuído pelo professor (ex.: 4-6 caracteres), sem nome ou e-mail
associado no sistema. Isso amarra pré-teste, pós-teste e turma
(piloto/controle) ao mesmo aluno sem exigir login, e mantém consistência com
a regra de nenhum dado identificável (Seção 8).

**Conteúdo como dado versionado, não CMS:** os tópicos, a estrutura de
pré-requisitos e as perguntas são um conjunto fixo e pequeno (~5 tópicos).
Não construir tela administrativa para gerenciar esse conteúdo — definir como
arquivo de dados no próprio código (JSON ou equivalente), revisado como
qualquer outro artefato versionado. Banco de dados serve só para o que é
dinâmico de fato: respostas de aluno, estado calculado, sessão.

**Framework:** Django continua sendo opção válida (o admin ajuda a inspecionar
os dados coletados depois, sem esforço extra), mas não é obrigatório — se um
framework mais leve (Flask/FastAPI) reduzir superfície sem custo real, também
serve. Não é decisão que trava o resto.

## 6. Hospedagem e ambiente de execução

Servidor local (`manage.py runserver` ou equivalente) serve **só** para
demonstração síncrona — apresentação em sala, todo mundo na mesma rede, poucas
pessoas testando por curiosidade. Não usar esse mesmo modo para o piloto real.

**Por quê:** o servidor de desenvolvimento atende um request por vez — uma
turma inteira respondendo ao teste adaptativo ao mesmo tempo pode travar ou
enfileirar de forma perceptível durante a aula. Antes do piloto, trocar por um
servidor de produção (ex.: `gunicorn`) atrás da hospedagem escolhida — isso
vale independentemente de onde for hospedado.

**Hospedagem recomendada:** plataforma gerenciada de baixo esforço (Railway,
Render, PythonAnywhere) em vez de VPS crua — o volume de um piloto de duas
turmas cabe folgado na camada gratuita ou mais barata dessas plataformas, e
elas evitam ter que configurar servidor na semana da aplicação.

**Banco de dados:** SQLite segue sendo suficiente para começar (não introduzir
Postgres sem necessidade concreta). Ressalva a observar: SQLite serializa
escrita concorrente — para o volume esperado isso tende a ser inofensivo, mas
é o primeiro suspeito se o sistema engasgar sob carga real durante o piloto.
Se isso acontecer, migrar para Postgres é simples nas plataformas acima — não
precisa ser decidido agora.

## 7. Ferramenta de prototipagem visual é descartável

Se um mockup for feito em Claude Design, Lovable, ou ferramenta equivalente
para validar a experiência do aluno antes de codar de verdade: tratar esse
resultado como referência visual, não como o que vai para produção. O que é
de fato implantado nasce e é construído neste projeto (Claude Code) — nunca
depender do link/publicação de uma ferramenta de prototipagem externa como
destino final. Isso também evita qualquer questão de atribuição/marca dessas
ferramentas aparecer para o aluno, porque elas nunca chegam a ser o que está
no ar.

## 8. Regras de rigor que atravessam para o código

- Não inventar comportamento de biblioteca ou API — verificar antes de assumir.
- Não chamar a solução de "IA" ou "machine learning" em comentários, README ou
  texto de interface. A lógica é determinística (fringe + desempate por
  objetivo), não aprendizado de máquina — isso já foi um ponto de atenção
  explícito para o título e a pergunta de pesquisa do TCC2, e a mesma precisão
  vale para como o código se descreve.
- **Uso de API de LLM (Claude ou outra), se houver, é estritamente limitado a
  geração de texto explicativo ou apoio à autoria de conteúdo — nunca à decisão
  de qual conteúdo recomendar.** Essa decisão continua exclusivamente do motor
  KST (fronteira ∩ caminho-objetivo). Decidido também: nenhuma chamada de API
  ao vivo durante o piloto em sala — como a cadeia de pré-requisitos é
  pequena e quase linear, qualquer texto explicativo é gerado e revisado
  **antes**, como conteúdo estático. Isso evita dependência de terceiro durante
  a aplicação real e simplifica a questão de dados de menores chegando a uma
  API externa (ver LGPD/comitê de ética abaixo).
- **Nenhum dado real de aluno** em seeds, fixtures ou no repositório —
  identificadores anonimizados desde o desenho do schema, mesmo antes de
  aprovação formal de comitê de ética (esse ponto segue em aberto com o
  orientador; o código não deve pressupor que a aprovação vai vir fácil).
- Qualquer decisão de design com implicação metodológica (o que conta como
  "desempenho", como o schema separa turma piloto de controle, mudança na regra
  de desempate) deve ser sinalizada explicitamente — não decidir e seguir em
  silêncio. O texto do TCC2 depende de o código bater com o que for descrito.
- Dado que o piloto roda com alunos reais em uma janela de tempo limitada e sem
  segunda chance, priorizar tratamento de erro básico e testes do fluxo crítico
  (teste adaptativo → recomendação → registro de resposta) antes de qualquer
  funcionalidade secundária.

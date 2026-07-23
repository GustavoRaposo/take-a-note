# Roadmap — Tomenotas (v2: aplicação profissional)

Este documento descreve a evolução do projeto atual (3 scripts bash +
atalhos do GNOME) para uma aplicação de verdade: um processo em background
com ícone na bandeja do sistema (AppIndicator), interface para gerenciar
notas, e atalhos de teclado que só funcionam enquanto o app está aberto.

## Por que mudar de arquitetura

Os scripts bash atuais funcionam, mas têm limitações estruturais pra virar
"produto":

- Não têm estado compartilhado — cada script roda isolado, então não dá pra
  saber "o app está gravando agora?" de fora.
- Os atalhos do GNOME (`gsettings custom-keybindings`) chamam os scripts
  diretamente e continuam funcionando mesmo se você "fechar" o app (porque
  não existe um app de fato rodando, só scripts avulsos).
- Não há UI — tudo é notificação (`notify-send`) e menu de seleção
  (`zenity`).
- Não dá pra mudar o atalho sem editar `gsettings` na mão.

A solução é ter **um processo único de longa duração** (o "daemon") que:

1. Mantém o estado (idle / gravando / transcrevendo).
2. Expõe um ícone na bandeja (AppIndicator) que reflete esse estado.
3. Expõe uma UI (janela GTK) para listar/tocar notas e configurar atalhos.
4. Registra os atalhos de teclado só enquanto está rodando — se você fechar
   o app, os atalhos morrem junto.

## Decisões técnicas propostas

| Item | Escolha | Motivo |
|---|---|---|
| Linguagem | Python 3 | Bindings maduros para GTK/AppIndicator, fácil reaproveitar a lógica dos scripts atuais |
| Tray icon | `AyatanaAppIndicator3` (via PyGObject) | É o que Steam, Discord e outros apps usam no Ubuntu/GNOME para ícone na bandeja com menu |
| UI | GTK3 (PyGObject) | Nativo, leve, integra bem com o AppIndicator |
| IPC (atalho → app) | D-Bus (serviço próprio, ex: `com.tomenotas.Daemon`) | Permite que o atalho "só funcione com o app aberto": se o app não estiver rodando, a chamada D-Bus simplesmente falha e nada acontece |
| Atalhos globais | `gsettings custom-keybindings` gerenciados pelo próprio app, apontando para um cliente D-Bus leve | GNOME no Wayland não permite que apps capturem hotkeys globais diretamente (sandbox); esse é o mecanismo confiável disponível hoje. Ver "Riscos" abaixo para uma alternativa futura via portal. |
| Armazenamento de notas | Mantém arquivos `.txt` (v2) → considerar SQLite na v3 | Simplicidade agora, espaço para evoluir depois |
| STT / TTS | Mantém whisper.cpp e Piper, chamados via subprocess a partir do daemon | Já validado e funcionando |

## Fase 0 — Estado atual (concluído)

- [x] `gravar.sh` — grava e transcreve
- [x] `listar.sh` — lista notas e seleciona a atual
- [x] `ler.sh` — lê a nota atual em voz alta
- [x] `install.sh` / `uninstall.sh`
- [x] Atalhos via `gsettings custom-keybindings`

## Fase 1 — Esqueleto do daemon (concluído)

Objetivo: ter um processo Python rodando em background com ícone na
bandeja, ainda sem UI de notas.

- [x] Criar `tomenotas-daemon` (processo Python com `GLib.MainLoop`)
- [x] Ícone na bandeja via `AyatanaAppIndicator3`, com menu básico:
      "Abrir", "Sair"
- [x] Serviço D-Bus próprio (`com.tomenotas.Daemon`) com métodos iniciais:
  - `ToggleRecording()`
  - `Ping()` (útil para os atalhos saberem se o daemon está vivo)
- [x] Migrar a lógica de `gravar.sh` (arecord + whisper.cpp) para dentro do
      daemon, chamado via `ToggleRecording()`
- [x] Cliente D-Bus leve (`tomenotas-hotkey-record`) para ser o alvo do
      atalho de teclado — só chama o método, não faz mais nada sozinho

**Critério de pronto:** apertar o atalho de gravar só funciona com o
daemon aberto; fechando o daemon pelo menu da bandeja, o atalho não faz
nada (a chamada D-Bus falha silenciosamente).

## Fase 2 — UI de notas (listar + tocar) (concluído)

- [x] Janela GTK principal, aberta a partir do menu da bandeja ou ao clicar
      no ícone
- [x] Lista de notas (mais recente primeiro), com prévia do texto
- [x] Botão "Play" por nota (ou nota selecionada) que chama o Piper e toca
      o áudio
- [x] Indicador visual de "tocando agora" (ex: ícone de play muda pra pause
      durante a reprodução)
- [x] Botão para apagar nota direto na UI (substitui os comandos manuais
      de `rm`)
- [x] Busca/filtro simples por texto na lista de notas

**Critério de pronto:** dá pra abrir a janela, ver todas as notas, tocar
qualquer uma com um clique, e apagar sem terminal.

## Fase 3 — Atalhos configuráveis pela UI (concluído)

- [x] Aba/janela de "Configurações" com 3 campos de atalho (gravar, listar,
      ler) usando um widget de captura de tecla (`Gtk.EventControllerKey`
      ou similar)
- [x] Ao salvar, o daemon atualiza os `gsettings custom-keybindings`
      automaticamente (equivalente ao que o `install.sh` faz hoje, mas via
      UI em vez de flags de linha de comando)
- [x] Validação de conflito (avisar se o atalho já está em uso por outro
      app do sistema, quando possível detectar)

**Critério de pronto:** mudar um atalho na UI reflete imediatamente no
comportamento do teclado, sem precisar editar nada manualmente.

## Fase 4 — Feedback visual de estado no ícone (concluído)

- [x] Três ícones (idle, gravando, transcrevendo) como assets do projeto
- [x] Daemon troca o ícone (`AppIndicator.set_icon()`) conforme a máquina de
      estados: `idle → recording → transcribing → idle`
- [x] Opcional: "pulsar" o ícone de gravando/transcrevendo alternando entre
      duas variantes a cada N ms (`GLib.timeout_add`), já que AppIndicator
      não suporta GIF/animação nativamente
- [x] Tooltip do ícone reflete o estado atual ("Gravando...",
      "Transcrevendo...", "Ocioso")

**Critério de pronto:** dá pra saber o estado do app só olhando pro ícone
na bandeja, sem abrir a janela.

## Fase 5 — Polimento e distribuição (concluído)

- [x] Iniciar automaticamente no login (arquivo `.desktop` em
      `~/.config/autostart/`)
- [x] Persistir configurações (atalhos, tamanho de modelo, voz escolhida)
      em `~/.config/tomenotas/config.json` (caminhos de modelo/voz no
      config.json; atalhos persistem nos gsettings, geridos pela UI)
- [x] Logging estruturado (arquivo de log em
      `~/.local/share/tomenotas/daemon.log`) para facilitar debug
- [x] Tratamento de erros na UI (ex: "microfone não encontrado", "modelo
      whisper não carregado") em vez de falhar silenciosamente
- [x] Empacotar como `.deb` (ou pelo menos um instalador único que resolve
      dependências Python via `venv`) — atendido pelo install.sh + venv;
      .deb fica como ideia futura no backlog
- [x] Atualizar `install.sh`/`uninstall.sh` para instalar/remover o daemon
      e o autostart
- [x] Clicar em uma notificação e abrir a tela do Tomenotas
- [x] Alterar o título da notificação para Tomenotas em vez de notify-send

## Ideias para depois (backlog, sem compromisso)

- [ ] **Migrar a UI para GTK4 + libadwaita** — visual GNOME moderno de
      verdade: `Adw.ApplicationWindow`, lista de notas com `Adw.ActionRow`,
      toasts (ex: "Nota apagada — Desfazer"), `Adw.PreferencesWindow` para
      a tela de Configurações, dark mode automático. Restrição: o
      `AyatanaAppIndicator3` só funciona com GTK3 (GTK3 e GTK4 não coexistem
      no mesmo processo), então a bandeja sai do daemon e vira um
      **processo satélite mínimo em GTK3** (só ícone + menu), conversando
      com o daemon pelos métodos D-Bus que já existem (`ShowWindow`,
      `ShowSettings`, `ToggleRecording`, `Ping`). A separação
      núcleo/cola atual (núcleo 100% testado, cola fina) torna essa troca
      de "casca" barata — o núcleo não muda.
- [x] Migrar armazenamento de notas para SQLite com migrations
      (`notes_db.py` + `migrations.py`; espelho `.txt` mantido para os
      scripts legados) — ver detalhamento na seção abaixo
- [x] UI de filtros/tags/favoritos na janela de notas: busca FTS com
      ranking, chips de tags (interseção), estrela de favorito por nota,
      popover de tags (marcar/desmarcar/criar) e filtro de período
- [x] Tela de detalhe da nota (clicar numa nota): conteúdo completo
      editável, favoritar, taguear, tocar e apagar; salvar retorna à lista
- [x] Sidebar na janela principal com seções Notas / Tags / Configurações:
      CRUD completo de tags (criar, listar com contagem, renomear com
      merge, apagar) e a tela de atalhos embutida (a janela separada de
      Configurações foi absorvida)
- [ ] Exportar notas (Markdown, texto simples, ou até áudio re-sintetizado)
- [ ] Atalho para editar o texto da nota manualmente antes de "arquivar"
- [ ] Suporte a múltiplas vozes Piper (trocar pela UI)
- [ ] Avaliar `xdg-desktop-portal` GlobalShortcuts como alternativa nativa
      ao `gsettings custom-keybindings` (ver riscos abaixo)
- [ ] **Renomear o projeto para honey-note** — em tudo que carrega o nome
      atual:
  - pacote Python `tomenotas` → `honey_note` (e entry point
    `honey-note-daemon`), clientes `tomenotas-hotkey-*` →
    `honey-note-hotkey-*`, `tomenotas-open` → `honey-note-open`
  - nome D-Bus `com.tomenotas.Daemon` → `com.honeynote.Daemon` (atualizar
    os 3 clientes e os ids dos atalhos `tomenotas-*` no gsettings)
  - diretórios de dados/config: `~/.local/share/tomenotas/` →
    `~/.local/share/honey-note/` e `~/.config/tomenotas/` →
    `~/.config/honey-note/` — **com migração automática no install.sh**
    (mover `notes.db`, `notes/`, config e log da instalação antiga, sem
    perda de dados; mesma garantia das migrations)
  - arquivos `.desktop` (menu + autostart), ícones
    (`tomenotas-*.svg` → `honey-note-*.svg`), logger `tomenotas.*`,
    `--app-name` das notificações, título da janela
  - documentos: README, ROADMAP, CLAUDE.md (e avaliar renomear o repo
    `take-a-note` no GitHub)
- [ ] **Padronizar os `.py` para desenvolvimento em inglês** —
      identificadores (funções, variáveis, classes), docstrings e
      comentários passam para inglês, incluindo nomes de testes.
      **Exceção**: strings visíveis ao usuário (notificações, janela,
      mensagens de erro exibidas) continuam em português — atualizar a
      convenção no CLAUDE.md junto (hoje ela pede tudo em PT)
- [ ] Empacotar como `.deb` de verdade (hoje a distribuição é via
      install.sh + venv)
- [x] Aposentar o `ler.sh` (último fluxo bash): método D-Bus
      `ReadCurrentNote()` no daemon como alvo do Super+T (lê a nota mais
      recente via Player). O espelho `.txt` foi mantido de propósito,
      como export das notas em texto puro

## Detalhamento — SQLite, filtros, tags e favoritos (proposta v3)

### Por que sair dos .txt

Hoje cada nota é um arquivo `.txt` e a busca é substring em memória
(`Note.matches`). Funciona para dezenas de notas, mas não escala nem
comporta metadados: não há como marcar favoritos, agrupar por assunto, nem
buscar com ranking. SQLite resolve tudo isso num único arquivo local
(`~/.local/share/tomenotas/notes.db`), continua 100% offline e vem na
biblioteca padrão do Python (`sqlite3`) — zero dependências novas.

### Esquema proposto

```sql
CREATE TABLE notes (
    id         INTEGER PRIMARY KEY,
    created_at TEXT    NOT NULL,             -- ISO-8601
    text       TEXT    NOT NULL,
    favorite   INTEGER NOT NULL DEFAULT 0    -- 0/1
);

CREATE TABLE tags (
    id   INTEGER PRIMARY KEY,
    name TEXT UNIQUE COLLATE NOCASE          -- "compras" == "Compras"
);

CREATE TABLE note_tags (
    note_id INTEGER REFERENCES notes(id) ON DELETE CASCADE,
    tag_id  INTEGER REFERENCES tags(id)  ON DELETE CASCADE,
    PRIMARY KEY (note_id, tag_id)
);

-- Busca full-text (FTS5), sincronizada com notes via triggers
CREATE VIRTUAL TABLE notes_fts USING fts5(
    text, content='notes', content_rowid='id'
);
```

### Filtros na UI (combináveis entre si)

- **Texto**: busca full-text via FTS5 com prefixo (`palavra*`) e ranking
  `bm25` — substitui o substring atual e ordena por relevância.
- **Tags**: chips clicáveis acima da lista (clicar filtra; múltiplas tags =
  interseção). Adicionar/remover tag por nota com entry + autocomplete das
  tags existentes.
- **Favoritos**: estrela (toggle) em cada linha da lista; chip "★ Favoritos"
  filtra só marcadas.
- **Período**: filtro rápido por `created_at` (hoje / esta semana / este
  mês).

### Arquitetura e migração

- Novo módulo `notes_db.py` no núcleo, com o mesmo contrato do `NoteStore`
  atual (`save/list/delete/matches`) mais `set_favorite`, `add_tag`,
  `remove_tag`, `search(texto, tags, favoritos, periodo)` — tudo TDD com
  banco em memória (`:memory:`), mantendo o gate de 90%.
- **Migração automática na primeira execução**: importa os `.txt` de
  `notes/` (timestamp do nome → `created_at`), move os originais para
  `notes/backup-pre-sqlite/` em vez de apagar (sem perda).
- O banco vira a fonte da verdade. O script legado remanescente (`ler.sh`,
  Super+T) lê `.txt` — **decisão implementada**: cada nota mantém um
  espelho `.txt` em `notes/` (criado no save, removido no delete), e
  `.txt` criados por fora do daemon são importados na abertura seguinte;
  por isso a migração inicial importa os `.txt` existentes sem movê-los.
  (`gravar.sh` e `listar.sh` foram aposentados e removidos.)

### Migrations — evolução do esquema sem perda de dados

Toda instalação/atualização precisa conviver com um banco que pode já
existir de uma versão anterior. A estratégia:

- **Versão do esquema no próprio banco**: `PRAGMA user_version` (nativo do
  SQLite, sem tabela extra). Banco novo é criado já na versão mais
  recente; banco existente informa em que versão parou.
- **Migrations registradas no código** (`migrations.py` no núcleo): uma
  lista ordenada e numerada — `1: esquema inicial`, `2: <próxima
  alteração>`, ... **Cada alteração de estrutura do banco entra
  obrigatoriamente como uma nova migration**; migrations já publicadas são
  imutáveis (mudou de ideia = migration nova por cima, nunca editar a
  antiga).
- **Aplicação na inicialização do daemon** (não no install.sh — o daemon é
  o único escritor do banco): abre o `notes.db`, compara `user_version`
  com a versão alvo e aplica, em ordem, apenas as migrations que faltam.
  Cada migration roda numa transação: ou aplica inteira, ou nada muda.
- **Garantias contra perda de dados**:
  - backup automático do arquivo antes de migrar
    (`notes.db.bak-v<versão>-<data>`), mantendo os últimos N backups;
  - migrations só usam operações preservadoras (`ALTER TABLE ... ADD`,
    `CREATE TABLE`, copiar dados); remover/renomear coluna exige o padrão
    "criar tabela nova → copiar dados → trocar" — nunca `DROP` com dados
    sem cópia prévia;
  - falha no meio → rollback da transação e o daemon avisa o usuário e
    aborta a migração, deixando o banco intacto na versão anterior (o
    backup cobre até corrupção de arquivo);
  - o `uninstall.sh` continua preservando o banco por padrão (só
    `--purge-notes` o remove).
- **TDD das migrations**: para cada migration N, um teste monta um banco
  real na versão N-1 **com dados**, migra, e verifica que os dados
  continuam íntegros e a estrutura nova existe; mais testes de banco novo
  (criação direta na última versão), de idempotência (rodar duas vezes não
  muda nada) e do caminho de rollback.

### Critério de pronto

Buscar por texto retorna resultados rankeados; tags e favoritos criados na
UI persistem e filtram a lista; migração importa todas as notas existentes
sem perda; combinação de filtros (texto + tag + favorito) funciona;
**atualizar o programa com um banco de versão anterior aplica as migrations
pendentes automaticamente e nenhuma nota/tag/favorito se perde** (validado
por teste com banco populado de versão antiga).

## Plano — camadas físicas (Clean Architecture leve) (executado)

O pacote hoje é plano (`src/tomenotas/*.py`), mas a separação lógica já
existe: núcleo puro e testado, I/O injetável, cola GTK fina. Este plano
transforma a separação lógica em estrutura física **sem** a cerimônia
completa de Clean Architecture (nada de interactors/DTOs/repositórios
abstratos — duck typing + injeção já cumprem o papel de interfaces).

### Estrutura alvo

```
src/tomenotas/
├── domain/    # tipos e regras puras, zero I/O
│   ├── note.py      (Note, DbNote, preview)
│   ├── state.py     (State, ToggleAction, status/Pulsador)
│   ├── periodo.py   (periodo_desde)
│   └── errors.py    (TranscriptionError, PlayerError, RecorderError,
│                     MigrationError)
├── app/       # casos de uso (orquestram ports injetados)
│   └── core.py      (DaemonCore)
├── infra/     # adaptadores de I/O (subprocess, sqlite, fs, gsettings)
│   ├── recorder.py, transcriber.py, player.py, notify.py
│   ├── notes_db.py, migrations.py
│   └── shortcuts.py, config.py, logs.py
└── ui/        # GTK/AppIndicator/D-Bus (cola, fora da cobertura)
    ├── daemon.py, window.py, settings_page.py
```

Regra de dependência (de fora para dentro): `ui → app/infra/domain`,
`infra → domain`, `app → domain`, `domain → nada interno`. Corrige de
quebra a violação atual: `core.py` importa exceções e `preview` da
infraestrutura — na migração elas sobem para `domain/errors.py` e
`domain/note.py`.

### Etapas (cada uma entregável, suíte verde o tempo todo)

1. **domain/**: extrair os tipos puros e as exceções; ajustar imports do
   restante. É a etapa que desfaz a inversão de dependência do core.
2. **app/**: mover `DaemonCore`; após esta etapa `app` importa só
   `domain`.
3. **infra/**: mover os adaptadores + config/logs/migrations.
4. **ui/**: mover a cola (renomear `settings_window.py` →
   `settings_page.py`); atualizar o entry point
   (`tomenotas-daemon = tomenotas.ui.daemon:main`) e os `omit` de
   cobertura no pyproject; reinstalar via install.sh.
5. **Teste de arquitetura**: `tests/test_arquitetura.py` (AST, sem
   dependências novas) que falha se: `gi` for importado fora de `ui/`;
   `domain/` importar qualquer camada interna; `app/` importar `infra/`
   ou `ui/`; `infra/` importar `app/` ou `ui/`. A regra vira gate de
   teste, não disciplina.
6. **Docs**: reescrever a seção de arquitetura do CLAUDE.md e o README
   (estrutura de pastas e onde cada coisa nova deve entrar).

Sem shims de compatibilidade: os caminhos de módulo são internos (o único
consumidor externo é o entry point, atualizado na etapa 4).

**Critério de pronto:** mesma funcionalidade e mesmos testes passando
(cobertura ≥ 90% no núcleo), mais o teste de arquitetura no gate; nenhum
import cruzando camadas na direção proibida.

## Riscos e pontos em aberto

- **Hotkeys globais no Wayland/GNOME**: hoje a única forma confiável é via
  `gsettings custom-keybindings`, que é uma configuração do sistema, não do
  app. O portal `org.freedesktop.portal.GlobalShortcuts` é o caminho
  "nativo" e mais moderno para isso, mas o suporte no `xdg-desktop-portal-gnome`
  ainda está amadurecendo — vale reavaliar a cada versão do Ubuntu.
- **AppIndicator no Ubuntu atual**: usar a lib `AyatanaAppIndicator3`
  (não a `AppIndicator3` antiga da Canonical, que está sem manutenção) —
  confirmar disponibilidade via `gir1.2-ayatanaappindicator3-0.1`.
- **Ícones animados**: AppIndicator não anima ícones nativamente; o efeito
  de "pulsar" precisa ser simulado trocando o ícone em intervalos.

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
- [ ] Migrar armazenamento de notas para SQLite (busca full-text, tags,
      favoritos) — ver detalhamento na seção abaixo
- [ ] Exportar notas (Markdown, texto simples, ou até áudio re-sintetizado)
- [ ] Atalho para editar o texto da nota manualmente antes de "arquivar"
- [ ] Suporte a múltiplas vozes Piper (trocar pela UI)
- [ ] Avaliar `xdg-desktop-portal` GlobalShortcuts como alternativa nativa
      ao `gsettings custom-keybindings` (ver riscos abaixo)
- [ ] Empacotar como `.deb` de verdade (hoje a distribuição é via
      install.sh + venv)

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
- O banco vira a fonte da verdade. Os scripts legados (`listar.sh`,
  `ler.sh`) leem `.txt` — decidir na v3: aposentá-los de vez ou gerar um
  espelho `.txt` somente-leitura para compatibilidade.

### Critério de pronto

Buscar por texto retorna resultados rankeados; tags e favoritos criados na
UI persistem e filtram a lista; migração importa todas as notas existentes
sem perda; combinação de filtros (texto + tag + favorito) funciona.

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

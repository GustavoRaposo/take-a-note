# Tomenotas

Assistente pessoal simples para Ubuntu: grave notas de voz com um atalho de
teclado, transcreva automaticamente para texto (offline, sem IA/LLM) e ouça
qualquer nota depois via TTS em português.

Sem nuvem, sem API paga, sem conexão com modelos de linguagem — só STT e TTS
rodando localmente na sua máquina.

## Funcionalidades

- **Gravar**: aperta um atalho para começar a gravar, aperta de novo para
  parar. O áudio é transcrito e salvo como uma nota de texto.
- **Listar**: mostra todas as notas (mais recente primeiro) numa janela de
  seleção. A nota escolhida vira a "nota atual".
- **Ler**: lê em voz alta (TTS em português) a nota atual selecionada, ou a
  mais recente se nenhuma foi escolhida ainda.

Cada gravação gera um arquivo `.txt` próprio. O áudio bruto (`.wav`) é
temporário e apagado automaticamente depois da transcrição — só o texto fica
salvo.

## Tecnologias usadas

| Componente | Ferramenta |
|---|---|
| Gravação de áudio | `arecord` (ALSA) |
| Speech-to-Text | [whisper.cpp](https://github.com/ggerganov/whisper.cpp) |
| Text-to-Speech | [Piper](https://github.com/rhasspy/piper) (voz `pt_BR-faber-medium`) |
| Seleção de notas | `zenity` |
| Notificações | `notify-send` |
| Reprodução de áudio | `paplay` (PulseAudio/PipeWire) |
| Daemon / bandeja | Python 3 + PyGObject (GTK3, `AyatanaAppIndicator3`) |
| Atalho → daemon | D-Bus (`com.tomenotas.Daemon`, via `gdbus`) |

## Requisitos

- Ubuntu com GNOME (testado em Wayland)
- ~2-4 GB livres para o modelo whisper `medium` + Piper
- Microfone funcional

## Instalação

Coloque todos os arquivos do projeto na mesma pasta e rode:

```bash
chmod +x install.sh
./install.sh
```

O instalador:

1. Instala dependências via `apt`: `zenity`, `alsa-utils`, `libnotify-bin`,
   `pulseaudio-utils`, ferramentas de build.
2. Clona e compila o `whisper.cpp`, baixando o modelo escolhido (padrão:
   `medium`).
3. Baixa o binário do Piper e a voz `pt_BR-faber-medium`.
4. Copia os scripts bash + `tomenotas-hotkey-record` para `~/bin`, instala o
   daemon como pacote Python num venv (`~/.local/share/tomenotas/venv`) e
   grava os caminhos do whisper em `~/.config/tomenotas/config.json`.
5. Configura os atalhos de teclado no GNOME via `gsettings`:
   - **Super+R** — gravar/parar (via daemon: só funciona com ele rodando)
   - **Super+L** — listar notas
   - **Super+T** — ler nota atual

### Opções do instalador

```bash
./install.sh --skip-whisper       # não instala/compila o whisper.cpp
./install.sh --skip-piper         # não instala o Piper
./install.sh --skip-shortcuts     # não configura atalhos automaticamente
./install.sh --model-size small   # tiny | base | small | medium | large
```

## Uso

0. O daemon inicia sozinho no login (autostart). Também dá para abrir pelo
   **menu de aplicativos** (procure "Tomenotas") — o lançador religa o
   daemon se preciso e abre a janela de notas. Manualmente:
   ```bash
   ~/bin/tomenotas-daemon &
   ```
   O ícone reflete o estado: neutro = ocioso, **badge vermelho pulsando** =
   gravando, **badge âmbar pulsando** = transcrevendo.
1. **Super+R** → fala → **Super+R** de novo → uma notificação confirma a nota
   criada. O atalho só funciona enquanto o daemon estiver rodando — feche
   pelo menu da bandeja ("Sair") para desativá-lo.
2. Menu da bandeja → **Abrir** → janela com todas as notas: busca por
   texto (full-text, por prefixo, ordenada por relevância), chips de
   **tags** (várias = interseção), filtro **★ Favoritos** e por período
   (hoje/7/30 dias). Por nota: ★ favorita, 🏷 gerencia tags (ou cria
   novas), ▶ ouve (vira ⏸ enquanto toca) e 🗑 apaga.
3. Menu da bandeja → **Configurações** → troque os 3 atalhos: clique no
   campo, pressione a nova combinação e pronto (efeito imediato; avisa se a
   combinação já estiver em uso por outro app).
4. **Super+L** → abre a mesma janela de notas (só funciona com o daemon
   rodando). Atenção: em muitos GNOME, Super+L já bloqueia a tela — se for
   o seu caso, troque a combinação em Configurações.
5. **Super+T** → ouve a nota selecionada.

Se algum atalho já estiver em uso por outro programa, ajuste em
**Configurações → Teclado → Atalhos personalizados**.

## Onde ficam os arquivos

```
~/bin/gravar.sh
~/bin/listar.sh
~/bin/ler.sh
~/bin/tomenotas-daemon          # daemon (link para o venv abaixo)
~/bin/tomenotas-hotkey-record   # cliente D-Bus chamado pelo Super+R
~/bin/tomenotas-hotkey-window   # cliente D-Bus chamado pelo Super+L
~/bin/tomenotas-open            # lançador: religa o daemon e abre a janela
~/.local/share/applications/tomenotas.desktop  # entrada no menu de apps
~/.config/tomenotas/config.json # caminhos do whisper/piper (lidos pelo daemon)
~/.config/autostart/tomenotas.desktop  # inicia o daemon no login
~/.local/share/tomenotas/
├── venv/               # pacote Python do daemon
├── icons/              # ícones da bandeja (estado)
├── daemon.log          # log do daemon (rotativo)
├── notes.db            # banco de notas (fonte da verdade; backups .bak-*)
├── notes/              # espelho .txt das notas (usado por ler.sh/listar.sh)
├── current_note        # ponteiro para a nota selecionada em listar.sh
└── recording.pid        # usado só pelo gravar.sh legado, não pelo daemon
~/whisper.cpp/           # binário e modelo do whisper.cpp
~/piper/                 # binário e voz do Piper
```

## Apagar notas e áudios

Os áudios (`.wav`) já são apagados automaticamente logo após cada
transcrição. As notas de texto **não** são apagadas sozinhas.

```bash
# apagar uma nota específica
rm ~/.local/share/tomenotas/notes/2026-07-22_15-00-38.txt

# apagar todas as notas
rm ~/.local/share/tomenotas/notes/*.txt

# apagar notas com mais de 30 dias
find ~/.local/share/tomenotas/notes/ -name "*.txt" -mtime +30 -delete
```

## Desinstalação

```bash
./uninstall.sh                        # remove scripts e atalhos, mantém notas e dependências
./uninstall.sh --purge-notes          # também apaga suas notas
./uninstall.sh --purge-deps           # também remove whisper.cpp e Piper
./uninstall.sh --purge-notes --purge-deps   # remove tudo
```

## Desenvolvimento

O daemon é um pacote Python (`src/tomenotas/`) desenvolvido com TDD: a
lógica (gravação, transcrição, notas, máquina de estados) é pura e coberta
por testes, com gate de 90% de cobertura (`pytest` falha abaixo disso). A
camada de cola GTK/AppIndicator/D-Bus (`daemon.py`) é fina, fica fora da
métrica e é validada manualmente.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest          # roda a suíte com relatório de cobertura
```

## Solução de problemas

**Primeiro passo**: veja o log do daemon —
```bash
tail -50 ~/.local/share/tomenotas/daemon.log
```

**`Rofi on wayland requires support for the layer shell protocol`**
O GNOME não suporta o protocolo `layer-shell` que o rofi usa no Wayland. O
projeto já usa `zenity` em vez de `rofi` para evitar esse problema. Se você
ainda tiver o rofi instalado e não for mais usá-lo:
```bash
sudo apt remove --purge rofi
sudo apt autoremove
```

**`paplay: comando não encontrado`**
Falta o pacote com utilitários do PulseAudio/PipeWire:
```bash
sudo apt install -y pulseaudio-utils
```

**Binário do whisper.cpp não encontrado**
Dependendo da versão, o binário compilado se chama `whisper-cli` ou `main`.
Verifique em `~/whisper.cpp/build/bin/` e ajuste a variável `WHISPER_BIN` em
`~/bin/gravar.sh` se necessário.

**Nenhum som sai ao gravar/testar o microfone**
Teste a captura isoladamente antes de depender dos atalhos:
```bash
arecord -f cd -t wav teste.wav
# fale algo, Ctrl+C para parar, depois:
aplay teste.wav
```

# Tomenotas

![Python](https://img.shields.io/badge/Python-3.12-blue)
![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04-orange)
![License](https://img.shields.io/badge/license-MIT-green)
![Coverage](https://img.shields.io/badge/coverage-90%25-brightgreen)

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

1. Instala dependências via `apt`: `alsa-utils`, `libnotify-bin`,
   `pulseaudio-utils`, ferramentas de build.
2. Clona e compila o `whisper.cpp` (só o binário — o **modelo** é baixado
   pelo próprio app no primeiro uso, em Configurações).
3. Baixa o binário do Piper (a **voz** também é baixada pelo app no
   primeiro uso).
4. Copia os scripts bash + `tomenotas-hotkey-record` para `~/tomenotas`,
   instala o daemon como pacote Python num venv
   (`~/.local/share/tomenotas/venv`) e grava os caminhos do whisper em
   `~/.config/tomenotas/config.json`.
5. Configura os atalhos de teclado no GNOME via `gsettings`:
   - **Super+R** — gravar/parar (via daemon: só funciona com ele rodando)
   - **Super+Y** — listar notas
   - **Super+T** — ler nota atual

### Opções do instalador

```bash
./install.sh --skip-whisper       # não instala/compila o whisper.cpp
./install.sh --skip-piper         # não instala o Piper
./install.sh --skip-shortcuts     # não configura atalhos automaticamente
./install.sh --skip-apt           # não roda apt (dependências já instaladas)
```

## Uso

0. O daemon inicia sozinho no login (autostart). Também dá para abrir pelo
   **menu de aplicativos** (procure "Tomenotas") — o lançador religa o
   daemon se preciso e abre a janela de notas. Manualmente:
   ```bash
   ~/tomenotas/tomenotas-daemon &
   ```
   O ícone reflete o estado: neutro = ocioso, **badge vermelho pulsando** =
   gravando, **badge âmbar pulsando** = transcrevendo.
1. **Super+R** → fala → **Super+R** de novo → uma notificação confirma a nota
   criada. O atalho só funciona enquanto o daemon estiver rodando — feche
   pelo menu da bandeja ("Sair") para desativá-lo.
2. Menu da bandeja → **Abrir** → janela com sidebar de seções:
   - **Notas**: busca por texto (full-text, por prefixo, ordenada por
     relevância), dropdown de **tags** (lista as existentes no banco),
     filtro **★ Favoritos** e por período (hoje/7/30 dias). Por nota:
     ★ favorita, 🏷 gerencia tags, ▶ ouve (vira ⏸ enquanto toca) e
     🗑 apaga. **Clicar na nota** abre o detalhe: conteúdo completo
     editável, com ★/🏷/▶/🗑 — "Salvar" grava a edição e volta pra
     lista (a seta ← volta sem salvar).
   - **Tags**: criar, listar (com nº de notas), renomear (unindo com a
     existente se o nome coincidir) e apagar tags — apagar uma tag nunca
     apaga as notas.
   - **Configurações**: troque os 3 atalhos — clique no campo, pressione a
     nova combinação e pronto (efeito imediato; avisa se a combinação já
     estiver em uso por outro app).
4. **Super+Y** → abre a mesma janela de notas (só funciona com o daemon
   rodando). (O padrão era Super+L, trocado porque em muitos GNOME essa
   combinação já bloqueia a tela.)
5. **Super+T** → ouve a nota mais recente em voz alta (via daemon —
   só funciona com ele rodando).

Se algum atalho já estiver em uso por outro programa, ajuste em
**Configurações → Teclado → Atalhos personalizados**.

## Onde ficam os arquivos

```
~/tomenotas/tomenotas-daemon          # daemon (link para o venv abaixo)
~/tomenotas/tomenotas-hotkey-record   # cliente D-Bus chamado pelo Super+R
~/tomenotas/tomenotas-hotkey-window   # cliente D-Bus chamado pelo Super+Y
~/tomenotas/tomenotas-hotkey-read     # cliente D-Bus chamado pelo Super+T
~/tomenotas/tomenotas-open            # lançador: religa o daemon e abre a janela
~/.local/share/applications/tomenotas.desktop  # entrada no menu de apps
~/.config/tomenotas/config.json # caminhos do whisper/piper (lidos pelo daemon)
~/.config/autostart/tomenotas.desktop  # inicia o daemon no login
~/.local/share/tomenotas/
├── venv/               # pacote Python do daemon
├── icons/              # ícones da bandeja (estado)
├── daemon.log          # log do daemon (rotativo)
├── notes.db            # banco de notas (fonte da verdade; backups .bak-*)
└── notes/              # espelho .txt das notas (export em texto puro)
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

O daemon é um pacote Python (`src/tomenotas/`) desenvolvido com TDD e
organizado em camadas (Clean Architecture leve): `domain/` (regras puras),
`app/` (casos de uso), `infra/` (adaptadores de I/O) e `ui/` (cola
GTK/D-Bus, fina, fora da métrica de cobertura). O gate de cobertura é 90%
(`pytest` falha abaixo disso) e a regra de dependência entre camadas é
imposta por `tests/test_architecture.py`.

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
Verifique em `~/whisper.cpp/build/bin/` e ajuste `whisper_bin` em
`~/.config/tomenotas/config.json` se necessário.

**Nenhum som sai ao gravar/testar o microfone**
Teste a captura isoladamente antes de depender dos atalhos:
```bash
arecord -f cd -t wav teste.wav
# fale algo, Ctrl+C para parar, depois:
aplay teste.wav
```

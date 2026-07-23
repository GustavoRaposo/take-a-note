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

| Componente | Ferramenta | Versão |
|---|---|---|
| Gravação de áudio | `arecord` (ALSA, pacote `alsa-utils`) | a do Ubuntu |
| Speech-to-Text | [whisper.cpp](https://github.com/ggerganov/whisper.cpp) | **v1.9.1** (pinada; binário estático embutido no .deb) |
| Modelos de STT | ggml `tiny`/`base`/`small`/`medium`/`large-v3` | baixados pelo app no 1º uso (75 MB–2.9 GB) |
| Text-to-Speech | [Piper](https://github.com/rhasspy/piper) | **2023.11.14-2** (pinada; embutido no .deb) |
| Voz padrão | `pt_BR-faber-medium` (~60 MB) | baixada pelo app no 1º uso |
| Notificações | `notify-send` (pacote `libnotify-bin`) | a do Ubuntu |
| Reprodução de áudio | `paplay` (pacote `pulseaudio-utils`) | a do Ubuntu |
| Daemon / bandeja | Python + PyGObject (GTK3, `AyatanaAppIndicator3` 0.1) | **Python ≥ 3.10** |
| Atalho → daemon | D-Bus (`com.tomenotas.Daemon`, via `gdbus`) | — |

As versões do whisper.cpp e do Piper são **pinadas no build do pacote**
(`packaging/build-deb.sh`) — todo .deb gerado usa exatamente essas; as
demais dependências vêm do apt do próprio Ubuntu, declaradas no pacote.

## Requisitos

- Ubuntu 24.04+ com GNOME (testado em Wayland)
- Python ≥ 3.10 (o do Ubuntu 24.04 é 3.12 — resolvido pelo apt)
- Espaço em disco: ~60 MB do pacote + o modelo whisper que você escolher
  no primeiro uso (75 MB a 2.9 GB) + ~60 MB da voz
- Microfone funcional

## Instalação

A instalação é via pacote `.deb` — um único caminho, sem compilar nada na
sua máquina:

```bash
sudo apt install ./tomenotas_0.2.0_amd64.deb
```

O `apt` resolve as dependências declaradas no pacote. Na primeira vez que
você abrir o app (menu de aplicativos → **Tomenotas**):

1. O daemon **registra sozinho os atalhos de teclado** no GNOME:
   - **Super+R** — gravar/parar (só funciona com o daemon rodando)
   - **Super+Y** — listar notas
   - **Super+T** — ler nota atual
2. A janela abre em **Configurações** pedindo o download do **modelo de
   transcrição** (escolha o tamanho — `medium` recomendado) e da **voz**
   — com barra de progresso; é a única hora em que algo é baixado.

### Gerando o pacote

Se você clonou o repositório em vez de baixar um `.deb` pronto:

```bash
./packaging/build-deb.sh    # requer git, cmake, build-essential e wget
sudo apt install ./dist/tomenotas_0.2.0_amd64.deb
```

O script compila um `whisper-cli` estático (whisper.cpp v1.9.1, sem
otimizações da CPU local — o pacote roda em qualquer amd64), baixa o
Piper 2023.11.14-2 e embute os dois no pacote. As ferramentas de build
são necessárias só nessa máquina, nunca na de quem instala o `.deb`.

## Uso

0. O daemon inicia sozinho no login (autostart). Também dá para abrir pelo
   **menu de aplicativos** (procure "Tomenotas") — o lançador religa o
   daemon se preciso e abre a janela de notas. Manualmente:
   ```bash
   tomenotas-daemon &
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

**Do pacote (removidos pelo `apt remove`):**
```
/usr/bin/tomenotas-daemon             # daemon
/usr/bin/tomenotas-hotkey-record      # cliente D-Bus chamado pelo Super+R
/usr/bin/tomenotas-hotkey-window      # cliente D-Bus chamado pelo Super+Y
/usr/bin/tomenotas-hotkey-read        # cliente D-Bus chamado pelo Super+T
/usr/bin/tomenotas-open               # lançador: religa o daemon e abre a janela
/usr/lib/tomenotas/whisper-cli        # whisper.cpp v1.9.1 (estático)
/usr/lib/tomenotas/piper/             # Piper 2023.11.14-2 (+ espeak-ng-data)
/usr/lib/python3/dist-packages/tomenotas/  # o pacote Python
/usr/share/tomenotas/icons/           # ícones da bandeja (estado)
/usr/share/applications/tomenotas.desktop  # entrada no menu de apps
/etc/xdg/autostart/tomenotas-autostart.desktop  # inicia o daemon no login
```

**Seus dados (nunca tocados pelo pacote):**
```
~/.config/tomenotas/config.json  # criado/atualizado pelo app (modelo, voz)
~/.local/share/tomenotas/
├── models/             # modelo whisper + voz Piper (baixados no 1º uso)
├── daemon.log          # log do daemon (rotativo)
├── notes.db            # banco de notas (fonte da verdade; backups .bak-*)
└── notes/              # espelho .txt das notas (export em texto puro)
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
sudo apt remove tomenotas
```

Suas notas, modelos e configuração **ficam** (o pacote não toca a sua
home). Para apagá-los também:

```bash
rm -rf ~/.local/share/tomenotas ~/.config/tomenotas
```

Os atalhos de teclado registrados no gsettings também permanecem (são
configuração por usuário); uma reinstalação os reaproveita, e apertar
os atalhos sem o app instalado não faz nada.

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

Para exercitar o fluxo real de teclado durante o desenvolvimento existe o
`install.sh` (instala via venv na home: scripts em `~/tomenotas`, daemon
em `~/.local/share/tomenotas/venv`) e o `uninstall.sh` que o reverte —
**rota exclusiva de desenvolvimento**: não a use com o `.deb` instalado
(o install.sh detecta e aborta; remova um antes de instalar o outro).

## Solução de problemas

**Primeiro passo**: veja o log do daemon —
```bash
tail -50 ~/.local/share/tomenotas/daemon.log
```

**`paplay: comando não encontrado`**
Não deve acontecer com o `.deb` (o `pulseaudio-utils` é dependência
declarada), mas se ocorrer:
```bash
sudo apt install -y pulseaudio-utils
```

**Binário do whisper.cpp não encontrado**
Com o `.deb`, o binário fica em `/usr/lib/tomenotas/whisper-cli` —
reinstale o pacote se ele sumiu. Na rota de desenvolvimento (install.sh),
verifique `~/whisper.cpp/build/bin/` e ajuste `whisper_bin` em
`~/.config/tomenotas/config.json` se necessário.

**Nenhum som sai ao gravar/testar o microfone**
Teste a captura isoladamente antes de depender dos atalhos:
```bash
arecord -f cd -t wav teste.wav
# fale algo, Ctrl+C para parar, depois:
aplay teste.wav
```

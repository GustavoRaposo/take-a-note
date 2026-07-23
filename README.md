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
4. Copia os scripts para `~/bin` e ajusta os caminhos automaticamente.
5. Configura os atalhos de teclado no GNOME via `gsettings`:
   - **Super+R** — gravar/parar
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

1. **Super+R** → fala → **Super+R** de novo → uma notificação confirma a nota
   criada.
2. **Super+L** → escolhe uma nota na lista.
3. **Super+T** → ouve a nota selecionada.

Se algum atalho já estiver em uso por outro programa, ajuste em
**Configurações → Teclado → Atalhos personalizados**.

## Onde ficam os arquivos

```
~/bin/gravar.sh
~/bin/listar.sh
~/bin/ler.sh
~/.local/share/tomenotas/
├── notes/              # suas notas de texto (.txt)
├── current_note        # ponteiro para a nota selecionada em listar.sh
└── recording.pid        # existe só enquanto uma gravação está em andamento
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

## Solução de problemas

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

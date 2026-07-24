# Treino do wake word "Tomenotas"

Kit para treinar o modelo de detecção de voz que o Tomenotas usa para
acionar a gravação ao ouvir "Tomenotas" / "tome notas". Usa o
[openWakeWord](https://github.com/dscripka/openWakeWord) e roda **fora do
app** (é um treino de ML), na sua GPU. O `.onnx` resultante é instalado
onde o daemon procura (`~/.local/share/tomenotas/models/tomenotas-ww.onnx`).

## Requisitos

- **GPU NVIDIA** com driver (uma GTX 1650 4GB dá conta — o config já vem
  com batches reduzidos para caber em 4GB).
- Linux, `git`, `wget`, `ffmpeg`, e **`espeak-ng`** (o gerador de amostras
  usa: `sudo apt install espeak-ng`).
- **~30 GB livres** e **algumas horas** (o gargalo é gerar as amostras e
  baixar os dados negativos, não o treino em si).
- **Python 3.10–3.12** para o treino. O ecossistema de ML (torch etc.)
  ainda **não** tem wheels para Python 3.13/3.14 — se o seu `python3` for
  3.13+ (como no Ubuntu mais novo), o `setup.sh` obtém um Python 3.11
  standalone automaticamente via [`uv`](https://docs.astral.sh/uv/)
  (sem sudo). O TensorFlow/tflite e o `speexdsp-ns` são pulados de
  propósito: só servem para a conversão `.tflite` e supressão de ruído,
  que não usamos (runtime só-ONNX).

## Passo a passo

```bash
cd training
chmod +x setup.sh download_data.sh train.sh

./setup.sh            # venv + PyTorch(CUDA) + openWakeWord + piper-sample-generator
./download_data.sh    # RIRs + ruído (AudioSet) + features negativas (~2000h)  [pesado]
./train.sh            # gera → aumenta → treina → exporta e instala o .onnx
```

Cada script aceita um `WORKDIR` opcional (padrão
`~/tomenotas-wakeword-training`) — passe o mesmo aos três se mudar.

Ao terminar, **reinicie o Tomenotas** e ligue o wake word em
**Configurações → Wake word**.

## Como funciona (resumo)

1. **Positivos**: o `piper-sample-generator` sintetiza dezenas de milhares
   de "Tomenotas"/"tome notas" com vozes/prosódias variadas.
2. **Negativos**: ~2000h de *features* pré-computadas (ACAV100M) +
   augmentation com RIRs (reverberação) e ruído de fundo (AudioSet).
3. **Treino**: um classificador pequeno (DNN) sobre os embeddings do
   openWakeWord; exporta `.onnx` (+ `.tflite`).

Ajuste em `tomenotas.yml`: `n_samples` (mais = melhor, mais lento),
`tts_batch_size` (suba se tiver mais VRAM), `target_phrase`.

## ⚠️ Sobre o sotaque (importante)

O gerador de amostras usa um modelo **em inglês** (LibriTTS). Ele pronuncia
"Tomenotas"/"tome notas" com fonética inglesa, que **não é idêntica** ao
português. Na prática costuma funcionar (a palavra é próxima), mas se a
detecção ficar fraca para a sua voz:

- **Grave algumas amostras suas** dizendo a palavra e adicione como
  positivos extras (o openWakeWord aceita clips reais em `positive/` —
  ver o notebook `notebooks/automatic_model_training.ipynb` do repo). Isso
  melhora muito a detecção do **seu** timbre/sotaque.
- Ou aumente `n_samples` e o `augmentation_rounds` para mais robustez.

Depois de instalado, ajuste a **Sensibilidade** em Configurações: limiar
maior = menos disparos falsos (mas exige falar mais claro).

## Privacidade

Nada aqui é enviado para lugar nenhum em produção: o modelo roda **100%
offline** no seu computador. O treino baixa datasets públicos só para
gerar o modelo — depois disso, o app não precisa de rede para o wake word.

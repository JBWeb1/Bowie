#!/bin/sh
# Put the score under the rendered film: the music ducks whenever Bowie talks, then the mix is set to -15 LUFS.
# Needs: fluidsynth + the FluidR3 GM soundfont (apt install fluidsynth fluid-soundfont-gm), pip install mido.
set -e
python3 compose.py
ffmpeg -y -i Bowers-The-Interview.mp4 -i assets/music/score-raw.wav -filter_complex \
 "[1:a]atrim=0:446.63,asetpts=N/SR/TB,afade=t=in:st=0:d=1.5,afade=t=out:st=443.0:d=3.6,volume=0.8,aresample=48000[m];\
[0:a]aresample=48000,asplit=2[v][key];[m][key]sidechaincompress=threshold=0.03:ratio=4:attack=15:release=450:makeup=1[duck];\
[v][duck]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-15:TP=-1.5:LRA=11[a]" \
 -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k -ar 48000 -movflags +faststart Bowers-The-Interview-music.mp4

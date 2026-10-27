# "The Interview": the Bowers film, made with HyperFrames

Bowie interviews for the job "Your AI" on the day before Sam's launch. Every question is the next real job, done in the real app.
STORYLINES.md has the three pitches; SPEC.md is the brief in numbers; REVIEW.md is the delivery note.

Rebuild (needs Node 22+, ffmpeg, `npm i -g hyperframes`, `pip install "bowers[voice]"` and `bowers voices install`):

```bash
python shoot.py && python shoot_post.py && python shoot_hover.py && python shoot_photo.py   # real screens at 2x -> assets/screens
python narrate.py ~/.docks/voices/kokoro                                                      # Bowie's lines -> assets/voice, timings.json
python build.py                                                                               # index.html + compositions/*.html
hyperframes check && hyperframes preview                                                      # look and edit
hyperframes render -o Bowers-The-Interview.mp4
./mix.sh                                                                                       # the score, ducked under the voice
```

The words are in script.json; the shots (screens, camera, cursor, Bowie's poses) are in shots.py.
The capture scripts expect a Lemon Lane demo project next to this folder (lemon-lane/ with site/index.html) and demo-bad/index.html.

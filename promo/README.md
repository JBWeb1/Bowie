# The Bowers promo, starring Bowie

The source of the ~10-minute promo film. Everything is made on your computer: real screenshots of the app,
Bowie's narration with the offline Kokoro voice, an original synthesized score, and frame-by-frame rendering.

```bash
pip install -e ".[voice,browser]" && bowers voices install   # Bowie's voice
ln -s ../docks/web/assets assets                               # stickers and art used by the scenes
python promo/shoot.py     # 1. screenshots of every page -> promo/shots/ (dark and light)
python promo/voice.py     # 2. narration per scene + caption timings -> promo/audio/, timings.json (voice: am_puck)
python promo/render.py    # 3. each scene, frame by frame, with its narration -> promo/scenes/
python promo/final.py     # 4. title + credits cards, join, music ducked under the voice -> Bowers-Promo-Starring-Bowie.mp4
```

Edit the words in `script.json` (each scene's title, subtitle and narration) and the on-screen points in `render.py`.
Re-voice one scene with `python promo/voice.py am_puck 13-integrations`, then re-render it with `python promo/render.py 13-integrations`.
Needs ffmpeg and Chromium for Playwright.

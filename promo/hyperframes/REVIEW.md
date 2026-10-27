# REVIEW: "The Interview"

## Creative calls
- Storyline: A + C as asked. Sam (seen only through texts) interviews Bowie the day before launch; each interview question is the next
  real job of the day, done in the real app. The wall clock carries the day from 8:02 am to midnight. Not built: B "Inside the Badge".
- 7 min 27 s (447 s), 1920×1080, 30 fps, 15 chapters. Content was added instead of holds to get near the 8 minutes asked: the developer,
  organising and launch-post chapters.
- Every product screen is a real Bowers capture at 2× (the Lemon Lane site, chat, Motion, Care, Labs, Aether, Knowledge Graph, Settings,
  Integrations, Forge, Library, Explore). The social reel inside the phone is a real HyperFrames render; the end-card code panel is the
  film's own source. No invented results: no fake scores, no fake generated video, no fake deploy URL. Where a feature needs a key
  (LTX video, OpenAI images), the film shows the real screen that says so.
- Bowie's voice: Kokoro am_puck, offline. Sound: bundled effects only, each tied to an action on screen (click, notification, pop,
  whoosh in two takes, chime, sparkle, one bass impact on the mark).
- Dropped from the storyline: the tiny tie (Bowie's poses are 3/4 views, so it never sat right on the chest).

## Measured vs looked at
- `hyperframes check`: 0 errors. Kept warnings: duplicate_media_discovery_risk (the same screen is both the laptop's picture and the
  full-frame shot, on purpose: it makes the zoom-through seamless); nested_media_start_basis_ambiguous (the reel's start is local to
  its chapter, as intended); phone-clock contrast at moments when the full-screen app covers the phone (false positives).
- Snapshots of every chapter start and middle, every seam, the phone sheet, and the key beats were looked at; fixes made from them:
  the camera opening inside the laptop (fromTo immediate render), a whip screen bleeding in from frame 0, Bowie covering the question,
  the cursor loitering, the long-list gag over the phone, the installer tile wrapping, Bowie covering the end-card mark.
- Sound was measured (levels, placement), not heard.

## Bugs the film found in Bowers (fixed and pushed)
- Math Lab couldn't factor an equation; plots now frame their roots and mark where they cross zero.
- Chat didn't render Markdown quotes.
- My first promo said Forge makes images; it is the coding workspace. This film shows Motion's photo mode instead.

## Weakest shot, and with more time
- The Labs and Agents passes are camera moves over grids of cards; with more time each would isolate one card and let it act.
- No music bed: no music source here (no HeyGen sign-in, MusicGen can't be downloaded). To add one: `heygen auth login --oauth`, then
  `npx hyperframes media-use resolve --type bgm --intent "warm upbeat acoustic, 100 bpm"`, and place it at 0.14 volume under the voice.
- Bowie is played by 384 px sticker art; a rigged character (separate eyes and mouth) would let him lip-sync.

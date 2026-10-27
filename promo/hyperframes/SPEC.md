# SPEC: "The Interview" (A Day With Bowie × Bowie's Job Interview)

GOAL: the viewer remembers "Bowie doesn't just answer, he does the job", and wants to download Bowers.
OUTPUT: HyperFrames, 1920×1080, 30 fps.
TIME: ≈ 7.5 min (the narration is the clock: assets/voice/*.wav, timings.json). 14 chapters, one sub-composition each.

STORY: Sam (seen only through texts on a phone) runs Lemon Lane and launches tomorrow. Bowie interviews for "Your AI".
Every interview question is the next job of Sam's day, done for real in Bowers. The wall clock carries the day from 8:02 am to midnight.

LOOK
- Home stage, the office: wall #2E6B66, wainscot panels 160 px wide with 2 px seams #285F5A, dado rail at y 600 (#244F4B, 10 px),
  noise grain 5 %. Window x 140–560, y 90–420, cream frame #F2E8D8 18 px, sky set by the hour (dawn #CFE8F2→#FFF1D2,
  noon #9ED3F0→#E4F4FB, afternoon #A9D2EA→#FCE7C4, evening #FF9A62→#C75B39, night #13253A→#0B1622 with a moon).
  Wall clock centred (1640, 230), r 120, face #F7EFE2, rim #1F1D1B 10 px, hands ink, second hand #FF6B2C.
  Desk: oak top from y 760, #C08A55→#9A6A3C, front edge 6 px #DDA772; contact shadows 0.35 opacity, 18 px blur.
  Props: Sam's laptop (graphite #2B2D31, the real Bowers UI on its screen), Sam's phone (graphite #1C1C1E, screen #F5F5F7,
  grey bubbles #E5E5EA, ink #111, Inter 34 px), a brass desk lamp #C99A4B (warm cone only at night), Bowie's résumé (paper #FBF7EE).
- The product: real Bowers screens captured at 2× (3200×1800), shown full-bleed 1920×1080; punch-ins 1.25–1.9× on the part in use.
  Never a small window floating on a void, never tilted.
- Type: Inter 900. Questions 104 px (9.6 % of height), tracking −3 px, cream #F7EFE2 on the wall, one accent word #FF6B2C.
  Phone text 34 px. Code panel JetBrains Mono 28 px.
- Accent #FF6B2C is rationed: Bowie himself, the accent word of each question, the payoff, the end card.

OBJECTS: wall clock (hands, ticks, rim), window (frame, sill, sky), oak desk (top, edge, shadow), laptop (lid, bezel, hinge, base),
phone (bezel, notch, bubbles), résumé (paper, heading, lines), lamp (base, arm, shade, cone), chair back (leather, piping).

MOTION
- Arrivals expo.out 0.5–0.7 s; camera power2.inOut 0.6–0.9 s; zoom-throughs power3.in 0.7 s; exits power3.in 0.25 s.
- Bowie is a character: a pose change is anticipation (0.08 s, scaleY 0.9) → stretch (1.08/0.94) → settle (0.25 s, elastic 1, 0.5).
  Idle breath 2 % at 0.35 Hz is acting. He enters from frame edges, never fades in.
- Titles land per word (blur 8 → 0, 0.14 s, 0.08 s apart), then stay dead still; exit with a 0.2 s blur-out.
- Cursor: 64 px (6 % of height), moves 0.55 s power2.inOut, the click is 0.06 s down, 0.12 s up, with a click on the same frame.

TRANSITIONS (5 kinds, each with a cause)
1. Zoom into the laptop screen: office → product (the screen's own image becomes the frame).
2. Pull back out of the laptop: product → office.
3. Whip between two screens: 0.25 s, 18 px horizontal blur peak.
4. Clock carry: each chapter opens on the office with the clock hands sweeping to the new hour (hard cut, the clock leads).
5. Colour flood: the lamp goes off and the room floods to night; at the end, night floods to the warm end card.

SOUND: Bowie's voice (Kokoro am_puck, offline) is the clock. Bundled effects only, each with a cause on screen: click (cursor clicks),
notification (a text arrives), pop (Bowie or a helper springs in), whoosh (zoom-throughs, whips; three takes rotated), chime (a job done),
sparkle (hired), impact-bass-1 (the end-card mark). No music source is available here (no HeyGen sign-in, MusicGen can't be downloaded),
so the film has no music bed; how to add one is in REVIEW.md.

BANNED: dark void with small floating UI; glow, bloom, particles, lens flares; purple/blue gradients, glass cards; cream-paper-serif look;
every element fading and sliding up; text moving while read; corner labels, HUD decoration; three cards in a row; title over a dimmed
screenshot; the logo docked in a corner; invented UI or invented results (no fake scores, no fake generated video, no fake deploy URL);
the same whoosh on every cut.

QA: frame 0 (phone with 8:02 and the first text, never empty); each chapter's first frame (clock + question); each zoom-through midpoint;
c02 the rejected page and the real page; c03 the reel playing in the phone; c06 the plot with x = 2 and x = 3; c12 the lamp-off night;
the end card at its last second (mark, wordmark, button).

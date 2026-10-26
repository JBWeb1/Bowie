---
description: Turn a long video into short highlight clips with captions
argument-hint: "VIDEO_PATH_OR_URL [what to look for]"
---
Turn this long video into short highlight clips: $ARGUMENTS (inspired by AutoClip and OpenMontage).
Use ffmpeg (install it if missing) and transcribe with whisper if it is available. Find the 3 to 6 most engaging moments, cut 15 to 60 second vertical 9:16 clips with burned-in captions, and save them under assets/clips. Write assets/clips/clips.md with each clip's title, timestamps and a suggested post caption.

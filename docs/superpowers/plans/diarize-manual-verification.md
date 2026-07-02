# Diarize — manual quality verification (REQUIRED before shipping)

Automated tests prove the clock/plumbing; only this proves pyannote separates real
voices. Do this once on real hardware before considering the feature done.

1. `pip install -e '.[diarize]'`
2. Ensure a HF token is available (accept the two pyannote licenses; `HF_TOKEN` or first-run prompt).
3. Record a real 2-person conversation **with natural pauses** (~2–3 min):
   `podscribe record <pod>` → talk, alternating speakers, leave a few silent gaps → Ctrl+C.
4. `podscribe diarize <pod> latest` → note the reported speaker count.
5. `podscribe show <pod> latest` and read the `.diarized.md`:
   - [ ] Speaker labels roughly track who is actually talking (not random).
   - [ ] Speaker count ≈ number of real people (±1 acceptable).
   - [ ] Labels don't obviously drift/flip in the back half (the v1 failure mode).
6. If labels are random or drift in the back half → the clock fix regressed; STOP and investigate
   `AudioCapture` continuous write + `audio_layout` before shipping.

# Roadmap

Deferred features tracked from the 2026-07 meetily competitive review. Not yet
scheduled; captured so they are not lost.

## Capture
- **System audio capture** (hear the far side of Zoom/Teams/Meet calls).
  - Windows: native WASAPI loopback (no user setup).
  - macOS: BlackHole aggregate-device helper (detect + guide), then a native
    Core Audio process tap.
- Pause/resume recording; crash-recovery for in-progress transcripts.

## Interface
- Desktop GUI + system-tray control.
- Installers / OTA updates / guided onboarding.

## Intelligence
- Meeting-type → summary templates (marry existing meeting types to templates).
- Multi-language summaries.
- General (non-KT) audio import + re-transcription.
- Anthropic/Claude LLM provider, including god-mode tool-calling.

## Output
- PDF / DOCX export.

## Integrations
- Calendar integration + automatic meeting detection.

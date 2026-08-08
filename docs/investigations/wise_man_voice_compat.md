# Wise Man Voice Input/Output — Browser Compatibility Matrix

CC-1 Wise Man directive v3, Sec 7. Real, dated compatibility data, sourced —
not assumed. Access date: 2026-08-08.

## SpeechRecognition (speech-to-text)

Sources: https://caniuse.com/speech-recognition (accessed 2026-08-08),
https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition (accessed
2026-08-08).

| Browser | Support | Notes |
|---|---|---|
| Chrome (desktop) | Partial, `webkitSpeechRecognition` prefix | Server-based recognition — see privacy note below |
| Edge (desktop) | Not supported per caniuse.com's own table | UNCERTAIN — Edge is Chromium-based and typically inherits Chrome's `webkitSpeechRecognition`, which conflicts with caniuse's "not supported" listing; not independently re-verified in-browser this session. Reported as-is from the source rather than silently corrected. |
| Safari (desktop) | Partial, from v14.1 | `webkitSpeechRecognition` prefix |
| Safari (iOS) | Partial, from v14.5 | `webkitSpeechRecognition` prefix |
| Firefox | **Not supported — disabled by default** | Confirmed: MDN and caniuse agree. Firefox implements the API surface but ships it disabled. |
| Chrome for Android | Reported "Not supported" by caniuse | UNCERTAIN — conflicts with desktop Chrome's own partial support and with widely-reported real-world Android Chrome STT usage; likely a caniuse data-tracking gap for the mobile variant specifically, not independently re-verified in-browser this session. |

**PRIVACY DISCLOSURE REQUIREMENT (confirmed, MDN):** "On some browsers, like
Chrome, using Speech Recognition on a web page involves a server-based
recognition engine. Your audio is sent to a web service for recognition
processing, so it won't work offline." This is real and must be disclosed
to the user before they use voice input — see the privacy note requirement
below.

## SpeechSynthesis (text-to-speech)

Source: https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesis
(accessed 2026-08-08) — reported **Baseline Widely available**, supported
across Chrome, Edge, Safari (desktop + iOS), Firefox, and Android Chrome
since September 2018. Materially better support than SpeechRecognition.

**iOS Safari user-gesture requirement:** widely reported in real-world use
that iOS Safari requires a user gesture (e.g. a button tap) before
`speechSynthesis.speak()` will actually produce audio — **not formally
documented in the MDN page fetched for this report**, so this is recorded
as a known real-world implementation detail, not a sourced fact with a
citable spec line. Wise Man's TTS toggle button itself is a user gesture
(the visible speaker-icon click), which should satisfy this requirement in
practice, but this has not been independently verified in a real iOS Safari
session in this build.

## What Wise Man does with this

- **Feature detection, not assumption:** `WiseMan.tsx` checks for
  `window.SpeechRecognition || window.webkitSpeechRecognition` and
  `"speechSynthesis" in window` at mount time and hides the mic/speaker
  controls entirely when unsupported — never a dead button (Sec 7's
  explicit requirement), verified in
  `website/__tests__/WiseMan.test.tsx`'s "does not show a mic button
  when SpeechRecognition is unsupported" / "...speechSynthesis
  is unsupported" tests.
- **Transcribed text enters the same `sendMessage()` typed text uses** — no
  separate code path, asserted directly in
  `website/__tests__/wiseManGuardrail.test.ts`'s "all four input shapes...
  call the SAME shared fetch code path" test (voice-transcribed text is one
  of the four shapes exercised there).
- **No paid third-party STT/TTS** — browser-native only, per the directive's
  explicit instruction.
- **Privacy note:** the persistent disclaimer in the widget
  (`website/lib/wiseMan/disclaimer.ts`) is currently the human-owned
  TODO(human) placeholder and does not yet include the Chrome-audio-to-
  remote-service disclosure above. **Open item for GATE C**: the real
  disclaimer text must include this before voice input ships to real
  traffic.

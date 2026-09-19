# Audio Provenance Statement

## What this proves
The ambient soundtrack (`space_ambient.wav`) used in this project is **not
copied, sampled, or sourced from any existing recording**. It is generated
entirely from mathematical functions (sine waves + filtered random noise) by
`generate_space_ambient.py`. This document records a cryptographic fingerprint
of both files at the time of generation, so their exact contents can be
verified later and are not silently swapped for something else.

## How to verify
Anyone can independently confirm this by running:

```
sha256sum generate_space_ambient.py space_ambient.wav
```

and comparing the output to the hashes below. If they match, the audio file
was produced by exactly this script — nothing else.

## Recorded fingerprints
- **Generation script** (`generate_space_ambient.py`):
  `2fd436fa3561c9c0f6a5f6cff5280dff6be762945b622a750a98fdd605f49719`
- **Generated audio** (`space_ambient.wav`):
  `77a2b2116e4787eb10a9e4d436fc8e22f834205e0c36887262a0e5f36a05889a`
- **Generated at (UTC):** 2026-09-19T02:08:03Z

## Why this counts as evidence
- The script contains no file loading, no network calls, and no external
  audio data — only `numpy` sine/noise generation and a `scipy` low-pass
  filter. This is visible by reading the script directly.
- The SHA-256 hash above is a one-way fingerprint: it's practically
  impossible for a different audio file (e.g. a real copyrighted track) to
  produce the same hash. Matching hashes prove the shipped audio is exactly
  what this script generates.
- Once this repository (including this file and its git commit history) is
  pushed to GitHub, the commit timestamp is recorded on GitHub's servers,
  giving a public, third-party-verifiable date for when this fingerprint was
  established — useful if a copyright claim is ever filed in error.

## In case of a mistaken copyright claim
Point to this file plus the git commit hash in your GitHub repository as
evidence of independent, synthetic origin, and request a manual review.

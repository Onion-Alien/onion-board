# Voice backgrounds

These CC0 audio excerpts are bundled for offline playback in the voice changer.
`credits.json` records each creator, source page, CC0 license, source preview,
processing and file hashes. The source recordings and designed spacecraft ambience
were published on Freesound under CC0 1.0. These excerpts use the high-quality MP3
previews, not lossless originals. The software license does not change their CC0 status.

They ship as Ogg Vorbis (libvorbis quality 5), encoded from the 16-bit FLAC loops this
folder held up to commit 64458f0f (`git show 64458f0f:assets/backgrounds/rain.flac`).
That's a second lossy step, chosen to make the installer about 5 MB smaller: measured
through the app's own rendering (as is, sped up and pitched, slowed with effects) every
third-of-an-octave band stays within 1 dB of the FLAC, and the loop seams gain no click.
`credits.json` keeps each FLAC's hash (`flac_sha256`) beside the shipped file's.

The files are decoded on a worker, never in an audio callback. Preview and live
playback use the same loops. No download, account or network access is needed.

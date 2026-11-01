- When the app closed (End task, a crash, the power) while it was getting FFmpeg, Tor or
  an add-on's Python, the half-downloaded files stayed on disk for good once that helper
  came from somewhere else (up to 115 MB for FFmpeg). The next start clears them, and a
  copy an update had moved aside is put back instead of being lost.

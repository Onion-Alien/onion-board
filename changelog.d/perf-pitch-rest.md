- The pitch changer, Natural sound and Voice size, and sounds played sped up use less CPU
  (the same sound): the pitch changer's search for where to join the voice back together
  runs as native code, the voice-shape step takes about a third of the time it did, and
  filters on stereo sound run up to three times as fast.

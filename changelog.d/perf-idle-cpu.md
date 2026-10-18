- The board uses less CPU while it sits idle: the audio engine does less work on blocks
  where nothing plays, and Bun and Hoot reuse the shapes that don't change between frames.
  Nothing you hear or see changes.

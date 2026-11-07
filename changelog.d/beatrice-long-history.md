- *Update AI voices* now gets a newer add-on when there is one, then sets it up again. It
  used to only run the install, so a copy already installed never got a new voice model.
- AI voices 0.4.0: the normal (20 ms) model keeps 16 seconds of your speech as context instead
  of 4, the same trained voices. In a matched test on one recording, Bear said one word more
  clearly. It adds no 16 second wait, but it takes about twice the CPU while you talk. *Use
  less CPU* keeps the 4 second model, and a PC too slow for the normal one now gets that
  model by itself (about 40 ms more delay).

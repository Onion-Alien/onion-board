- Mic effect: on a mic whose driver never starts an effect in its endpoint slot (some
  virtual mics), the set-up no longer fails with "Windows didn't start it yet": it
  moves to the mic's stream slot, which most apps record through, and stays there.

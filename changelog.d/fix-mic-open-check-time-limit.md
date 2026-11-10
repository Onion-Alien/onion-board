- The mic set-up no longer gives up as "stuck" when Windows' audio stops answering after its
  audio restart: a mic check that hangs counts as a mic that won't open, so the set-up
  restarts Windows' audio once more within a minute instead of waiting five.

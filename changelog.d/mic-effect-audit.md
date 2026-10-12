- Mic effect fixes from a code review: turning sounds off in "add to my mic" mode now
  fades out instead of playing the last queued bit; Windows can no longer unload the
  effect while it's still handing it out; a mic stream that paused for a while no longer
  writes over another app's entry when it comes back; and a second copy of the board
  starting up can no longer take over the mic from the first one.

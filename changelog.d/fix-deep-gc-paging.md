- Fix: on a PC short on memory, the app could freeze for 10 seconds to minutes at a
  time, sounds included, while it sat in the background (and Windows could call it Not
  Responding). Its memory clean-up read the whole app back from disk; it now waits until
  you're back in the window and the PC has memory to spare.

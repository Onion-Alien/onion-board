- Two more freezes on PCs short of memory: checking which game is in front (for *Who's
  listening*) asked Windows on the window's own thread every few seconds, and one PC
  sat in it for minutes; it now runs on a helper thread. The anonymous usage count
  reads its saved problem reports there too, never on the window.

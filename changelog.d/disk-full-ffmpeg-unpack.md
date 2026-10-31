- Fixed: a download that failed because the disk is full now says so ("The disk is full")
  instead of "the downloader ran into a problem", and doesn't suggest a newer downloader.
- Fixed: getting FFmpeg failed with "access denied" when an antivirus was still scanning the
  new ffmpeg.exe; it now waits a few seconds for it.

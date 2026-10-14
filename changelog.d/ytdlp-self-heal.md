- A link that fails to download because the downloader (yt-dlp) is out of date now shows
  an *Update downloader* button: one click gets the newest and tries the link again.
- Updating the downloader never breaks it any more: it skips a yt-dlp that needs a newer
  Python than the app has, and a downloaded copy that won't start is dropped for the
  built-in one (and never fetched again).

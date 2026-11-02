# Free sound packs

Ready-made boards anyone can add to Onion Board in one click: **Sounds tab → Backup →
Free sound packs**. The list the app shows is
[catalog.json](catalog.json).

## Share your own pack

1. In Onion Board, put the sounds in a category of their own. Give them names, and
   pictures and hotkeys if you like.
2. **Backup → Export this category** saves it as a zip.
3. Open the [Share a sound pack](https://github.com/Onion-Alien/onion-board/issues/new?template=sound-pack.yml)
   form (*Share a pack* on the Free sound packs page opens it too), drag the zip
   in, and say where each sound comes from.

Once it's checked, it shows up on everyone's Free sound packs page. No app update needed.

## The rules

There are two kinds of pack, with different rules.

**Packs stored here** (a zip on this project's GitHub releases, like every shared pack):

- **Every sound and picture is CC0** (public domain), or CC BY with the credits inside
  the pack (like the GM pack). Either you made it and release it that way, or whoever
  made it published it that way (Freesound, OpenGameArt, Wikimedia Commons and others
  mark it on each file). "Free to download" isn't the same thing.
- Nothing ripped from games, films, shows, songs or meme videos.
- Nothing hateful, sexual or meant to scare people into thinking something real is
  happening (fake alarms, sirens over a call…).
- Up to 300 MB, any sound format Onion Board plays. Levels roughly matched, please:
  a sound that blasts people's ears gets sent back.

**Links packs** (maintainers only, see below) are just a list of links to sounds
already public on a sound site. This project stores none of them: each person's app
downloads them from that site when they press *Add*. The sounds belong to their owners,
and the app says so on the pack. Own one of them and want it out? Open an
[issue](https://github.com/Onion-Alien/onion-board/issues) or email
**onionboard.contact@proton.me**, and its link comes off the list.

## Links packs (maintainers)

A pack can also be just a list of links to [Myinstants](https://www.myinstants.com)
sounds, in place of a zip: nothing of it is stored here. When someone presses *Add*,
the app downloads each sound from Myinstants itself (through the same switch, proxy and
Tor settings as a pasted Myinstants link), puts them on the board as one pack, and
says how many it skipped because they're gone from there. The first six are the
pack's preview. An entry has `links` instead of `url`, `sha256` and `preview`:

```json
{"id": "memes", "name": "Meme sounds", "emoji": "😂", "tags": ["Memes"],
 "description": "...", "author": "...",
 "links": [{"name": "Vine boom", "category": "Memes",
            "url": "https://www.myinstants.com/media/sounds/vine-boom.mp3"}]}
```

Only `https://www.myinstants.com/media/sounds/<file>.mp3` links are kept (up to 300).
Versions before links packs skip such an entry.

## Checking a pack (maintainers)

```
python scripts/checks/check_pack.py pack.zip --id short-name --name "Pack name" --tag pack-short-name --about "..." --author "..." --preview "Sound one" --preview "Sound two" ...
gh release create pack-short-name pack.zip short-name-preview.zip --prerelease --title "Pack name (free sound pack)"
```

`--preview` (up to six, by name) writes `short-name-preview.zip` next to the pack: those
sounds cut to 7 seconds, with their pictures. *Preview* on the pack's card plays them so
people can hear a few before adding it; a pack without one just shows no samples.

Listen to it, check each sound's source and licence, then add the printed entry to
`catalog.json` in a pull request. The app only downloads packs from this project's own
releases and checks every one against the SHA-256 in the list, so a pack can't change
after it was checked.

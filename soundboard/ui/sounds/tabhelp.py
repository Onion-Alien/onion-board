"""A tab's help pop-up (`TabHelpPopup`): what the tab is for, on the shared card frame
(kit/modalframe.py) with Bun or Hoot in its header. `dialogs` re-exports it."""
from __future__ import annotations

from soundboard.i18n import _
from soundboard.ui.kit.modalframe import InfoCard


def tab_card(key: str) -> tuple[str, list[tuple[str, str, str]]] | None:
    """The About this tab card of tab `key` (tabcontrol.TAB_KEYS): its subtitle and its
    points, (icon, bold line, quieter line). None for a tab without one."""
    cards = {
        "sounds": (_("Your sound buttons, ready to play."), [
            ("plus", _("Add sounds"),
             _("Use the Add button, drop files or folders here, or search the web.")),
            ("play", _("Play one"),
             _("Double-click it or press Enter. The player bar plays what's picked.")),
            ("edit", _("Make it yours"),
             _("Right-click a sound for its hotkey, effects, categories and picture.")),
            ("mic", _("Your mic and headphones"),
             _("The strip at the bottom shows your mic, what others hear and your "
               "headphones.")),
        ]),
        "radio": (_("Live stations from all over the world."), [
            ("search", _("Find a station"),
             _("Click a dot on the map, or search by name, genre, country or city.")),
            ("headphones", _("Listen yourself"), _("It plays in your headphones.")),
            ("live", _("Send it out"),
             _("Press Send to others and whoever's listening hears it too.")),
            ("record", _("Keep a bit"), _("Record saves a piece of it as a sound button.")),
        ]),
        "apps": (_("Let others hear a program that's playing."), [
            ("apps", _("Pick a program"),
             _("A music player, a browser, a game, even a call in another app.")),
            ("volume", _("On its own volume"),
             _("It goes out the same way your sounds do, and keeps playing on your "
               "speakers.")),
            ("check", _("Only that program"), _("Nothing else you play is touched.")),
        ]),
        "triggers": (_("Sounds that play by themselves."), [
            ("eye", _("Watches your game"),
             _("Plays a sound when a picture shows up: a \"YOU DIED\", a rare spawn, a "
               "queue popping.")),
            ("puzzle", _("An add-on"), _("It's the Onion Watch add-on.")),
            ("shield", _("Stays on your PC"),
             _("The screen is never saved or sent anywhere.")),
        ]),
        "voice": (_("Change how you sound, live."), [
            ("voice", _("Voice changer"),
             _("Pick a voice to turn it on for whoever you send sounds to.")),
            ("robot", _("AI voices"), _("Turn your voice into someone else's.")),
            ("speech", _("Type to talk"), _("Type a line and a computer voice says it.")),
            ("ear", _("Try it first"),
             _("Press Hear what they hear at the bottom to check it.")),
        ]),
        "setup": (_("Where your sounds go, and how they sound."), [
            ("cable", _("Where sounds go"),
             _("Straight into your mic, the virtual cable, another device or nobody.")),
            ("headphones", _("Your devices"),
             _("Your mic, your headphones and who's listening.")),
            ("sliders", _("Equalizer"), _("Tune the sound before it goes out.")),
            ("record", _("Test it"), _("Records what goes out and plays it back.")),
        ]),
        "store": (_("Sounds and voices other players share."), [
            ("play", _("Hear it first"), _("Play any sound before you add it.")),
            ("plus", _("Add in a click"), _("Add the ones you like to your board.")),
            ("like", _("Vote"), _("The best ones rise to the top.")),
            ("upload", _("Share yours"),
             _("Share a sound puts one of yours up for everyone once it's been checked.")),
        ]),
    }
    return cards.get(key)


class TabHelpPopup(InfoCard):
    """A help card with a mascot: Escape, the ✕, Got it or a click outside closes it, and
    the focus goes back to what opened it.

    With `key` (a tab, tabcontrol.TAB_KEYS) it shows that tab's subtitle and points
    (tab_card); otherwise `text` is its one paragraph (`body`; set its format to rich
    text for bold words). `owl`: Hoot instead of Bun (the Triggers tab's)."""

    def __init__(self, title: str, text: str = "", *, key: str = "", owl: bool = False,
                 parent=None):
        card = tab_card(key) if key else None
        subtitle, points = card if card is not None else ("", [])
        super().__init__(title, subtitle, mascot="owl" if owl else "bun", points=points,
                         text="" if card is not None else text, parent=parent)

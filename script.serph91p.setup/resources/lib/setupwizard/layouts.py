"""Curated navigation adapters, not copies of authenticated device configuration."""
from pathlib import Path
from xml.etree import ElementTree as ET
from .config import (AMBER_MENU, _profile, apply_payloads, apply_template)
from .templates import minimal_layout_template

BASE = 'special://home/addons/script.serph91p.setup/resources/playlists/'
NAVIGATION = (
    ('Live TV', 'ActivateWindow(TVChannels)'),
    ('Programm / EPG', 'ActivateWindow(TVGuide)'),
    ('YouTube', 'ActivateWindow(Videos,plugin://plugin.video.youtube/,return)'),
    ('Filme', 'ActivateWindow(Videos,videodb://movies/titles/,return)'),
    ('Serien', 'ActivateWindow(Videos,videodb://tvshows/titles/,return)'),
    ('Twitch', 'ActivateWindow(Videos,plugin://plugin.video.twitch/,return)'),
    ('Gronkh.tv', 'ActivateWindow(Videos,plugin://plugin.video.gronkhtv/,return)'),
    ('Filme fortsetzen', 'ActivateWindow(Videos,' + BASE + 'continue-movies.xsp,return)'),
    ('Serienfolgen fortsetzen', 'ActivateWindow(Videos,' + BASE + 'continue-episodes.xsp,return)'),
    ('Neue Filme', 'ActivateWindow(Videos,videodb://recentlyaddedmovies/,return)'),
    ('Neue Folgen', 'ActivateWindow(Videos,videodb://recentlyaddedepisodes/,return)'),
)


def amber_menu():
    """Skin Shortcuts XML format from official Amber's shortcuts/mainmenu.DATA.xml."""
    root = ET.Element('shortcuts')
    actions = NAVIGATION + (
        ('Setup-Assistent', 'RunScript(script.serph91p.setup)'),
        ('Einstellungen', 'ActivateWindow(Settings)'),
    )
    for index, (label, action) in enumerate(actions):
        node = ET.SubElement(root, 'shortcut')
        ET.SubElement(node, 'defaultID').text = 'serph91p-' + str(index)
        ET.SubElement(node, 'label').text = label
        ET.SubElement(node, 'label2').text = 'Serph91P Setup'
        ET.SubElement(node, 'icon').text = 'icons/mainmenu/videos.png'
        ET.SubElement(node, 'action').text = action
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def describe_layout(profile_id):
    if profile_id == 'arctic':
        return ('Arctic: Film-/Serienwidgets und Twitch-/YouTube-Hubs. '
                'Generische Bibliotheksansichten benötigen deine eigene Emby-Synchronisation. '
                'Die gleichen zusätzlichen Ziele findest du unter Inhalte öffnen im Assistenten.')
    if profile_id == 'amber':
        return ('Amber: übersichtliches Hauptmenü für Live TV, EPG, YouTube, Filme, Serien, '
                'Twitch und Gronkh.tv sowie Fortsetzen/neue Inhalte. '
                'Das ersetzt nur Ambers Skin-Shortcuts-Hauptmenü, mit Sicherung. '
                'Keine Arctic-Widgetoptik; Kodi/SkinShortcuts muss die Darstellung beim '
                'manuellen Skinwechsel erzeugen. Andere Skins und deren Hauptmenüs bleiben unverändert.')
    if profile_id == 'touch':
        return ('Touch: Kodis mitgelieferter Estuary mit aktiviertem Touchmodus. '
                'Die Änderung erfolgt mit Sicherung und Readback über Kodis Laufzeit-Schnittstelle, '
                'nicht durch Schreiben aktiver Skin-Dateien. '
                'Identische Inhaltsziele erreichst du im Assistenten über Inhalte öffnen. '
                'Keine frei konfigurierbaren Arctic-Hubs oder identischen Widgets versprochen. '
                'Es werden keine zwischengespeicherten Favoriten überschrieben.')
    raise ValueError('unknown profile')


def apply_layout(profile: Path, backup: Path, profile_id: str):
    describe_layout(profile_id)  # Unknown profiles fail before path access.
    if profile_id == 'arctic':
        return apply_template(profile, backup, minimal_layout_template())
    if profile_id == 'amber':
        return apply_payloads(profile, backup, {AMBER_MENU: amber_menu()}, 'amber')
    _profile(profile)
    return []  # Native touch controls stay native; consistent actions live in the wizard.

"""Explicit skin profile choices; layouts are only advertised when supported."""
from dataclasses import dataclass

@dataclass(frozen=True)
class SkinProfile:
    key: str
    addon_id: str
    minimum: tuple
    label: str
    layout_supported: bool
    warning: str = ''

PROFILES = (
    SkinProfile('arctic', 'skin.arctic.fuse.3', (3, 3, 12), 'Schön: Arctic Fuse 3', True),
    # Version is the verified official Omega skin metadata version; Kodi resolves
    # the skin's declared helper dependencies through its repository manager.
    SkinProfile('amber', 'skin.amber', (3, 99, 2), 'Schnell: Amber (historischer Pi 5 Skin)', True),
    SkinProfile('touch', 'skin.estuary', (4, 0, 0), 'Touch: Estuary mit Touchmodus', True,
                'Estouchys letzter Quellstand ist von 2024; aktive Pflege ist nicht bestätigt. '
                'Darum verwendet dieses Profil Kodis mitgelieferten Estuary mit Touchmodus. '
                'Die Touch-Oberfläche unterscheidet sich von Arctic. Fortfahren?'),
)

def requirements_for(profile, arctic_requirements, profile_requirements, shared_requirements):
    return ((arctic_requirements if profile.key == 'arctic' else
             (next(r for r in profile_requirements if r.addon_id == profile.addon_id),))
            + shared_requirements)
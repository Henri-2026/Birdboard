# This file is part of Birdboard (based on BeeRef, GPL-3.0-or-later).

APPNAME = 'Birdboard'
APPNAME_FULL = f'{APPNAME} Reference Board'
VERSION = '1.1.0'
WEBSITE = 'https://github.com/Henri-2026/Birdboard'
COPYRIGHT = 'Birdboard v1.1.0 (based on open-source BeeRef)'

CHANGED_SYMBOL = '✎'

THEMES = {
    'light': {
        'Scene:Canvas': (233, 234, 236),      # #E9EAEC Studio Light Gray
        'Scene:Text': (28, 28, 34),           # #1C1C22 Crisp Dark Ink
        'Scene:Selection': (58, 60, 66),      # #3A3C42 Refined Dark Charcoal Gray
        'Welcome:Bg': '#E9EAEC',
        'Welcome:TextPrimary': '#27272A',
        'Welcome:TextSecondary': '#71717A',
    },
    'dark': {
        'Scene:Canvas': (26, 26, 29),         # #1A1A1D Penart Matte Dark
        'Scene:Text': (242, 242, 247),        # #F2F2F7 Penart Primary Text
        'Scene:Selection': (168, 170, 178),   # #A8AAB2 Crisp Slate Gray on Dark
        'Welcome:Bg': '#1A1A1D',
        'Welcome:TextPrimary': '#F2F2F7',
        'Welcome:TextSecondary': '#9A9AA2',
    },
}

ACTIVE_THEME = 'light'

COLORS = {
    # Legacy keys updated dynamically by set_active_theme()
    'Active:Base': (250, 250, 252),
    'Active:AlternateBase': (240, 240, 244),
    'Active:Window': (233, 234, 236),
    'Active:Button': (242, 242, 246),
    'Active:Text': (28, 28, 34),
    'Active:HighlightedText': (255, 255, 255),
    'Active:WindowText': (28, 28, 34),
    'Active:ButtonText': (28, 28, 34),
    'Active:Highlight': (58, 130, 247),
    'Active:Link': (58, 130, 247),

    'Disabled:Base': (235, 235, 238),
    'Disabled:Window': (233, 234, 236, 120),
    'Disabled:WindowText': (154, 154, 162),
    'Disabled:Light': (0, 0, 0, 0),
    'Disabled:Text': (154, 154, 162),

    'Scene:Selection': (58, 60, 66),
    'Scene:Canvas': (233, 234, 236),
    'Scene:Text': (28, 28, 34),
}


def set_active_theme(theme_name: str) -> dict:
    global ACTIVE_THEME
    if theme_name not in THEMES:
        theme_name = 'light'
    ACTIVE_THEME = theme_name
    t = THEMES[theme_name]
    COLORS['Scene:Canvas'] = t['Scene:Canvas']
    COLORS['Scene:Text'] = t['Scene:Text']
    COLORS['Scene:Selection'] = t['Scene:Selection']
    return t


def get_active_theme() -> dict:
    return THEMES.get(ACTIVE_THEME, THEMES['light'])

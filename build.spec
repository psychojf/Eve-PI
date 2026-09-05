# -*- mode: python ; coding: utf-8 -*-
#
# Deux sortes de fichiers, et la différence compte.
#
#   `datas` ci-dessous voyage *dans* l'exe. PyInstaller en mode un-fichier le
#   déballe au lancement dans un dossier temporaire dont le chemin est
#   `sys._MEIPASS`. C'est `bundled_path()` qui va l'y chercher.
#
#   Ce que l'application *écrit* — la bibliothèque, l'historique, la config —
#   ne peut pas vivre là : ce dossier est effacé à la fermeture. Ces
#   fichiers-là restent à côté de l'exe, via `get_base_path()`, et ne sont
#   donc pas listés ici.
#
# Rien de tout cela n'était vrai avant le 2026-09-04 : `_MEIPASS` n'était
# consulté nulle part, donc les 3,6 Mo embarqués ci-dessous étaient du poids
# mort et l'exe ne trouvait ses planètes que si un dossier `data` se trouvait
# à côté de lui.

block_cipher = None

a = Analysis(
    ['PI.py'],
    pathex=[],
    binaries=[],
    datas=[
        # L'icône de la fenêtre. Elle est aussi donnée à EXE(icon=...) plus
        # bas, mais ce sont deux usages : l'un habille le fichier, l'autre la
        # fenêtre — et le second doit être lisible à l'exécution.
        ('future.ico', '.'),

        # Le Scout résout, parcourt les stargates et rend les planètes depuis
        # cet instantané, donc il doit voyager ou l'outil retombe sur l'ESI.
        ('data/scout-universe.json', 'data'),

        # L'artwork des huit types de planète : sans lui, la carte dessine une
        # colonie sur du vide.
        ('data/planets', 'data/planets'),

        # Les vignettes du Scout, une par type de planète.
        ('data/planet_icons', 'data/planet_icons'),

        # `planet_radii.json` (8,3 Mo) et `system_names.json` ne sont
        # délibérément PAS embarqués. Ce sont les caches du chemin de secours
        # ESI, et ce chemin ne s'ouvre que si l'instantané SDE manque — voir
        # le démarrage : `if _offline_universe() is None`. L'instantané étant
        # juste au-dessus dans cette liste, il ne manque jamais. Les livrer
        # ajouterait 8 Mo à l'exe pour du code qui ne tourne pas.
    ],
    hiddenimports=[
        'src.pi_data', 'src.debug_log',
        # Les services : PyInstaller suit les imports, mais ceux-ci arrivent
        # par des chemins qu'il ne voit pas toujours (imports tardifs dans les
        # modules d'UI, pour casser les cycles avec PI).
        'src.services.template_service', 'src.services.scout_universe',
        'src.services.mixed_p2', 'src.services.colony_model',
        'src.services.library_cards', 'src.services.template_describe',
        'src.services.stage_plan', 'src.services.stage_edit',
        'src.services.grace', 'src.services.factory_runtime',
        'src.services.grow_to_supply', 'src.services.history',
        'src.services.sourcing', 'src.services.eve_time',
        # Les écrans et panneaux flottants.
        'src.ui.screens', 'src.ui.factory_timer', 'src.ui.stage_notice',
        'src.ui.collect_bar',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Eve PI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='future.ico',
)

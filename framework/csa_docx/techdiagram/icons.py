"""Device icons on a 24x24 grid, drawn for this renderer (no third-party licence to carry).

Style (from the CSA IT/OT design example): heavy navy outlines on white bodies, a light blue fill for screens and
cylinder tops, teal accents (status dots, waves, trend lines) and an orange shield for firewalls. The enclosing
<g> sets stroke = the kind's colour and fill = none; elements that need another fill or stroke carry it
themselves, so the same markup draws in the SVG, the PNG and the Word drawing.
"""

NAVY = "#203a55"       # outlines, names
TEAL = "#167d8d"       # accents, lines
LIGHT = "#ddedf2"      # screens, cylinder tops
WHITE = "#ffffff"
ORANGE = "#d27a35"     # security boundary devices
ORANGE_FILL = "#fff3e7"
GREY = "#8c959f"
RED = "#c4432b"

_W = f'fill="{WHITE}"'
_L = f'fill="{LIGHT}"'
_DOT = f'fill="{TEAL}" stroke="none"'
_ACC = f'stroke="{TEAL}"'


def _dot(x, y, r=1.15):
    return f'<circle cx="{x}" cy="{y}" r="{r}" {_DOT}/>'


def _monitor(inner: str = "", screen: bool = True) -> str:
    """Monitor frame with a light screen and a stand; `inner` draws on the screen."""
    scr = f'<rect x="5" y="5.5" width="14" height="8" {_L} stroke="none"/>' if screen else ""
    return (f'<rect x="3" y="3.5" width="18" height="12" rx="1" {_W}/>{scr}{inner}'
            '<path d="M12 15.5v4.5M7.5 20.5h9"/>')


def _stack(n: int = 3) -> str:
    """Stacked server units with a teal status dot each."""
    h = {3: 5.6, 2: 8.5}[n]
    gap = (20 - n * h) / (n - 1) if n > 1 else 0
    out = []
    for i in range(n):
        y = 2 + i * (h + gap)
        out.append(f'<rect x="3" y="{y:.2f}" width="18" height="{h:.2f}" rx="1.3" {_W}/>' + _dot(6.6, round(y + h / 2, 2)))
    return "".join(out)


def _cylinder(inner: str = "") -> str:
    return (f'<path d="M4 5.5v13c0 1.7 3.6 3 8 3s8-1.3 8-3v-13" {_W}/>'
            '<path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" stroke-width="1.3"/>'
            f'<ellipse cx="12" cy="5.5" rx="8" ry="3" {_L}/>{inner}')


ICONS = {
    # cylinder with a light top
    "database": _cylinder(),
    # three stacked server units
    "app_server": _stack(3),
    # log server: document with teal lines
    "logging": f'<path d="M5.5 2h9.5l4.5 4.5V22h-14z" {_W}/><path d="M15 2v4.5h4.5"/>'
               f'<path d="M8.5 11.5h7.5M8.5 15h7.5M8.5 18.5h4.5" {_ACC}/>',
    # operator workstation: monitor
    "terminal": _monitor(),
    # jump host: monitor with a teal key
    "jump_host": _monitor(f'<circle cx="9" cy="9.5" r="1.8" fill="none" {_ACC}/><path d="M10.8 9.5h5.2M14.6 9.5v1.8" {_ACC}/>'),
    # radio mast with teal waves
    "radio": f'<path d="M12 10v11M8 21.5h8M9 21.5l3-11 3 11"/>{_dot(12, 8, 1.7)}'
             f'<path d="M8.2 4.8a5.5 5.5 0 0 0 0 6.4M15.8 4.8a5.5 5.5 0 0 1 0 6.4" {_ACC}/>',
    # domain controller: shield with a teal key
    "directory": f'<path d="M12 2l8 3v6c0 5-3.4 9.3-8 11-4.6-1.7-8-6-8-11V5z" {_W}/>'
                 f'<circle cx="12" cy="9.5" r="2.3" fill="none" {_ACC}/><path d="M12 11.8V17M12 15h2.2" {_ACC}/>',
    # globe (DNS / internet)
    "globe": f'<circle cx="12" cy="12" r="9.5" {_W}/><path d="M2.5 12h19" {_ACC}/>'
             '<path d="M12 2.5a14 14 0 0 1 0 19M12 2.5a14 14 0 0 0 0 19"/>',
    # internal addresses: three nodes on a teal tree
    "network": f'<path d="M12 7.5v4.5M5 16.5V12h14v4.5" {_ACC}/>'
               f'<rect x="8.5" y="2" width="7" height="5.5" rx="1" {_W}/><rect x="1.5" y="16.5" width="7" height="5.5" rx="1" {_W}/>'
               f'<rect x="15.5" y="16.5" width="7" height="5.5" rx="1" {_W}/>',
    # backup target: drive with a teal arrow
    "backup": f'<rect x="2.5" y="13" width="19" height="8" rx="1.5" {_W}/>{_dot(6.5, 17)}'
              f'<path d="M12 2.5v7.5M8.5 6.5 12 10l3.5-3.5" {_ACC}/>',
    # mail
    "mail": f'<rect x="2.5" y="4.5" width="19" height="15" rx="1.5" {_W}/><path d="m2.5 6.5 9.5 7 9.5-7" {_ACC}/>',
    # firewall: orange shield with a four-point star
    "firewall": f'<path d="M3.5 3.5h17l-1 10.5L12 21l-7.5-7z" fill="{ORANGE_FILL}" stroke="{ORANGE}"/>'
                f'<path d="M12 7.6l1 2.6 2.6 1-2.6 1-1 2.6-1-2.6-2.6-1 2.6-1z" fill="{ORANGE}" stroke="none"/>',
    # generic server: two units
    "server": _stack(2),
    # PLC: rack with I/O modules and teal LEDs
    "plc": f'<rect x="2" y="5" width="20" height="14" rx="1.3" {_W}/><path d="M7 5v14M12 5v14M17 5v14"/>'
           + _dot(4.5, 8.5, 0.9) + _dot(9.5, 8.5, 0.9) + _dot(14.5, 8.5, 0.9) + _dot(19.5, 8.5, 0.9),
    # RTU: field box with a teal antenna
    "rtu": f'<path d="M12 9V3M9 5l3-2 3 2" {_ACC}/><rect x="4" y="9" width="16" height="12" rx="1.3" {_W}/>'
           f'<path d="M7.5 13.5h4.5M7.5 17h6"/>{_dot(16, 15.3)}',
    # HMI: monitor with a teal gauge
    "hmi": _monitor(f'<path d="M8 12.6a4 4 0 0 1 8 0M12 12.6l2-2.6" fill="none" {_ACC}/>'),
    # historian: cylinder with a teal trend
    "historian": _cylinder(f'<path d="M7 18l3-3 2 2 4.5-4.5" {_ACC}/>'),
    # network switch: box with light port squares
    "switch": f'<rect x="1.5" y="7.5" width="21" height="9" rx="1.5" {_W}/>'
              + "".join(f'<rect x="{x}" y="10.5" width="2.3" height="3" {_L} stroke-width="0.9"/>' for x in (4, 7.6, 11.2, 14.8, 18.4)),
    # router: circle with teal arrows
    "router": f'<circle cx="12" cy="12" r="9.5" {_W}/><path d="M7.5 12h9M12 7.5v9M14 6l-2-2-2 2M14 18l-2 2-2-2" {_ACC}/>',
    # virtualisation host: base with two guests
    "hypervisor": f'<rect x="2" y="15" width="20" height="6.5" rx="1.3" {_W}/>{_dot(5.5, 18.25)}'
                  f'<rect x="3.5" y="2.5" width="7.5" height="9.5" rx="1" {_L}/><rect x="13" y="2.5" width="7.5" height="9.5" rx="1" {_L}/>',
    # storage: two shelves
    "storage": f'<rect x="3" y="3" width="18" height="7" rx="1.3" {_W}/><rect x="3" y="12" width="18" height="7" rx="1.3" {_W}/>'
               f'{_dot(6.5, 6.5)}{_dot(6.5, 15.5)}<path d="M3 22h18"/>',
    # time source: clock with teal hands
    "time": f'<circle cx="12" cy="12" r="9.5" {_W}/><path d="M12 6.5V12l3.5 2.5" {_ACC}/>',
    # wireless access point: base with teal waves
    "wireless": f'<rect x="3.5" y="15" width="17" height="6.5" rx="1.5" {_W}/>{_dot(7.5, 18.25)}<path d="M12 11v4"/>'
                f'<path d="M8.6 8.6a4.8 4.8 0 0 1 6.8 0M5.8 5.8a8.8 8.8 0 0 1 12.4 0" {_ACC}/>',
    # cloud / external network
    "cloud": f'<path d="M7 19h10.5a4.5 4.5 0 0 0 .6-8.96A6.5 6.5 0 0 0 5.6 9.3 4.9 4.9 0 0 0 7 19z" {_L}/>',
    # API / integration endpoint
    "api": f'<rect x="2" y="4" width="20" height="16" rx="1.5" {_W}/><path d="M9 8.5l-3.5 3.5L9 15.5M15 8.5l3.5 3.5-3.5 3.5" {_ACC}/>',
    # virtual machine: a guest inside a dashed host frame
    "vm": f'<rect x="2.5" y="3" width="19" height="13" rx="1.5" stroke-dasharray="3 2"/>'
          f'<rect x="6" y="6" width="12" height="7" rx="1" {_L}/><path d="M12 16v4.5M7.5 20.5h9"/>',
    # server rack
    "rack": f'<rect x="5" y="2" width="14" height="20" rx="1.3" {_W}/><path d="M5 7h14M5 12h14M5 17h14"/>'
            + _dot(8, 4.5, 0.9) + _dot(8, 9.5, 0.9) + _dot(8, 14.5, 0.9) + _dot(8, 19.5, 0.9),
    # engineering workstation: monitor with a teal gear
    "workstation": _monitor(f'<circle cx="12" cy="9.5" r="1.9" fill="none" {_ACC}/>'
                            f'<path d="M12 6.2v1.2M12 11.6v1.2M8.7 9.5h1.2M14.1 9.5h1.2" {_ACC}/>'),
    # SCADA server: monitor with a teal process trend
    "scada": _monitor(f'<path d="M6.5 12h2.5l1.7-3.5 2.6 5 1.7-2.5h2.5" fill="none" {_ACC}/>'),
    # DHCP: address list with a teal tick
    "dhcp": f'<rect x="3" y="3" width="18" height="18" rx="1.5" {_W}/><path d="M7 8h6M7 12h7M7 16h3.5"/>'
            f'<path d="M13.5 16l2 2 3.5-4" {_ACC}/>',
    # not known
    "unknown": f'<circle cx="12" cy="12" r="9.5" stroke-dasharray="3 2.5" {_W}/>'
               f'<path d="M9.3 9a2.8 2.8 0 0 1 5.4 1c0 1.9-2.7 2.7-2.7 2.7"/><circle cx="12" cy="17" r="1" fill="currentColor" stroke="none"/>',
}

# kind -> (icon, human label, outline colour). One navy for every device, as in the design example; grey and red
# keep "not recorded" and "not evidenced" apart from confirmed systems.
KINDS = {
    "database":   ("database",   "Database server",          NAVY),
    "app_server": ("app_server", "Application server",       NAVY),
    "logging":    ("logging",    "Log server",               NAVY),
    "jump_host":  ("jump_host",  "Jump host",                NAVY),
    "terminal":   ("terminal",   "Operator workstation",     NAVY),
    "radio":      ("radio",      "Radio management",         NAVY),
    "directory":  ("directory",  "Domain controller · DNS",  NAVY),
    "internal":   ("network",    "Internal addresses",       NAVY),
    "internet":   ("globe",      "Internet",                 NAVY),
    "backup":     ("backup",     "Backup target",            NAVY),
    "mail":       ("mail",       "Mail",                     NAVY),
    "firewall":   ("firewall",   "Firewall",                 ORANGE),
    "dns":        ("globe",      "DNS server",               NAVY),
    "time":       ("time",       "Time source",              NAVY),
    "switch":     ("switch",     "Network switch",           NAVY),
    "router":     ("router",     "Router",                   NAVY),
    "hypervisor": ("hypervisor", "Virtualisation host",      NAVY),
    "storage":    ("storage",    "Storage",                  NAVY),
    "plc":        ("plc",        "PLC",                      NAVY),
    "rtu":        ("rtu",        "RTU",                      NAVY),
    "hmi":        ("hmi",        "HMI",                      NAVY),
    "historian":  ("historian",  "Historian",                NAVY),
    "server":     ("server",     "Server",                   NAVY),
    "wireless":   ("wireless",   "Wireless access point",    NAVY),
    "cloud":      ("cloud",      "Cloud / external network", NAVY),
    "api":        ("api",        "API integration",          NAVY),
    "vm":         ("vm",         "Virtual machine",          NAVY),
    "rack":       ("rack",       "Server rack",              NAVY),
    "workstation": ("workstation", "Engineering workstation", NAVY),
    "scada":      ("scada",      "SCADA server",             NAVY),
    "dhcp":       ("dhcp",       "DHCP service",             NAVY),
    "unknown":    ("unknown",    "Role not recorded",        GREY),
    "gap":        ("unknown",    "Gap: not evidenced",       RED),
}

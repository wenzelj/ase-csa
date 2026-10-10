"""Line icons on a 24x24 grid, stroke=currentColor. Drawn for this renderer
(Lucide-style, not copied), so there is no third-party licence to carry."""

ICONS = {
    # stacked cylinder
    "database": '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    # rack server, two units
    "app_server": '<rect x="3" y="3" width="18" height="8" rx="2"/><rect x="3" y="13" width="18" height="8" rx="2"/><path d="M7 7h.01M7 17h.01M11 7h6M11 17h6"/>',
    # log server: document with lines
    "logging": '<path d="M6 2h9l5 5v15H6z"/><path d="M15 2v5h5"/><path d="M9 12h8M9 16h8M9 20h5"/>',
    # monitor
    "terminal": '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/><path d="M6 8l3 2-3 2M11 12h4"/>',
    # monitor with key (jump host)
    "jump_host": '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/><circle cx="8.5" cy="10" r="2.2"/><path d="M10.7 10H17M15 10v2M17 10v2"/>',
    # radio mast with waves
    "radio": '<path d="M12 10v12M8 22h8M9 22l3-12 3 12"/><circle cx="12" cy="8" r="1.6"/><path d="M8.2 4.8a5.5 5.5 0 0 0 0 6.4M15.8 4.8a5.5 5.5 0 0 1 0 6.4M5.4 2.6a9 9 0 0 0 0 10.8M18.6 2.6a9 9 0 0 1 0 10.8"/>',
    # domain controller: shield with key
    "directory": '<path d="M12 2l8 3v6c0 5-3.4 9.3-8 11-4.6-1.7-8-6-8-11V5z"/><circle cx="12" cy="10" r="2.4"/><path d="M12 12.4V17M12 15h2"/>',
    # globe (DNS / internet)
    "globe": '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15 15 0 0 1 0 20M12 2a15 15 0 0 0 0 20"/>',
    # cloud of addresses (internal, not named)
    "network": '<rect x="9" y="2" width="6" height="5" rx="1"/><rect x="2" y="17" width="6" height="5" rx="1"/><rect x="16" y="17" width="6" height="5" rx="1"/><path d="M12 7v5M5 17v-5h14v5"/>',
    # backup target
    "backup": '<rect x="2" y="13" width="20" height="8" rx="2"/><path d="M6 17h.01M10 17h.01"/><path d="M12 3v7M8.5 6.5 12 10l3.5-3.5"/>',
    # mail
    "mail": '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m2 6 10 7 10-7"/>',
    # firewall: brick wall
    "firewall": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v6M15 9v6M9 15v6"/>',
    # generic server (a role is recorded but no specific type matched)
    "server": '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M8 6h8M8 10h8M8 14h3"/><circle cx="15.5" cy="17.5" r="1"/>',
    # PLC: rack with I/O modules
    "plc": '<rect x="2" y="5" width="20" height="14" rx="1.5"/><path d="M7 5v14M12 5v14M17 5v14"/><path d="M4 9h1M9 9h1M14 9h1M19 9h1M4 15h1M9 15h1"/>',
    # RTU: field box with antenna
    "rtu": '<rect x="4" y="9" width="16" height="12" rx="1.5"/><path d="M12 9V3M9 5l3-2 3 2"/><path d="M8 14h3M8 17h5"/><circle cx="16" cy="15" r="1.3"/>',
    # HMI: screen with gauge
    "hmi": '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/><path d="M7 13a5 5 0 0 1 10 0"/><path d="M12 13l2.5-3"/>',
    # historian: cylinder with trend line
    "historian": '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M7 16l3-3 2 2 4-5"/>',
    # network switch
    "switch": '<rect x="2" y="8" width="20" height="8" rx="2"/><path d="M6 12h.01M9 12h.01M12 12h.01M15 12h.01M18 12h.01"/><path d="M6 8V5M12 8V5M18 8V5"/>',
    # router
    "router": '<circle cx="12" cy="12" r="9"/><path d="M8 12h8M12 8v8"/><path d="M14 6l-2-2-2 2M14 18l-2 2-2-2M6 10l-2 2 2 2M18 10l2 2-2 2"/>',
    # virtualisation host
    "hypervisor": '<rect x="2" y="15" width="20" height="6" rx="1.5"/><rect x="4" y="3" width="7" height="9" rx="1"/><rect x="13" y="3" width="7" height="9" rx="1"/><path d="M6 18h.01"/>',
    # storage
    "storage": '<rect x="3" y="3" width="18" height="6" rx="1.5"/><rect x="3" y="11" width="18" height="6" rx="1.5"/><path d="M7 6h.01M7 14h.01M3 21h18"/>',
    # time source
    "time": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    # not known
    "unknown": '<circle cx="12" cy="12" r="10" stroke-dasharray="3 2.5"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
}

# kind -> (icon, human label, accent colour)
KINDS = {
    "database":   ("database",   "Database server",          "#1f6feb"),
    "app_server": ("app_server", "Application server",       "#0e7c66"),
    "logging":    ("logging",    "Log server",               "#8250df"),
    "jump_host":  ("jump_host",  "Jump host",                "#bf3989"),
    "terminal":   ("terminal",   "Operator workstation",     "#bf3989"),
    "radio":      ("radio",      "Radio management",         "#c4432b"),
    "directory":  ("directory",  "Domain controller · DNS",  "#9a6700"),
    "internal":   ("network",    "Internal addresses",       "#57606a"),
    "internet":   ("globe",      "Internet",                 "#57606a"),
    "backup":     ("backup",     "Backup target",            "#57606a"),
    "mail":       ("mail",       "Mail",                     "#57606a"),
    "firewall":   ("firewall",   "Firewall",                 "#cf222e"),
    "dns":        ("globe",      "DNS server",               "#9a6700"),
    "time":       ("time",       "Time source",              "#9a6700"),
    "switch":     ("switch",     "Network switch",           "#0969da"),
    "router":     ("router",     "Router",                   "#0969da"),
    "hypervisor": ("hypervisor", "Virtualisation host",      "#6639ba"),
    "storage":    ("storage",    "Storage",                  "#57606a"),
    "plc":        ("plc",        "PLC",                      "#bc4c00"),
    "rtu":        ("rtu",        "RTU",                      "#bc4c00"),
    "hmi":        ("hmi",        "HMI",                      "#bf3989"),
    "historian":  ("historian",  "Historian",                "#1f6feb"),
    "server":     ("server",     "Server",                   "#0e7c66"),
    "unknown":    ("unknown",    "Role not recorded",        "#6e7781"),
}
